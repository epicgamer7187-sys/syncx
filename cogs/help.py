import discord
from discord.ext import commands

from config import Config
from utils import brand

USER_COMMANDS = [
    ("add <server_id> [amount]", "Add members. Omit amount to add your full limit."),
    ("limit", "Preview your remaining member limit."),
    ("queue", "View the current queue."),
    ("profile", "View your authorization and usage profile."),
    ("authorize", "Get your personal authorization link."),
    ("invite", "Get the bot invite link."),
    ("ping", "Check the bot latency."),
]

OWNER_COMMANDS = [
    ("verify_panel [#channel]", "Send the permanent verification panel."),
    ("resync", "Re-check whether verified users are still authorized."),
    ("verified_count", "Count verified users in this server."),
    ("settings", "View the current configuration."),
    ("set limit <amount>", "Set the default limit for normal users."),
    ("set rolelimit <role> <amount>", "Set a member limit for a role."),
    ("set removerolelimit <role>", "Remove a role limit."),
    ("set channel <#channel>", "Restrict the add command to one channel."),
    ("set verifyrole <@role>", "Set the role given on verification."),
    ("set maxqueue <amount>", "Set the queue capacity."),
    ("blacklist server <id>", "Blacklist a server."),
    ("blacklist unserver <id>", "Unblacklist a server."),
    ("blacklist user <@user>", "Blacklist a user."),
    ("blacklist unuser <@user>", "Unblacklist a user."),
    ("blacklist list", "List all blacklisted servers and users."),
    ("authcount", "Show the total number of authorized users."),
    ("recheck", "Find accounts missing the guilds.join scope."),
    ("synccmds", "Re-sync slash commands."),
    ("clearqueue", "Clear the queue."),
    ("resetuser <@user>", "Reset a user's usage and cooldown."),
]

LIMIT = 1000


def _chunks(pairs):
    out, current = [], ""
    for name, desc in pairs:
        line = f"`{name}` - {desc}\n"
        if len(current) + len(line) > LIMIT:
            out.append(current.rstrip())
            current = ""
        current += line
    if current:
        out.append(current.rstrip())
    return out


class Help(commands.Cog):
    """Dynamic help menu."""

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="help", description="Show the help menu")
    async def help(self, ctx):
        is_owner = await self.bot.is_owner(ctx.author)

        embed = brand(
            f"Prefix: `{Config.PREFIX}` - Slash commands work too.\n"
            "`amount` is optional - omit it to add your full limit.",
            title="Venice Member Bot - Help",
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        for i, block in enumerate(_chunks(USER_COMMANDS)):
            embed.add_field(
                name="User Commands" if i == 0 else "User Commands (cont.)",
                value=block,
                inline=False,
            )

        if is_owner:
            for i, block in enumerate(_chunks(OWNER_COMMANDS)):
                embed.add_field(
                    name="Owner Commands" if i == 0 else "Owner Commands (cont.)",
                    value=block,
                    inline=False,
                )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Help(bot))
