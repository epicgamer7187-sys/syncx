import os
from dotenv import load_dotenv

load_dotenv()


def _int(name, default=0):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    TOKEN = os.getenv("DISCORD_TOKEN", "")
    CLIENT_ID = os.getenv("CLIENT_ID", "")
    CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
    BOT_OWNER_ID = _int("BOT_OWNER_ID", 0)
    PREFIX = os.getenv("PREFIX", ",")
    REDIRECT_URI = os.getenv("REDIRECT_URI", "")
    PORT = _int("PORT", 8080)
    DB_PATH = os.getenv("DB_PATH", "data/bot.db")
    SUPPORT_SERVER = os.getenv("SUPPORT_SERVER", "")

    # Defaults
    DEFAULT_NORMAL_LIMIT = 10
    MAX_QUEUE = 25
    COOLDOWN_SECONDS = 120

    # Token endpoint
    DISCORD_API = "https://discord.com/api/v10"
