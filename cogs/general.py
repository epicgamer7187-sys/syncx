import time

import discord
from discord.ext import commands

from utils import err, info, ok, ts
from web import bot_invite_url


class General(commands.Cog):
    """Miscellaneous utilities and database controls."""

    def __init__(self, bot):
        self.bot = bot
        self.started = time.time()

    @commands.hybrid_command(name="ping", description="Check the bot latency")
    async def ping(self, ctx):
        await ctx.send(
            embed=ok(f"**Gateway latency:** `{round(self.bot.latency * 1000)}ms`", title="Pong")
        )

    @commands.hybrid_command(name="invite", description="Get the correctly-scoped bot invite link")
    async def invite(self, ctx):
        embed = info(
            "Use **this** link to add the bot to a server.\n"
            "Use the `verify_panel` button for user authorization - they are different flows.",
            title="Bot Invite",
        )
        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label="Invite Bot", url=bot_invite_url(), style=discord.ButtonStyle.link
            )
        )
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="stats", description="Bot statistics")
    async def stats(self, ctx):
        authorized = await self.bot.db.count_authorized()
        queued = await self.bot.db.queue_size()
        embed = info(
            f"**Authorized:** `{authorized}`\n"
            f"**Queue:** `{queued}`\n"
            f"**Guilds:** `{len(self.bot.guilds)}`\n"
            f"**Latency:** `{round(self.bot.latency * 1000)}ms`\n"
            f"**Backend:** `{'MongoDB' if self.bot.db.online else 'SQLite fallback'}`",
            title="Statistics",
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="authcount", aliases=["authorized", "auths"], description="Count authorized users"
    )
    @commands.guild_only()
    @commands.is_owner()
    async def authcount(self, ctx):
        count = await self.bot.db.count_authorized()
        await ctx.send(embed=info(f"**Total authorized users:** `{count}`", title="Authorized Users"))

    @commands.hybrid_command(name="recheck", description="Find accounts with a bad OAuth scope")
    @commands.is_owner()
    async def recheck(self, ctx):
        rows = await self.bot.db.get_bad_scope_users()
        if not rows:
            return await ctx.send(embed=ok("Every stored account has a valid `guilds.join` scope."))

        lines = [f"<@{r['user_id']}> - scope `{r['scope'] or 'empty'}`" for r in rows[:20]]
        await ctx.send(
            embed=info(
                "\n".join(lines) + f"\n\n**{len(rows)}** account(s) need to re-authorize.",
                title="Bad Scope Accounts",
            )
        )

    @commands.hybrid_command(name="dbstatus", description="Show the active database backend")
    @commands.is_owner()
    async def dbstatus(self, ctx):
        pending = await self.bot.db.sqlite.pending_count()
        embed = info(
            f"**Mode:** `{'MongoDB' if self.bot.db.online else 'SQLite fallback'}`\n"
            f"**Pending ops:** `{pending}`\n"
            f"**Mongo configured:** `{'yes' if self.bot.db.mongo else 'no'}`",
            title="Database Status",
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="forcesync", description="Replay pending ops to MongoDB now")
    @commands.is_owner()
    async def forcesync(self, ctx):
        if self.bot.db.mongo is None:
            return await ctx.send(embed=err("MONGO_URI is not configured."))
        if not await self.bot.db.mongo.ping():
            return await ctx.send(embed=err("MongoDB is unreachable right now."))
        count = await self.bot.db.sync_pending()
        await ctx.send(embed=ok(f"Replayed `{count}` pending ops."))

    @commands.hybrid_command(name="attempts", description="Recent pull attempts")
    @commands.is_owner()
    async def attempts(self, ctx):
        rows = await self.bot.db.list_pulls(20)
        if not rows:
            return await ctx.send(embed=info("No attempts recorded."))
        lines = [
            f"<@{r['user_id']}> -> `{r['guild_id']}` - {r['count']}x - {ts(r['last_pull'])}"
            for r in rows
        ]
        await ctx.send(embed=info("\n".join(lines), title="Attempts"))

    @commands.hybrid_command(
        name="resetattempts", description="Clear a user/server attempt record"
    )
    @commands.is_owner()
    async def resetattempts(self, ctx, user: discord.User, server_id: str):
        try:
            sid = int(server_id.strip())
        except ValueError:
            return await ctx.send(embed=err("Invalid server ID."))
        await self.bot.db.reset_pull(user.id, sid)
        await ctx.send(embed=ok(f"Cleared attempts for {user.mention} on `{sid}`."))

    @commands.hybrid_command(name="synccmds", description="Re-sync slash commands")
    @commands.is_owner()
    async def synccmds(self, ctx):
        synced = await self.bot.tree.sync()
        await ctx.send(embed=ok(f"Synced `{len(synced)}` slash commands."))

    @commands.hybrid_command(name="clearqueue", description="Clear the queue")
    @commands.is_owner()
    async def clearqueue(self, ctx):
        await self.bot.db.clear_queue()
        await ctx.send(embed=ok("Queue cleared."))

    @commands.hybrid_command(name="resetuser", description="Reset a user's usage")
    @commands.is_owner()
    async def resetuser(self, ctx, user: discord.User):
        await self.bot.db.set_usage(user.id, used=0, cooldown=0)
        await ctx.send(embed=ok(f"Reset usage for {user.mention}."))


async def setup(bot):
    await bot.add_cog(General(bot))
