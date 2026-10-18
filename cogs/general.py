import time

import discord
from discord.ext import commands

from utils import info, ok


class General(commands.Cog):
    """Miscellaneous utilities."""

    def __init__(self, bot):
        self.bot = bot
        self.started = time.time()

    @commands.hybrid_command(name="ping", description="Check the bot latency")
    async def ping(self, ctx):
        latency = round(self.bot.latency * 1000)
        await ctx.send(embed=ok(f"**Gateway latency:** `{latency}ms`", title="Pong"))

    @commands.hybrid_command(name="authcount", aliases=["authorized", "auths"], description="Count total authorized users")
    @commands.guild_only()
    @commands.is_owner()
    async def authcount(self, ctx):
        count = await self.bot.db.count_authorized()
        await ctx.send(embed=info(f"**Total authorized users:** `{count}`", title="Authorized Users"))

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
