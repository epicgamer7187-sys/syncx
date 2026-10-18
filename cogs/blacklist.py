import discord
from discord.ext import commands

from utils import err, info, ok


class Blacklist(commands.Cog):
    """Server and user blacklisting."""

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_group(name="blacklist", aliases=["bl"], description="Manage blacklists", invoke_without_command=True)
    @commands.guild_only()
    @commands.is_owner()
    async def blacklist(self, ctx):
        await ctx.send(
            embed=info(
                "`blacklist server <id>` / `blacklist unserver <id>`\n"
                "`blacklist user <@user>` / `blacklist unuser <@user>`\n"
                "`blacklist list`",
                title="Blacklist",
            )
        )

    @blacklist.command(name="server", description="Blacklist a server by ID")
    @commands.is_owner()
    async def bl_server(self, ctx, server_id: str):
        try:
            sid = int(server_id.strip())
        except ValueError:
            return await ctx.send(embed=err("Invalid server ID."))
        await self.bot.db.add_blacklist_server(sid)
        await ctx.send(embed=ok(f"Server `{sid}` blacklisted."))

    @blacklist.command(name="unserver", description="Remove a server from the blacklist")
    @commands.is_owner()
    async def unbl_server(self, ctx, server_id: str):
        try:
            sid = int(server_id.strip())
        except ValueError:
            return await ctx.send(embed=err("Invalid server ID."))
        await self.bot.db.remove_blacklist_server(sid)
        await ctx.send(embed=ok(f"Server `{sid}` removed from the blacklist."))

    @blacklist.command(name="user", description="Blacklist a user")
    @commands.is_owner()
    async def bl_user(self, ctx, user: discord.User):
        await self.bot.db.add_blacklist_user(user.id)
        await ctx.send(embed=ok(f"{user.mention} blacklisted."))

    @blacklist.command(name="unuser", description="Remove a user from the blacklist")
    @commands.is_owner()
    async def unbl_user(self, ctx, user: discord.User):
        await self.bot.db.remove_blacklist_user(user.id)
        await ctx.send(embed=ok(f"{user.mention} removed from the blacklist."))

    @blacklist.command(name="list", description="List all blacklists")
    @commands.is_owner()
    async def bl_list(self, ctx):
        servers = await self.bot.db.list_blacklist_servers()
        users = await self.bot.db.list_blacklist_users()

        embed = info(title="Blacklists")
        embed.add_field(
            name=f"Servers ({len(servers)})",
            value="\n".join(f"`{s}`" for s in servers[:20]) or "None",
            inline=False,
        )
        embed.add_field(
            name=f"Users ({len(users)})",
            value="\n".join(f"<@{u}>" for u in users[:20]) or "None",
            inline=False,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Blacklist(bot))
