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


def human_list(items, formatter, empty="None"):
    if not items:
        return empty
    return "\n".join(formatter(i) for i in items)


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
