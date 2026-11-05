import asyncio
import logging

import discord
from discord.ext import commands

from config import Config
from store import Store
from utils import err
from web import WebServer

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("venice")

COGS = [
    "cogs.oauth",
    "cogs.add",
    "cogs.verify",
    "cogs.settings",
    "cogs.blacklist",
    "cogs.general",
    "cogs.help",
]


class VeniceBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.guilds = True

        super().__init__(
            command_prefix=commands.when_mentioned_or(Config.PREFIX),
            intents=intents,
            help_command=None,
            owner_id=Config.BOT_OWNER_ID or None,
            case_insensitive=True,
            strip_after_prefix=True,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
        )
        self.db = Store(Config.DB_PATH, Config.MONGO_URI or None, Config.MONGO_DB)
        self.web = WebServer(self)

    async def setup_hook(self):
        await self.db.connect()

        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info("Loaded %s", cog)
            except Exception:
                log.exception("Failed to load %s", cog)

        await self.web.start()
        self.tree.on_error = self.on_app_command_error

        try:
            synced = await self.tree.sync()
            log.info("Synced %d slash commands", len(synced))
        except Exception:
            log.exception("Slash command sync failed")

    async def on_ready(self):
        log.info("Store mode: %s", "MongoDB" if self.db.online else "SQLite fallback")
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching, name=f"{Config.PREFIX}help"
            ),
            status=discord.Status.online,
        )

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.CheckFailure):
            return await ctx.send(embed=err("You do not have permission to use this command."))
        if isinstance(error, commands.MissingRequiredArgument):
            return await ctx.send(
                embed=err(f"Missing argument: `{error.param.name}`.\nTry `{Config.PREFIX}help`.")
            )
        if isinstance(error, commands.BadArgument):
            return await ctx.send(embed=err(f"Invalid argument: {error}"))
        log.exception("Command error in %s", getattr(ctx.command, "name", "?"), exc_info=error)
        try:
            await ctx.send(embed=err(f"`{type(error).__name__}`: {error}"))
        except discord.HTTPException:
            pass

    async def on_app_command_error(self, interaction, error):
        if isinstance(error, discord.app_commands.CommandInvokeError):
            error = error.original
        try:
            msg = err(f"`{type(error).__name__}`: {error}")
            if interaction.response.is_done():
                await interaction.followup.send(embed=msg, ephemeral=True)
            else:
                await interaction.response.send_message(embed=msg, ephemeral=True)
        except discord.HTTPException:
            pass

    async def close(self):
        await self.db.close()
        await super().close()


async def main():
    if not Config.TOKEN or not Config.CLIENT_ID or not Config.CLIENT_SECRET:
        raise SystemExit("Missing DISCORD_TOKEN / CLIENT_ID / CLIENT_SECRET.")

    bot = VeniceBot()
    async with bot:
        await bot.start(Config.TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
