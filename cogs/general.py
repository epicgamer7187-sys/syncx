import io
import json
import time

import discord
from discord.ext import commands

from database import BACKUP_VERSION
from utils import err, info, ok, ts
from web import bot_invite_url

MAX_BYTES = 24 * 1024 * 1024


class General(commands.Cog):
    """Miscellaneous utilities and backups."""

    def __init__(self, bot):
        self.bot = bot
        self.started = time.time()

    @commands.hybrid_command(name="ping", description="Check the bot latency")
    async def ping(self, ctx):
        await ctx.send(
            embed=ok(f"**Gateway latency:** `{round(self.bot.latency * 1000)}ms`", title="Pong")
        )

    @commands.hybrid_command(name="invite", description="Get the correctly-scoped bot invite link")
    async def invite(self, ctx):
        embed = info(
            "Use **this** link to add the bot to a server.\n"
            "Use the `verify_panel` button for user authorization - they are different flows.",
            title="Bot Invite",
        )
        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label="Invite Bot", url=bot_invite_url(), style=discord.ButtonStyle.link
            )
        )
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="stats", description="Bot statistics")
    async def stats(self, ctx):
        authorized = await self.bot.db.count_authorized()
        queued = await self.bot.db.queue_size()
        embed = info(
            f"**Authorized:** `{authorized}`\n"
            f"**Queue:** `{queued}`\n"
            f"**Guilds:** `{len(self.bot.guilds)}`\n"
            f"**Latency:** `{round(self.bot.latency * 1000)}ms`",
            title="Statistics",
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="authcount", aliases=["authorized", "auths"], description="Count authorized users"
    )
    @commands.guild_only()
    @commands.is_owner()
    async def authcount(self, ctx):
        count = await self.bot.db.count_authorized()
        await ctx.send(embed=info(f"**Total authorized users:** `{count}`", title="Authorized Users"))

    @commands.hybrid_command(name="recheck", description="Find accounts with a bad OAuth scope")
    @commands.is_owner()
    async def recheck(self, ctx):
        rows = await self.bot.db.get_bad_scope_users()
        if not rows:
            return await ctx.send(embed=ok("Every stored account has a valid `guilds.join` scope."))
        lines = [f"<@{r['user_id']}> - scope `{r['scope'] or 'empty'}`" for r in rows[:20]]
        await ctx.send(
            embed=info(
                "\n".join(lines) + f"\n\n**{len(rows)}** account(s) need to re-authorize.",
                title="Bad Scope Accounts",
            )
        )

    @commands.hybrid_command(name="attempts", description="Recent pull attempts")
    @commands.is_owner()
    async def attempts(self, ctx):
        rows = await self.bot.db.list_pulls(20)
        if not rows:
            return await ctx.send(embed=info("No attempts recorded."))
        lines = [
            f"<@{r['user_id']}> -> `{r['guild_id']}` - {r['count']}x - {ts(r['last_pull'])}"
            for r in rows
        ]
        await ctx.send(embed=info("\n".join(lines), title="Attempts"))

    @commands.hybrid_command(name="resetattempts", description="Clear a user/server attempt record")
    @commands.is_owner()
    async def resetattempts(self, ctx, user: discord.User, server_id: str):
        try:
            sid = int(server_id.strip())
        except ValueError:
            return await ctx.send(embed=err("Invalid server ID."))
        await self.bot.db.reset_pull(user.id, sid)
        await ctx.send(embed=ok(f"Cleared attempts for {user.mention} on `{sid}`."))

    @commands.hybrid_command(name="synccmds", description="Re-sync slash commands")
    @commands.is_owner()
    async def synccmds(self, ctx):
        synced = await self.bot.tree.sync()
        await ctx.send(embed=ok(f"Synced `{len(synced)}` slash commands."))

    @commands.hybrid_command(name="clearqueue", description="Clear the queue")
    @commands.is_owner()
    async def clearqueue(self, ctx):
        await self.bot.db.clear_queue()
        await ctx.send(embed=ok("Queue cleared."))

    @commands.hybrid_command(name="resetuser", description="Reset a user's usage")
    @commands.is_owner()
    async def resetuser(self, ctx, user: discord.User):
        await self.bot.db.set_usage(user.id, used=0, cooldown=0)
        await ctx.send(embed=ok(f"Reset usage for {user.mention}."))

    # ---------------- backup / restore ----------------
    def _attachment(self, ctx, attachment):
        if attachment is not None:
            return attachment
        message = getattr(ctx, "message", None)
        if message is not None and message.attachments:
            return message.attachments[0]
        return None

    async def _read(self, attachment):
        if attachment.size > MAX_BYTES:
            raise ValueError(f"File is {attachment.size // 1048576} MB, limit is 24 MB.")
        raw = await attachment.read()
        return json.loads(raw.decode("utf-8"))

    @commands.hybrid_command(name="backup", description="Export the whole database to a file")
    @commands.is_owner()
    async def backup(self, ctx):
        await ctx.defer()
        payload = await self.bot.db.export_all()
        raw = json.dumps(payload, indent=2, default=str).encode("utf-8")

        if len(raw) > MAX_BYTES:
            return await ctx.send(
                embed=err(f"Export is {len(raw) // 1048576} MB, over the 24 MB attachment cap.")
            )

        stamp = time.strftime("%Y%m%d-%H%M%S")
        file = discord.File(io.BytesIO(raw), filename=f"backup-{stamp}.json")
        counts = {k: len(v) for k, v in payload["tables"].items()}

        await ctx.send(
            content=f"Backup `{file.filename}`",
            embed=info(
                "\n".join(f"`{t}`: {c}" for t, c in counts.items()),
                title="Backup Complete",
            ),
            file=file,
        )

    @commands.hybrid_command(name="restore", description="Preview a backup before applying it")
    @commands.is_owner()
    async def restore(self, ctx, attachment: discord.Attachment = None):
        await ctx.defer()
        file = self._attachment(ctx, attachment)
        if file is None:
            return await ctx.send(embed=err("Attach a `.json` backup file."))
        if not file.filename.endswith(".json"):
            return await ctx.send(embed=err("File must be `.json`."))

        try:
            payload = await self._read(file)
        except Exception as exc:
            return await ctx.send(embed=err(f"Could not read the file: {exc}"))

        if payload.get("version") != BACKUP_VERSION:
            return await ctx.send(
                embed=err(f"Version mismatch. File has `{payload.get('version')}`, expected `{BACKUP_VERSION}`.")
            )

        incoming = payload.get("tables") or {}
        current = await self.bot.db.table_counts()
        lines = []
        for table in current:
            lines.append(f"`{table}`: {current[table]} -> {len(incoming.get(table) or [])}")

        await ctx.send(
            embed=info(
                "\n".join(lines)
                + "\n\nRun `,restoreconfirm` with the same file to apply.",
                title="Restore Preview",
            )
        )

    @commands.hybrid_command(name="restoreconfirm", description="Apply a backup file")
    @commands.is_owner()
    async def restoreconfirm(self, ctx, attachment: discord.Attachment = None):
        await ctx.defer()
        file = self._attachment(ctx, attachment)
        if file is None:
            return await ctx.send(embed=err("Attach the `.json` backup file."))

        try:
            payload = await self._read(file)
        except Exception as exc:
            return await ctx.send(embed=err(f"Could not read the file: {exc}"))

        previous = await self.bot.db.get_setting_int("maintenance", 0)
        await self.bot.db.set_setting("maintenance", 1)

        try:
            await self.bot.db.import_all(payload)
        except Exception as exc:
            await self.bot.db.set_setting("maintenance", previous)
            return await ctx.send(embed=err(f"Restore rolled back: {exc}"))
        finally:
            await self.bot.db.set_setting("maintenance", previous)

        counts = await self.bot.db.table_counts()
        await ctx.send(
            embed=ok(
                "\n".join(f"`{t}`: {c}" for t, c in counts.items()),
                title="Restore Complete",
            )
        )


async def setup(bot):
    await bot.add_cog(General(bot))
