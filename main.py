import asyncio
import logging

import discord
from discord.ext import commands

from config import Config
from database import Database
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

    async def setup_hook(self):
        await self.db.connect()

        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info("Loaded %s", cog)
            except Exception:
                log.exception("Failed to load %s", cog)

        await self.web.start()

        try:
            synced = await self.tree.sync()
            log.info("Synced %d slash commands", len(synced))
        except Exception:
            log.exception("Slash command sync failed")

    async def on_ready(self):
        log.info(
            "discord.py %s | Guild.add_member=%s | http.add_member=%s",
            discord.__version__,
            hasattr(discord.Guild, "add_member"),
            hasattr(discord.http.HTTPClient, "add_member"),
        )
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching, name=f"{Config.PREFIX}help | Managing Users"
            ),
            status=discord.Status.dnd,
        )

    async def close(self):
        await self.db.close()
        await super().close()


async def main():
    if not Config.TOKEN or not Config.CLIENT_ID or not Config.CLIENT_SECRET:
        raise SystemExit("Missing DISCORD_TOKEN / CLIENT_ID / CLIENT_SECRET in environment.")

    bot = VeniceBot()
    async with bot:
        await bot.start(Config.TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
