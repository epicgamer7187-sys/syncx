import discord

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


def ok(desc, title="Success"):
    return _build(desc, title=title, color=SUCCESS)


def err(desc, title="Error"):
    return _build(desc, title=title, color=ERROR)


def info(desc, title=None):
    return _build(desc, title=title, color=INFO)


def warn(desc, title="Notice"):
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


async def add_member_to_guild(bot, guild, user_id, access_token):
    """Add a user to a guild with their OAuth token.

    Routes through the raw HTTP layer when Guild.add_member is unavailable,
    which is the case on newer discord.py builds.
    """
    fn = getattr(guild, "add_member", None)
    if callable(fn):
        return await fn(discord.Object(id=user_id), access_token=access_token)

    http_fn = getattr(bot.http, "add_member", None) or getattr(bot.http, "add_guild_member")
    await http_fn(guild.id, user_id, access_token=access_token)

    try:
        return await guild.fetch_member(user_id)
    except discord.HTTPException:
        return None
