import base64
import json
import logging
import time
import urllib.parse

import aiohttp
import discord
from aiohttp import web

from config import Config

log = logging.getLogger("venice.web")

TOKEN_URL = f"{Config.DISCORD_API}/oauth2/token"
ME_URL = f"{Config.DISCORD_API}/users/@me"

HTML_OK = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Authorized</title>
<style>
body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
background:#0b0b12;color:#fff;font-family:system-ui,Segoe UI,Roboto,sans-serif}
.card{background:#15151f;padding:48px 56px;border-radius:20px;text-align:center;
box-shadow:0 20px 60px rgba(124,58,237,.35);border:1px solid #26263a;max-width:460px}
h1{margin:0 0 12px;font-size:26px;background:linear-gradient(90deg,#a78bfa,#60a5fa);
-webkit-background-clip:text;-webkit-text-fill-color:transparent}
p{color:#a1a1b5;line-height:1.6;margin:0}
.tick{font-size:54px;margin-bottom:16px}
</style></head><body><div class="card">
<div class="tick">&#10004;</div>
<h1>Authorization Complete</h1>
<p>You have been verified successfully.<br>You can now close this tab and return to Discord.</p>
</div></body></html>"""

HTML_ERROR = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Error</title>
<style>
body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
background:#0b0b12;color:#fff;font-family:system-ui,Segoe UI,Roboto,sans-serif}
.card{background:#15151f;padding:48px 56px;border-radius:20px;text-align:center;
box-shadow:0 20px 60px rgba(239,68,68,.3);border:1px solid #26263a;max-width:460px}
h1{margin:0 0 12px;font-size:26px;color:#f87171}
p{color:#a1a1b5;line-height:1.6;margin:0}
.x{font-size:54px;margin-bottom:16px}
</style></head><body><div class="card">
<div class="x">&#10006;</div>
<h1>Authorization Failed</h1>
<p>{reason}</p>
</div></body></html>"""


def _error_page(reason="Something went wrong. Please try again from Discord."):
    return web.Response(text=HTML_ERROR.replace("{reason}", reason), content_type="text/html")


def make_state(guild_id, channel_id=None):
    payload = json.dumps({"g": str(guild_id), "c": str(channel_id) if channel_id else None})
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def parse_state(state):
    if not state:
        return None, None
    try:
        pad = "=" * (-len(state) % 4)
        data = json.loads(base64.urlsafe_b64decode(state + pad).decode())
        return data.get("g"), data.get("c")
    except Exception:
        return None, None


def oauth_url(guild_id, channel_id=None):
    params = {
        "client_id": Config.CLIENT_ID,
        "redirect_uri": Config.REDIRECT_URI,
        "response_type": "code",
        "scope": "identify guilds.join",
        "state": make_state(guild_id, channel_id),
        "prompt": "consent",
    }
    if guild_id:
        params["guild_id"] = str(guild_id)
        params["disable_guild_select"] = "true"
    return "https://discord.com/oauth2/authorize?" + urllib.parse.urlencode(
        params, quote_via=urllib.parse.quote
    )


class WebServer:
    def __init__(self, bot):
        self.bot = bot
        self.app = web.Application()
        self.app.router.add_get("/", self.index)
        self.app.router.add_get("/callback", self.callback)
        self.runner = None

    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "0.0.0.0", Config.PORT)
        await site.start()
        log.info("OAuth web server listening on port %s", Config.PORT)

    async def index(self, request):
        return web.Response(text="Venice Member Bot is running.", content_type="text/plain")

    async def callback(self, request):
        query = request.query
        code = query.get("code")
        state = query.get("state", "")

        if query.get("error"):
            log.warning("OAuth denied: %s", query.get("error_description"))
            return _error_page("You cancelled the authorization.")

        if not code:
            return _error_page("No authorization code was returned.")

        guild_id, channel_id = parse_state(state)
        if not guild_id:
            # Discord's install-link flow passes guild_id directly and no state
            guild_id = query.get("guild_id")
        if not guild_id:
            guild_id = await self.bot.db.get_setting_int("verify_guild", 0) or None

        data = {
            "client_id": Config.CLIENT_ID,
            "client_secret": Config.CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": Config.REDIRECT_URI,
        }

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                async with session.post(TOKEN_URL, data=data) as r:
                    token = await r.json(content_type=None)
                    if r.status != 200 or "access_token" not in token:
                        log.warning("Token exchange failed %s: %s", r.status, token)
                        return _error_page("Could not exchange the authorization code.")

                headers = {"Authorization": f"Bearer {token['access_token']}"}
                async with session.get(ME_URL, headers=headers) as r:
                    user = await r.json(content_type=None)
                    if r.status != 200 or "id" not in user:
                        log.warning("User fetch failed %s: %s", r.status, user)
                        return _error_page("Could not read your Discord profile.")
        except aiohttp.ClientError as exc:
            log.exception("OAuth callback network error")
            return _error_page(f"Network error: {exc}")
        except Exception:
            log.exception("OAuth callback unexpected error")
            return _error_page()

        scopes = str(token.get("scope", ""))
        if "guilds.join" not in scopes:
            log.warning("Token missing guilds.join scope. Got: %r", scopes)

        expires_at = int(time.time()) + int(token.get("expires_in", 604800))
        user_id = int(user["id"])

        await self.bot.db.save_oauth(
            user_id,
            user.get("username"),
            token["access_token"],
            token.get("refresh_token"),
            expires_at,
            authorized=True,
        )

        if guild_id:
            await self._finish_verification(int(guild_id), user_id, token["access_token"])

        return web.Response(text=HTML_OK, content_type="text/html")

    async def _finish_verification(self, guild_id, user_id, access_token):
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            log.warning("Verified user %s but bot is not in guild %s", user_id, guild_id)
            return

        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.HTTPException:
                member = None

        if member is None:
            if guild.me is None or not guild.me.guild_permissions.create_instant_invite:
                log.warning("Missing Create Invite permission in guild %s", guild_id)
                return
            try:
                member = await guild.add_member(
                    discord.Object(id=user_id), access_token=access_token
                )
            except discord.HTTPException:
                log.exception("Failed to add verified member to guild %s", guild_id)
                return

        role_id = await self.bot.db.get_setting_int("verify_role", 0)
        if role_id and member is not None:
            role = guild.get_role(role_id)
            if role is not None:
                try:
                    await member.add_roles(role, reason="Verification")
                except discord.HTTPException:
                    log.exception("Failed to grant verify role in guild %s", guild_id)

        await self.bot.db.add_verified(guild_id, user_id)
