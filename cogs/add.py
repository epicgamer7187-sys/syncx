import asyncio
import logging
import time

import discord
from discord.ext import commands

from config import Config
from utils import add_member_to_guild, err, info, ok, ts, warn

log = logging.getLogger("venice.add")


class Add(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._worker = None
        self._restock = None

    async def cog_load(self):
        self._worker = asyncio.create_task(self.worker_loop())
        self._restock = asyncio.create_task(self.restock_loop())

    async def cog_unload(self):
        for task in (self._worker, self._restock):
            if task:
                task.cancel()

    # ---------------- config helpers ----------------
    async def cfg(self, key, default):
        return await self.bot.db.get_setting_int(key, default)

    async def user_limit(self, guild, user_id):
        if await self.bot.is_owner(discord.Object(id=user_id)):
            return None
        base = await self.cfg("normal_limit", Config.DEFAULT_NORMAL_LIMIT)
        if guild is None:
            return base
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.HTTPException:
                return base
        best = None
        for role_id, amount in (await self.bot.db.get_role_limits()).items():
            if member.get_role(role_id) is not None:
                if best is None or amount > best:
                    best = amount
        return best if best is not None else base

    async def remaining(self, guild, user_id):
        limit = await self.user_limit(guild, user_id)
        if limit is None:
            return None
        usage = await self.bot.db.get_usage(user_id)
        return max(0, limit - usage["used"])

    async def member_in_guild(self, guild, user_id):
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except discord.HTTPException:
            return None

    # ---------------- commands ----------------
    @commands.hybrid_command(
        name="add", description="Add members to a server. Omit amount to add your full limit."
    )
    @commands.guild_only()
    async def add(self, ctx, server_id: str, amount: int = None):
        await ctx.defer()

        if await self.cfg("maintenance", 0):
            return await ctx.send(embed=warn("The bot is in maintenance mode. Try again soon."))

        channel_id = await self.cfg("add_channel", 0)
        if channel_id and ctx.channel.id != channel_id:
            return await ctx.send(embed=err(f"Please use this command in <#{channel_id}>."))

        try:
            target_id = int(server_id.strip())
        except ValueError:
            return await ctx.send(embed=err("`server_id` must be numeric."))

        if amount is not None and amount <= 0:
            return await ctx.send(embed=err("`amount` must be greater than 0."))

        oauth = self.bot.get_cog("OAuth")
        if not await oauth.is_authorized(ctx.author.id):
            return await ctx.send(embed=err("You are not authorized. Run `authorize` first."))

        if await self.bot.db.is_server_blacklisted(target_id):
            return await ctx.send(embed=err(f"Server `{target_id}` is blacklisted."))

        if await self.bot.db.is_user_blacklisted(ctx.author.id):
            return await ctx.send(embed=err("You are blacklisted from adding members."))

        max_queue = await self.cfg("max_queue", Config.DEFAULT_MAX_QUEUE)
        if await self.bot.db.queue_size() >= max_queue:
            return await ctx.send(embed=warn(f"Queue is full ({max_queue}). Try again shortly."))

        now = int(time.time())
        usage = await self.bot.db.get_usage(ctx.author.id)
        if usage["cooldown"] > now:
            return await ctx.send(embed=warn(f"Cooldown active. Try again {ts(usage['cooldown'])}."))

        left = await self.remaining(ctx.guild, ctx.author.id)
        if left is not None and left <= 0:
            return await ctx.send(embed=err("No members left in your current cycle."))

        target_guild = self.bot.get_guild(target_id)
        if target_guild is None:
            return await ctx.send(embed=err(f"I am not in the server `{target_id}`."))

        # ---- same-server repeat guard ----
        repeat_limit = await self.cfg("repeat_limit", Config.DEFAULT_REPEAT_LIMIT)
        same_cd = await self.cfg("same_guild_cooldown", Config.DEFAULT_SAME_GUILD_COOLDOWN)
        pull = await self.bot.db.get_pull(ctx.author.id, target_id)

        if pull:
            ready_at = pull["last_pull"] + same_cd
            if ready_at > now:
                return await ctx.send(
                    embed=warn(
                        f"You already pulled to this server. Try again {ts(ready_at)}.",
                        title="Same Server",
                    )
                )
            if repeat_limit and pull["count"] >= repeat_limit:
                await self.bot.db.add_blacklist_user(ctx.author.id)
                await self.bot.db.add_blacklist_server(target_id)
                return await ctx.send(
                    embed=err(
                        f"You hit the repeat limit (`{repeat_limit}`) on `{target_guild.name}`.\n"
                        "Both you and the server have been **blacklisted**.",
                        title="Repeat Limit",
                    )
                )

        # ---- queue ----
        if left is None:
            planned = amount
            planned_text = "Unlimited" if planned is None else str(planned)
        else:
            planned = min(amount, left) if amount else left
            planned_text = f"{planned} of {left} available"

        await self.bot.db.add_queue(ctx.author.id, ctx.guild.id, target_id, ctx.channel.id, amount)
        await self.bot.db.record_pull(ctx.author.id, target_id)
        position = await self.bot.db.queue_position(ctx.author.id)

        await ctx.send(
            embed=info(
                f"**Server:** `{target_guild.name}`\n"
                f"**Position in queue:** `{position}`\n"
                f"**Will add up to:** `{planned_text}`",
                title="Queued",
            )
        )

    @commands.hybrid_command(name="limit", aliases=["limits", "remaining"])
    @commands.guild_only()
    async def limit(self, ctx):
        limit = await self.user_limit(ctx.guild, ctx.author.id)
        usage = await self.bot.db.get_usage(ctx.author.id)
        if limit is None:
            embed = info("You have **unlimited** member additions.", title="Limit Preview")
        else:
            left = max(0, limit - usage["used"])
            embed = info(
                f"**Total limit:** `{limit}`\n**Used:** `{usage['used']}`\n"
                f"**Remaining:** `{left}`", title="Limit Preview",
            )
        if usage["cooldown"] > int(time.time()):
            embed.add_field(name="Cooldown", value=ts(usage["cooldown"]), inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="pulls", aliases=["history"], description="Your recent pulls")
    @commands.guild_only()
    async def pulls(self, ctx):
        rows = await self.bot.db.list_pulls(50)
        mine = [r for r in rows if r["user_id"] == ctx.author.id]
        if not mine:
            return await ctx.send(embed=info("You have no pull history."))
        lines = [
            f"`{r['guild_id']}` - {r['count']}x - {ts(r['last_pull'])}" for r in mine[:15]
        ]
        await ctx.send(embed=info("\n".join(lines), title="Your Pulls"))

    @commands.hybrid_command(name="queue")
    async def queue(self, ctx):
        rows = await self.bot.db.queue_list()
        if not rows:
            return await ctx.send(embed=info("Queue is empty."))
        lines = [
            f"`#{i}` <@{r['user_id']}> -> `{r['guild_id']}`"
            for i, r in enumerate(rows[:25], start=1)
        ]
        await ctx.send(embed=info("\n".join(lines), title=f"Queue ({len(rows)})"))

    @commands.hybrid_command(name="profile")
    @commands.guild_only()
    async def profile(self, ctx):
        limit = await self.user_limit(ctx.guild, ctx.author.id)
        usage = await self.bot.db.get_usage(ctx.author.id)
        authorized = await self.bot.get_cog("OAuth").is_authorized(ctx.author.id)
        embed = info(title=f"{ctx.author.display_name}")
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        embed.add_field(name="Authorized", value="Yes" if authorized else "No")
        embed.add_field(name="Limit", value="Unlimited" if limit is None else str(limit))
        embed.add_field(name="Used", value=str(usage["used"]))
        if limit is not None:
            embed.add_field(name="Remaining", value=str(max(0, limit - usage["used"])))
        await ctx.send(embed=embed)

    # ---------------- workers ----------------
    async def worker_loop(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                if await self.cfg("maintenance", 0):
                    await asyncio.sleep(3)
                    continue
                entry = await self.bot.db.pop_queue()
                if entry:
                    try:
                        await self.process(entry)
                    except Exception:
                        log.exception("process() failed, requeueing %s", entry.get("key"))
                        await self.bot.db.add_queue(
                            entry["user_id"], entry["source_guild_id"],
                            entry["guild_id"], entry["channel_id"], entry["amount"],
                        )
                else:
                    await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("Worker error")
                await asyncio.sleep(3)

    async def restock_loop(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                now = int(time.time())
                for user_id in await self.bot.db.get_expired_cooldowns(now):
                    await self.bot.db.set_usage(user_id, used=0, cooldown=0)
                    await self.notify_restock(user_id)
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("Restock error")
            await asyncio.sleep(10)

    async def notify_restock(self, user_id):
        channel_id = await self.cfg("add_channel", 0)
        if not channel_id:
            return
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return
        try:
            await channel.send(
                content=f"<@{user_id}>",
                embed=ok("Your members have been **restocked**."),
            )
        except discord.HTTPException:
            pass

    async def process(self, entry):
        user_id = entry["user_id"]
        guild_id = entry["guild_id"]
        channel_id = entry["channel_id"]
        source_guild_id = entry["source_guild_id"]
        requested = entry["amount"]

        channel = self.bot.get_channel(channel_id)
        target = self.bot.get_guild(guild_id)
        source = self.bot.get_guild(source_guild_id)

        async def notify(embed):
            if channel:
                try:
                    await channel.send(content=f"<@{user_id}>", embed=embed)
                except discord.HTTPException:
                    pass

        if target is None:
            return await notify(err(f"I am not in `{guild_id}`."))
        if target.me is None or not target.me.guild_permissions.create_instant_invite:
            return await notify(err(f"I need **Create Invite** in `{target.name}`."))

        oauth = self.bot.get_cog("OAuth")
        if not await oauth.get_valid_token(user_id):
            return await notify(err("You are no longer authorized."))

        limit = await self.user_limit(source, user_id)
        usage = await self.bot.db.get_usage(user_id)

        if limit is None:
            remaining = None
        else:
            remaining = max(0, limit - usage["used"])
            if remaining <= 0:
                return await notify(err("No members left in your cycle."))

        goal = (requested if remaining is None else min(requested, remaining)) if requested else remaining

        pool = await self.bot.db.get_authorized_users()
        added = skipped = failed = 0

        for candidate_id in pool:
            if goal is not None and added >= goal:
                break
            token = await oauth.get_valid_token(candidate_id)
            if not token:
                continue
            if await self.member_in_guild(target, candidate_id) is not None:
                skipped += 1
                continue
            try:
                await add_member_to_guild(self.bot, target, candidate_id, token)
                added += 1
            except discord.HTTPException as exc:
                failed += 1
                log.warning("Add %s -> %s failed: %s", candidate_id, target.id, exc)
            await asyncio.sleep(0.5)

        now = int(time.time())
        cooldown = await self.cfg("cooldown", Config.DEFAULT_COOLDOWN)
        new_used = usage["used"] + added
        await self.bot.db.set_usage(user_id, used=new_used, cooldown=now + cooldown)

        left_text = "Unlimited" if limit is None else str(max(0, limit - new_used))
        await notify(
            ok(
                f"**Server:** `{target.name}`\n**Added:** `{added}`\n"
                f"**Skipped:** `{skipped}`\n**Failed:** `{failed}`\n"
                f"**Remaining:** `{left_text}`\n**Next:** {ts(now + cooldown)}",
                title="Members Added",
            )
        )


async def setup(bot):
    await bot.add_cog(Add(bot))
