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
                "`set maxqueue <amount>` - queue capacity\n"
                "`set cooldown <seconds>` - per-user cooldown\n"
                "`set sameguildcooldown <seconds>` - same-server repeat cooldown\n"
                "`set repeatlimit <count>` - repeats before auto-blacklist\n"
                "`set maintenance <on|off>` - pause or resume the queue",
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

    @set_.command(name="cooldown", description="Per-user cooldown in seconds")
    @commands.is_owner()
    async def set_cooldown(self, ctx, seconds: int):
        if seconds < 0:
            return await ctx.send(embed=err("Must be 0 or higher."))
        await self.bot.db.set_setting("cooldown", seconds)
        await ctx.send(embed=ok(f"Cooldown set to `{seconds}s`."))

    @set_.command(name="sameguildcooldown", description="Same-server repeat cooldown in seconds")
    @commands.is_owner()
    async def set_same_cd(self, ctx, seconds: int):
        if seconds < 0:
            return await ctx.send(embed=err("Must be 0 or higher."))
        await self.bot.db.set_setting("same_guild_cooldown", seconds)
        await ctx.send(embed=ok(f"Same-server cooldown set to `{seconds}s`."))

    @set_.command(name="repeatlimit", description="Repeats before auto-blacklist (0 disables)")
    @commands.is_owner()
    async def set_repeat(self, ctx, count: int):
        if count < 0:
            return await ctx.send(embed=err("Must be 0 or higher."))
        await self.bot.db.set_setting("repeat_limit", count)
        await ctx.send(embed=ok(f"Repeat limit set to `{count}`."))

    @set_.command(name="maintenance", description="Pause or resume the queue")
    @commands.is_owner()
    async def set_maintenance(self, ctx, state: str):
        on = state.lower() in ("on", "true", "1", "yes")
        await self.bot.db.set_setting("maintenance", 1 if on else 0)
        await ctx.send(embed=ok(f"Maintenance **{'enabled' if on else 'disabled'}**."))

    @commands.hybrid_command(
        name="settings",
        aliases=["setting", "config"],
        description="View the current configuration",
    )
    @commands.guild_only()
    @commands.is_owner()
    async def settings(self, ctx):
        normal = await self.bot.db.get_setting_int("normal_limit", Config.DEFAULT_NORMAL_LIMIT)
        channel_id = await self.bot.db.get_setting_int("add_channel", 0)
        role_id = await self.bot.db.get_setting_int("verify_role", 0)
        max_queue = await self.bot.db.get_setting_int("max_queue", Config.DEFAULT_MAX_QUEUE)
        cooldown = await self.bot.db.get_setting_int("cooldown", Config.DEFAULT_COOLDOWN)
        same_cd = await self.bot.db.get_setting_int(
            "same_guild_cooldown", Config.DEFAULT_SAME_GUILD_COOLDOWN
        )
        repeat = await self.bot.db.get_setting_int("repeat_limit", Config.DEFAULT_REPEAT_LIMIT)
        maintenance = await self.bot.db.get_setting_int("maintenance", 0)
        role_limits = await self.bot.db.get_role_limits()

        embed = info(title="Current Configuration")
        embed.add_field(name="Normal limit", value=str(normal))
        embed.add_field(name="Add channel", value=f"<#{channel_id}>" if channel_id else "Any")
        embed.add_field(name="Verify role", value=f"<@&{role_id}>" if role_id else "Not set")
        embed.add_field(name="Queue cap", value=str(max_queue))
        embed.add_field(name="Cooldown", value=f"{cooldown}s")
        embed.add_field(name="Same-server cooldown", value=f"{same_cd}s")
        embed.add_field(name="Repeat limit", value=str(repeat) if repeat else "Disabled")
        embed.add_field(name="Maintenance", value="On" if maintenance else "Off")
        embed.add_field(
            name="Role limits",
            value="\n".join(f"<@&{r}> -> `{a}`" for r, a in role_limits.items()) or "None",
            inline=False,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Settings(bot))
