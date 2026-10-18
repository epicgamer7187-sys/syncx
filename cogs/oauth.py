import time

import aiohttp
import discord
from discord.ext import commands

from config import Config


class OAuth(commands.Cog):
    """Handles token storage and refresh."""

    def __init__(self, bot):
        self.bot = bot

    async def get_valid_token(self, user_id):
        row = await self.bot.db.get_oauth(user_id)
        if not row or not row["authorized"]:
            return None

        if "guilds.join" not in (row["scope"] or ""):
            return None

        if row["expires_at"] and row["expires_at"] - 120 > time.time():
            return row["access_token"]

        refreshed = await self._refresh(user_id, row["refresh_token"])
        if refreshed:
            return refreshed

        if row["expires_at"] and row["expires_at"] > time.time():
            return row["access_token"]

        return None

    async def _refresh(self, user_id, refresh_token):
        if not refresh_token:
            return None

        data = {
            "client_id": Config.CLIENT_ID,
            "client_secret": Config.CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{Config.DISCORD_API}/oauth2/token", data=data) as r:
                    if r.status != 200:
                        await self.bot.db.set_authorized(user_id, False)
                        return None
                    payload = await r.json()
        except Exception:
            return None

        expires_at = int(time.time()) + payload.get("expires_in", 604800)
        await self.bot.db.save_oauth(
            user_id,
            None,
            payload["access_token"],
            payload.get("refresh_token", refresh_token),
            expires_at,
            authorized=True,
            scope=payload.get("scope"),
        )
        return payload["access_token"]

    async def is_authorized(self, user_id) -> bool:
        row = await self.bot.db.get_oauth(user_id)
        if not row or not row["authorized"]:
            return False
        return "guilds.join" in (row["scope"] or "")

    @commands.hybrid_command(name="authorize", aliases=["auth"], description="Get your authorization link")
    async def authorize(self, ctx):
        from utils import brand
        from web import oauth_url

        guild_id = ctx.guild.id if ctx.guild else None
        url = oauth_url(guild_id, ctx.channel.id)

        row = await self.bot.db.get_oauth(ctx.author.id)
        if row and row["authorized"] and "guilds.join" in (row["scope"] or ""):
            status = "Authorized"
        else:
            status = "Not authorized"

        embed = brand(
            f"**Status:** {status}\n\n"
            "Click the button below to authorize the bot to add you to servers.",
            title="<:greenlink:1561396716157014046>Authorization",
        )
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Authorize", url=url, style=discord.ButtonStyle.link))
        await ctx.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(OAuth(bot))
