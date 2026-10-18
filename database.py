import os
import time

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_users (
    user_id       INTEGER PRIMARY KEY,
    username      TEXT,
    access_token  TEXT,
    refresh_token TEXT,
    expires_at    INTEGER DEFAULT 0,
    authorized    INTEGER DEFAULT 1,
    scope         TEXT DEFAULT '',
    created_at    INTEGER
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS role_limits (
    role_id INTEGER PRIMARY KEY,
    amount  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS blacklist_servers (
    server_id INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS blacklist_users (
    user_id INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS usage (
    user_id  INTEGER PRIMARY KEY,
    used     INTEGER DEFAULT 0,
    cooldown INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS queue (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER,
    source_guild_id  INTEGER,
    guild_id         INTEGER,
    channel_id       INTEGER,
    amount           INTEGER,
    created_at       INTEGER
);

CREATE TABLE IF NOT EXISTS verified (
    guild_id    INTEGER,
    user_id     INTEGER,
    verified_at INTEGER,
    PRIMARY KEY (guild_id, user_id)
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self):
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self._migrate()
        await self.conn.commit()

    async def _migrate(self):
        cur = await self.conn.execute("PRAGMA table_info(oauth_users)")
        columns = {row["name"] for row in await cur.fetchall()}
        if "scope" not in columns:
            await self.conn.execute("ALTER TABLE oauth_users ADD COLUMN scope TEXT DEFAULT ''")
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()

    # ---------------- settings ----------------
    async def get_setting(self, key, default=None):
        cur = await self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else default

    async def set_setting(self, key, value):
        await self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        await self.conn.commit()

    async def get_setting_int(self, key, default=0):
        value = await self.get_setting(key)
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    # ---------------- role limits ----------------
    async def get_role_limits(self) -> dict:
        cur = await self.conn.execute("SELECT role_id, amount FROM role_limits")
        return {r["role_id"]: r["amount"] for r in await cur.fetchall()}

    async def set_role_limit(self, role_id, amount):
        await self.conn.execute(
            "INSERT INTO role_limits (role_id, amount) VALUES (?, ?) "
            "ON CONFLICT(role_id) DO UPDATE SET amount = excluded.amount",
            (role_id, amount),
        )
        await self.conn.commit()

    async def remove_role_limit(self, role_id):
        await self.conn.execute("DELETE FROM role_limits WHERE role_id = ?", (role_id,))
        await self.conn.commit()

    # ---------------- blacklist ----------------
    async def add_blacklist_server(self, server_id):
        await self.conn.execute("INSERT OR IGNORE INTO blacklist_servers VALUES (?)", (server_id,))
        await self.conn.commit()

    async def remove_blacklist_server(self, server_id):
        await self.conn.execute("DELETE FROM blacklist_servers WHERE server_id = ?", (server_id,))
        await self.conn.commit()

    async def is_server_blacklisted(self, server_id) -> bool:
        cur = await self.conn.execute("SELECT 1 FROM blacklist_servers WHERE server_id = ?", (server_id,))
        return await cur.fetchone() is not None

    async def list_blacklist_servers(self):
        cur = await self.conn.execute("SELECT server_id FROM blacklist_servers ORDER BY server_id")
        return [r["server_id"] for r in await cur.fetchall()]

    async def add_blacklist_user(self, user_id):
        await self.conn.execute("INSERT OR IGNORE INTO blacklist_users VALUES (?)", (user_id,))
        await self.conn.commit()

    async def remove_blacklist_user(self, user_id):
        await self.conn.execute("DELETE FROM blacklist_users WHERE user_id = ?", (user_id,))
        await self.conn.commit()

    async def is_user_blacklisted(self, user_id) -> bool:
        cur = await self.conn.execute("SELECT 1 FROM blacklist_users WHERE user_id = ?", (user_id,))
        return await cur.fetchone() is not None

    async def list_blacklist_users(self):
        cur = await self.conn.execute("SELECT user_id FROM blacklist_users ORDER BY user_id")
        return [r["user_id"] for r in await cur.fetchall()]

    # ---------------- usage ----------------
    async def get_usage(self, user_id):
        cur = await self.conn.execute("SELECT used, cooldown FROM usage WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        if row is None:
            await self.conn.execute(
                "INSERT OR IGNORE INTO usage (user_id, used, cooldown) VALUES (?, 0, 0)", (user_id,)
            )
            await self.conn.commit()
            return {"used": 0, "cooldown": 0}
        return {"used": row["used"], "cooldown": row["cooldown"]}

    async def set_usage(self, user_id, used=None, cooldown=None):
        await self.get_usage(user_id)
        if used is not None:
            await self.conn.execute("UPDATE usage SET used = ? WHERE user_id = ?", (used, user_id))
        if cooldown is not None:
            await self.conn.execute("UPDATE usage SET cooldown = ? WHERE user_id = ?", (cooldown, user_id))
        await self.conn.commit()

    async def get_expired_cooldowns(self, now):
        cur = await self.conn.execute(
            "SELECT user_id FROM usage WHERE cooldown > 0 AND cooldown <= ? AND used > 0", (now,)
        )
        return [r["user_id"] for r in await cur.fetchall()]

    # ---------------- queue ----------------
    async def queue_size(self) -> int:
        cur = await self.conn.execute("SELECT COUNT(*) AS c FROM queue")
        return (await cur.fetchone())["c"]

    async def add_queue(self, user_id, source_guild_id, guild_id, channel_id, amount):
        await self.conn.execute(
            "INSERT INTO queue (user_id, source_guild_id, guild_id, channel_id, amount, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, source_guild_id, guild_id, channel_id, amount, int(time.time())),
        )
        await self.conn.commit()

    async def queue_list(self):
        cur = await self.conn.execute("SELECT * FROM queue ORDER BY id ASC")
        return await cur.fetchall()

    async def queue_position(self, user_id) -> int:
        rows = await self.queue_list()
        for i, row in enumerate(rows, start=1):
            if row["user_id"] == user_id:
                return i
        return 0

    async def pop_queue(self):
        cur = await self.conn.execute("SELECT * FROM queue ORDER BY id ASC LIMIT 1")
        row = await cur.fetchone()
        if row:
            await self.conn.execute("DELETE FROM queue WHERE id = ?", (row["id"],))
            await self.conn.commit()
        return row

    async def clear_queue(self):
        await self.conn.execute("DELETE FROM queue")
        await self.conn.commit()

    # ---------------- oauth ----------------
    async def save_oauth(self, user_id, username, access_token, refresh_token,
                         expires_at, authorized=True, scope=None):
        existing = await self.get_oauth(user_id)
        if existing:
            username = username or existing["username"]
            scope = scope if scope is not None else existing["scope"]
            await self.conn.execute(
                "UPDATE oauth_users SET username=?, access_token=?, refresh_token=?, "
                "expires_at=?, authorized=?, scope=? WHERE user_id=?",
                (username, access_token, refresh_token, expires_at, int(authorized), scope, user_id),
            )
        else:
            await self.conn.execute(
                "INSERT INTO oauth_users (user_id, username, access_token, refresh_token, "
                "expires_at, authorized, scope, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, username, access_token, refresh_token, expires_at,
                 int(authorized), scope or "", int(time.time())),
            )
        await self.conn.commit()

    async def get_oauth(self, user_id):
        cur = await self.conn.execute("SELECT * FROM oauth_users WHERE user_id = ?", (user_id,))
        return await cur.fetchone()

    async def set_authorized(self, user_id, state: bool):
        await self.conn.execute("UPDATE oauth_users SET authorized = ? WHERE user_id = ?", (int(state), user_id))
        await self.conn.commit()

    async def get_authorized_users(self):
        cur = await self.conn.execute(
            "SELECT user_id FROM oauth_users WHERE authorized = 1 ORDER BY created_at ASC"
        )
        return [r["user_id"] for r in await cur.fetchall()]

    async def count_authorized(self) -> int:
        cur = await self.conn.execute("SELECT COUNT(*) AS c FROM oauth_users WHERE authorized = 1")
        return (await cur.fetchone())["c"]

    async def get_bad_scope_users(self):
        cur = await self.conn.execute(
            "SELECT user_id, username, scope FROM oauth_users "
            "WHERE authorized = 1 AND (scope IS NULL OR scope NOT LIKE '%guilds.join%')"
        )
        return await cur.fetchall()

    # ---------------- verified ----------------
    async def add_verified(self, guild_id, user_id):
        await self.conn.execute(
            "INSERT OR REPLACE INTO verified (guild_id, user_id, verified_at) VALUES (?, ?, ?)",
            (guild_id, user_id, int(time.time())),
        )
        await self.conn.commit()

    async def remove_verified(self, guild_id, user_id):
        await self.conn.execute("DELETE FROM verified WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        await self.conn.commit()

    async def get_verified(self, guild_id=None):
        if guild_id is None:
            cur = await self.conn.execute("SELECT * FROM verified")
        else:
            cur = await self.conn.execute("SELECT * FROM verified WHERE guild_id = ?", (guild_id,))
        return await cur.fetchall()
