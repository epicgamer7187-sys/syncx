import time

import discord
from discord.ext import commands

from utils import info, ok
from web import bot_invite_url


class General(commands.Cog):
    """Miscellaneous utilities."""

    def __init__(self, bot):
        self.bot = bot
        self.started = time.time()

    @commands.hybrid_command(name="ping", description="Check the bot latency")
    async def ping(self, ctx):
        await ctx.send(embed=ok(f"**Gateway latency:** `{round(self.bot.latency * 1000)}ms`", title="Pong"))

    @commands.hybrid_command(name="invite", description="Get the correctly-scoped bot invite link")
    async def invite(self, ctx):
        embed = info(
            "Use **this** link to add the bot to a server.\n"
            "Use the `verify_panel` button for user authorization - they are different flows.",
            title="Bot Invite",
        )
        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(label="Invite Bot", url=bot_invite_url(), style=discord.ButtonStyle.link)
        )
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="authcount", aliases=["authorized", "auths"], description="Count authorized users")
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
