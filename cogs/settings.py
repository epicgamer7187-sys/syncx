import discord
from discord.ext import commands

from config import Config
from utils import err, info, ok


class Settings(commands.Cog):
    """Owner-only configuration."""

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_group(name="set", description="Configure the bot", invoke_without_command=True)
    @commands.guild_only()
    @commands.is_owner()
    async def set_(self, ctx):
        await ctx.send(
            embed=info(
                "`set limit <amount>` - default limit for normal users\n"
                "`set rolelimit <role> <amount>` - limit for a role\n"
                "`set removerolelimit <role>` - remove a role limit\n"
                "`set channel <#channel>` - restrict the add command\n"
                "`set verifyrole <@role>` - role given on verification\n"
                "`set maxqueue <amount>` - set the queue cap",
                title="Configuration",
            )
        )

    @set_.command(name="limit", description="Set the default limit for normal users")
    @commands.is_owner()
    async def set_limit(self, ctx, amount: int):
        if amount < 0:
            return await ctx.send(embed=err("Amount must be 0 or higher."))
        await self.bot.db.set_setting("normal_limit", amount)
        await ctx.send(embed=ok(f"Normal user limit set to `{amount}`."))

    @set_.command(name="rolelimit", description="Set a limit for a role")
    @commands.is_owner()
    async def set_rolelimit(self, ctx, role: discord.Role, amount: int):
        if amount < 0:
            return await ctx.send(embed=err("Amount must be 0 or higher."))
        await self.bot.db.set_role_limit(role.id, amount)
        await ctx.send(embed=ok(f"Limit for {role.mention} set to `{amount}`."))

    @set_.command(name="removerolelimit", description="Remove a role limit")
    @commands.is_owner()
    async def remove_rolelimit(self, ctx, role: discord.Role):
        await self.bot.db.remove_role_limit(role.id)
        await ctx.send(embed=ok(f"Removed the limit for {role.mention}."))

    @set_.command(name="channel", description="Restrict the add command to a channel")
    @commands.is_owner()
    async def set_channel(self, ctx, channel: discord.TextChannel):
        await self.bot.db.set_setting("add_channel", channel.id)
        await ctx.send(embed=ok(f"Add command restricted to {channel.mention}."))

    @set_.command(name="verifyrole", description="Set the role given on verification")
    @commands.is_owner()
    async def set_verifyrole(self, ctx, role: discord.Role):
        await self.bot.db.set_setting("verify_role", role.id)
        await ctx.send(embed=ok(f"Verification role set to {role.mention}."))

    @set_.command(name="maxqueue", description="Set the maximum queue size")
    @commands.is_owner()
    async def set_maxqueue(self, ctx, amount: int):
        if amount < 1:
            return await ctx.send(embed=err("Amount must be at least 1."))
        await self.bot.db.set_setting("max_queue", amount)
        await ctx.send(embed=ok(f"Queue cap set to `{amount}`."))

    @commands.hybrid_command(name="settings", description="View the current configuration")
    @commands.guild_only()
    @commands.is_owner()
    async def settings(self, ctx):
        normal = await self.bot.db.get_setting_int("normal_limit", Config.DEFAULT_NORMAL_LIMIT)
        channel_id = await self.bot.db.get_setting_int("add_channel", 0)
        role_id = await self.bot.db.get_setting_int("verify_role", 0)
        role_limits = await self.bot.db.get_role_limits()

        embed = info(title="Current Configuration")
        embed.add_field(name="Normal limit", value=str(normal))
        embed.add_field(name="Add channel", value=f"<#{channel_id}>" if channel_id else "Any")
        embed.add_field(name="Verify role", value=f"<@&{role_id}>" if role_id else "Not set")
        embed.add_field(
            name="Role limits",
            value="\n".join(f"<@&{r}> -> `{a}`" for r, a in role_limits.items()) or "None",
            inline=False,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Settings(bot))
