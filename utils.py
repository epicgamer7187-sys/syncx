import logging

import discord

log = logging.getLogger("venice.utils")

BRAND = 0x7C3AED
SUCCESS = 0x10B981
ERROR = 0xEF4444
WARN = 0xF59E0B
INFO = 0x3B82F6

FOOTER = "Venice Member Bot"


def _build(description=None, title=None, color=BRAND, footer=FOOTER):
    e = discord.Embed(color=color)
    if title:
        e.title = title
    if description:
        e.description = description
    if footer:
        e.set_footer(text=footer)
    return e


def ok(desc=None, title="Success"):
    return _build(desc, title=title, color=SUCCESS)


def err(desc=None, title="Error"):
    return _build(desc, title=title, color=ERROR)


def info(desc=None, title=None):
    return _build(desc, title=title, color=INFO)


def warn(desc=None, title="Notice"):
    return _build(desc, title=title, color=WARN)


def brand(desc=None, title=None):
    return _build(desc, title=title, color=BRAND)


def ts(seconds: int) -> str:
    return f"<t:{int(seconds)}:R>"


async def respond(ctx, embed, ephemeral=True):
    try:
        if ctx.interaction is not None:
            if ctx.interaction.response.is_done():
                await ctx.send(embed=embed)
            else:
                await ctx.send(embed=embed, ephemeral=ephemeral)
        else:
            await ctx.reply(embed=embed, mention_author=False)
    except discord.HTTPException:
        pass


def _member_route(guild_id, user_id):
    try:
        from discord.http import Route
    except ImportError:
        from discord import Route
    return Route(
        "PUT",
        "/guilds/{guild_id}/members/{user_id}",
        guild_id=guild_id,
        user_id=user_id,
    )


_warned = False


async def add_member_to_guild(bot, guild, user_id, access_token):
    """Add a user to a guild using their OAuth2 token.

    Tries, in order:
      1. Guild.add_member          (older public helper)
      2. Any named HTTPClient variant
      3. Raw PUT via Route         (mirrors discord.py's own implementation)
    """
    global _warned

    fn = getattr(guild, "add_member", None)
    if callable(fn):
        return await fn(discord.Object(id=user_id), access_token=access_token)

    http = bot.http

    for name in ("add_member", "add_guild_member", "guild_member_add"):
        candidate = getattr(http, name, None)
        if callable(candidate):
            return await candidate(guild.id, user_id, access_token=access_token)

    if not _warned:
        _warned = True
        log.warning(
            "No named member-add helper found; using raw Route. "
            "Guild.add_member=%s, HTTPClient member methods=%s",
            hasattr(discord.Guild, "add_member"),
            sorted(n for n in dir(http) if "member" in n.lower()),
        )

    await http.request(_member_route(guild.id, user_id), json={"access_token": access_token})

    try:
        return await guild.fetch_member(user_id)
    except discord.HTTPException:
        return None
