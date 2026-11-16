import asyncio
import logging

import discord
from discord.ext import commands

import vr_presence
from config import Config
from database import Database
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
        self.db = Database(Config.DB_PATH)
        self.web = WebServer(self)
        self._presence_task = None

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

        self._presence_task = asyncio.create_task(self._rotate_presence())

    async def _rotate_presence(self):
        await self.wait_until_ready()
        if not Config.STATUSES:
            return
        index = 0
        while True:
            template = Config.STATUSES[index % len(Config.STATUSES)]
            name = template.replace("{prefix}", Config.PREFIX).replace(
                "{guilds}", str(len(self.guilds))
            )
            try:
                await self.change_presence(
                    activity=discord.Activity(
                        type=discord.ActivityType.watching, name=name[:128]
                    ),
                    status=discord.Status.online,
                )
            except Exception:
                log.exception("Presence update failed")
            index += 1
            await asyncio.sleep(max(15, Config.STATUS_INTERVAL))

    async def on_ready(self):
        log.info("Logged in as %s (%s)", self.user, self.user.id)

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
        if self._presence_task:
            self._presence_task.cancel()
        await self.db.close()
        await super().close()


async def main():
    if not Config.TOKEN or not Config.CLIENT_ID or not Config.CLIENT_SECRET:
        raise SystemExit("Missing DISCORD_TOKEN / CLIENT_ID / CLIENT_SECRET.")

    vr_presence.install()

    bot = VeniceBot()
    async with bot:
        await bot.start(Config.TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
