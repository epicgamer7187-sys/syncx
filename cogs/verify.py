import discord
from discord.ext import commands

from utils import brand, info, ok
from web import oauth_url


class Verify(commands.Cog):
    """Verification panel and role assignment."""

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="verify_panel", description="Send the verification panel")
    @commands.guild_only()
    @commands.is_owner()
    async def verify_panel(self, ctx, channel: discord.TextChannel = None):
        await ctx.defer()
        channel = channel or ctx.channel

        url = oauth_url(ctx.guild.id, channel.id)
        role_id = await self.bot.db.get_setting_int("verify_role", 0)
        role_text = f"<@&{role_id}>" if role_id else "*not configured*"

        embed = brand(
            "**Authorize once. Get verified. Get added anywhere.**\n\n"
            "Click the button below and approve the request.\n"
            "The link is **permanent** - unlimited members can use it.",
            title="<:greenlink:1561396716157014046>Verification",
        )
        embed.add_field(name="You will receive", value=role_text, inline=False)
        embed.set_footer(text="Venice Member Bot - Secure OAuth2")

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Authorize", url=url, style=discord.ButtonStyle.link))

        await channel.send(embed=embed, view=view)
        if channel.id != ctx.channel.id:
            await ctx.send(embed=ok(f"Verification panel sent to {channel.mention}."))

    @commands.hybrid_command(name="resync", description="Resync verified users")
    @commands.guild_only()
    @commands.is_owner()
    async def resync(self, ctx):
        await ctx.defer()
        oauth = self.bot.get_cog("OAuth")

        rows = await self.bot.db.get_verified(ctx.guild.id)
        checked = valid = invalid = 0

        for row in rows:
            checked += 1
            if await oauth.get_valid_token(row["user_id"]):
                valid += 1
            else:
                invalid += 1
                await self.bot.db.set_authorized(row["user_id"], False)

        await ctx.send(
            embed=info(
                f"**Checked:** `{checked}`\n"
                f"**Still authorized:** `{valid}`\n"
                f"**No longer authorized:** `{invalid}`",
                title="Resync Complete",
            )
        )

    @commands.hybrid_command(name="verified_count", description="Count verified users")
    @commands.guild_only()
    @commands.is_owner()
    async def verified_count(self, ctx):
        rows = await self.bot.db.get_verified(ctx.guild.id)
        await ctx.send(embed=info(f"**Verified members:** `{len(rows)}`", title="Verified Count"))


async def setup(bot):
    await bot.add_cog(Verify(bot))
