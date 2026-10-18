import asyncio
import logging
import time

import discord
from discord.ext import commands

from config import Config
from utils import add_member_to_guild, err, info, ok, ts, warn

log = logging.getLogger("venice.add")


class Add(commands.Cog):
    """Member adding system with FIFO queue."""

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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def user_limit(self, guild, user_id):
        """Returns None for unlimited (owner)."""
        if await self.bot.is_owner(discord.Object(id=user_id)):
            return None

        base = await self.bot.db.get_setting_int("normal_limit", Config.DEFAULT_NORMAL_LIMIT)
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

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    @commands.hybrid_command(
        name="add",
        description="Add members to a server. Omit amount to add your full limit.",
    )
    @commands.guild_only()
    async def add(self, ctx, server_id: str, amount: int = None):
        await ctx.defer()

        channel_id = await self.bot.db.get_setting_int("add_channel", 0)
        if channel_id and ctx.channel.id != channel_id:
            return await ctx.send(embed=err(f"Please use this command in <#{channel_id}>."))

        try:
            target_id = int(server_id.strip())
        except ValueError:
            return await ctx.send(embed=err("`server_id` must be a numeric server ID."))

        if amount is not None and amount <= 0:
            return await ctx.send(embed=err("`amount` must be greater than 0."))

        oauth = self.bot.get_cog("OAuth")
        if not await oauth.is_authorized(ctx.author.id):
            return await ctx.send(
                embed=err("You are not authorized. Run `authorize` and complete the OAuth flow.")
            )

        if await self.bot.db.is_server_blacklisted(target_id):
            return await ctx.send(embed=err(f"Server `{target_id}` is blacklisted."))

        if await self.bot.db.is_user_blacklisted(ctx.author.id):
            return await ctx.send(embed=err("You are blacklisted from adding members."))

        if await self.bot.db.queue_size() >= Config.MAX_QUEUE:
            return await ctx.send(
                embed=warn(f"The queue is full ({Config.MAX_QUEUE} entries). Try again shortly.")
            )

        usage = await self.bot.db.get_usage(ctx.author.id)
        now = int(time.time())
        if usage["cooldown"] > now:
            return await ctx.send(
                embed=warn(f"You are on cooldown. Try again {ts(usage['cooldown'])}.")
            )

        left = await self.remaining(ctx.guild, ctx.author.id)
        if left is not None and left <= 0:
            return await ctx.send(embed=err("You have no members left in your current cycle."))

        target_guild = self.bot.get_guild(target_id)
        if target_guild is None:
            return await ctx.send(embed=err(f"I am not in the server `{target_id}`."))

        # Resolve how many will actually be attempted
        if left is None:
            # owner / unlimited
            planned = amount if amount else None
            planned_text = "Unlimited" if planned is None else str(planned)
        else:
            planned = min(amount, left) if amount else left
            planned_text = f"{planned} of {left} available"

        await self.bot.db.add_queue(ctx.author.id, ctx.guild.id, target_id, ctx.channel.id, amount)
        position = await self.bot.db.queue_position(ctx.author.id)

        await ctx.send(
            embed=info(
                f"**Server:** `{target_guild.name}`\n"
                f"**Position in queue:** `{position}`\n"
                f"**Will add up to:** `{planned_text}`",
                title="Added to queue",
            )
        )

    @commands.hybrid_command(
        name="limit", aliases=["limits", "remaining"], description="Preview your remaining limit"
    )
    @commands.guild_only()
    async def limit(self, ctx):
        limit = await self.user_limit(ctx.guild, ctx.author.id)
        usage = await self.bot.db.get_usage(ctx.author.id)

        if limit is None:
            embed = info("You have **unlimited** member additions.", title="Limit Preview")
        else:
            left = max(0, limit - usage["used"])
            embed = info(
                f"**Total limit:** `{limit}`\n"
                f"**Used:** `{usage['used']}`\n"
                f"**Restocked / remaining:** `{left}`",
                title="Limit Preview",
            )

        if usage["cooldown"] > int(time.time()):
            embed.add_field(name="Cooldown", value=ts(usage["cooldown"]), inline=False)

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="queue", description="View the current queue")
    async def queue(self, ctx):
        rows = await self.bot.db.queue_list()
        if not rows:
            return await ctx.send(embed=info("The queue is empty."))

        lines = [
            f"`#{i}` <@{row['user_id']}> -> `{row['guild_id']}`"
            for i, row in enumerate(rows[:25], start=1)
        ]
        await ctx.send(embed=info("\n".join(lines), title=f"Queue ({len(rows)}/{Config.MAX_QUEUE})"))

    @commands.hybrid_command(name="profile", description="View your profile")
    @commands.guild_only()
    async def profile(self, ctx):
        limit = await self.user_limit(ctx.guild, ctx.author.id)
        usage = await self.bot.db.get_usage(ctx.author.id)
        oauth = self.bot.get_cog("OAuth")
        authorized = await oauth.is_authorized(ctx.author.id)

        embed = info(title=f"{ctx.author.display_name}'s Profile")
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        embed.add_field(name="Authorized", value="Yes" if authorized else "No")
        embed.add_field(name="Limit", value="Unlimited" if limit is None else str(limit))
        embed.add_field(name="Used", value=str(usage["used"]))
        if limit is not None:
            embed.add_field(name="Remaining", value=str(max(0, limit - usage["used"])))
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------
    async def worker_loop(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                entry = await self.bot.db.pop_queue()
                if entry:
                    try:
                        await self.process(entry)
                    except Exception:
                        log.exception("process() failed, requeueing entry %s", entry["id"])
                        await self.bot.db.add_queue(
                            entry["user_id"],
                            entry["source_guild_id"],
                            entry["guild_id"],
                            entry["channel_id"],
                            entry["amount"],
                        )
                else:
                    await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("Queue worker error")
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
                log.exception("Restock loop error")
            await asyncio.sleep(10)

    async def notify_restock(self, user_id):
        channel_id = await self.bot.db.get_setting_int("add_channel", 0)
        if not channel_id:
            return
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return
        try:
            await channel.send(
                content=f"<@{user_id}>",
                embed=ok("Your members have been **restocked**. You can add again."),
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
            await notify(err(f"I am not in the server `{guild_id}`."))
            return

        if target.me is None or not target.me.guild_permissions.create_instant_invite:
            await notify(err(f"I need **Create Invite** permission in `{target.name}`."))
            return

        oauth = self.bot.get_cog("OAuth")
        if not await oauth.get_valid_token(user_id):
            await notify(err("You are no longer authorized. Please re-authorize."))
            return

        limit = await self.user_limit(source, user_id)
        usage = await self.bot.db.get_usage(user_id)

        if limit is None:
            remaining = None  # uncapped
        else:
            remaining = max(0, limit - usage["used"])
            if remaining <= 0:
                await notify(err("You have no members left in your current cycle."))
                return

        # goal: None means "until the pool is exhausted"
        if requested:
            goal = requested if remaining is None else min(requested, remaining)
        else:
            goal = remaining  # None for owner -> uncapped

        pool = await self.bot.db.get_authorized_users()
        added = 0
        skipped = 0
        failed = 0

        for candidate_id in pool:
            if goal is not None and added >= goal:
                break

            candidate_token = await oauth.get_valid_token(candidate_id)
            if not candidate_token:
                continue

            if await self.member_in_guild(target, candidate_id) is not None:
                skipped += 1
                continue

            try:
                await add_member_to_guild(self.bot, target, candidate_id, candidate_token)
                added += 1
            except discord.HTTPException as exc:
                failed += 1
                log.warning("Failed to add %s to %s: %s", candidate_id, target.id, exc)

            await asyncio.sleep(0.5)

        now = int(time.time())
        new_used = usage["used"] + added
        await self.bot.db.set_usage(user_id, used=new_used, cooldown=now + Config.COOLDOWN_SECONDS)

        left_text = "Unlimited" if limit is None else str(max(0, limit - new_used))

        await notify(
            ok(
                f"**Server:** `{target.name}`\n"
                f"**Added:** `{added}`\n"
                f"**Skipped (already present):** `{skipped}`\n"
                f"**Failed:** `{failed}`\n"
                f"**Restocked / remaining:** `{left_text}`\n"
                f"**Next available:** {ts(now + Config.COOLDOWN_SECONDS)}",
                title="Members Added",
            )
        )


async def setup(bot):
    await bot.add_cog(Add(bot))
