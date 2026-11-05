import json
import os
import time
import uuid

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_users (
    user_id INTEGER PRIMARY KEY, username TEXT, access_token TEXT,
    refresh_token TEXT, expires_at INTEGER DEFAULT 0,
    authorized INTEGER DEFAULT 1, scope TEXT DEFAULT '', created_at INTEGER
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS role_limits (role_id INTEGER PRIMARY KEY, amount INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS blacklist_servers (server_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS blacklist_users (user_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS usage (
    user_id INTEGER PRIMARY KEY, used INTEGER DEFAULT 0, cooldown INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE, user_id INTEGER,
    source_guild_id INTEGER, guild_id INTEGER, channel_id INTEGER,
    amount INTEGER, created_at INTEGER
);
CREATE TABLE IF NOT EXISTS verified (
    guild_id INTEGER, user_id INTEGER, verified_at INTEGER,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS pulls (
    user_id INTEGER, guild_id INTEGER, count INTEGER DEFAULT 0,
    last_pull INTEGER DEFAULT 0, PRIMARY KEY (user_id, guild_id)
);
CREATE TABLE IF NOT EXISTS pending_ops (
    id INTEGER PRIMARY KEY AUTOINCREMENT, collection TEXT, op TEXT,
    payload TEXT, created_at INTEGER
);
"""


class SqliteBackend:
    def __init__(self, path):
        self.path = path
        self.conn = None

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
        cols = {r["name"] for r in await cur.fetchall()}
        if "scope" not in cols:
            await self.conn.execute("ALTER TABLE oauth_users ADD COLUMN scope TEXT DEFAULT ''")
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()

    # ---------------- journal ----------------
    async def log_op(self, collection, op, payload):
        await self.conn.execute(
            "INSERT INTO pending_ops (collection, op, payload, created_at) VALUES (?, ?, ?, ?)",
            (collection, op, json.dumps(payload), int(time.time())),
        )
        await self.conn.commit()

    async def pending_ops(self):
        cur = await self.conn.execute("SELECT * FROM pending_ops ORDER BY id ASC")
        return await cur.fetchall()

    async def pending_count(self):
        cur = await self.conn.execute("SELECT COUNT(*) AS c FROM pending_ops")
        return (await cur.fetchone())["c"]

    async def clear_pending(self, ids):
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        await self.conn.execute(f"DELETE FROM pending_ops WHERE id IN ({marks})", ids)
        await self.conn.commit()

    # ---------------- settings ----------------
    async def get_setting(self, key, default=None):
        cur = await self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else default

    async def set_setting(self, key, value):
        await self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value))
        )
        await self.conn.commit()

    # ---------------- role limits ----------------
    async def get_role_limits(self):
        cur = await self.conn.execute("SELECT role_id, amount FROM role_limits")
        return {r["role_id"]: r["amount"] for r in await cur.fetchall()}

    async def set_role_limit(self, role_id, amount):
        await self.conn.execute(
            "INSERT INTO role_limits (role_id, amount) VALUES (?, ?) "
            "ON CONFLICT(role_id) DO UPDATE SET amount = excluded.amount", (role_id, amount)
        )
        await self.conn.commit()

    async def remove_role_limit(self, role_id):
        await self.conn.execute("DELETE FROM role_limits WHERE role_id = ?", (role_id,))
        await self.conn.commit()

    # ---------------- blacklists ----------------
    async def add_blacklist_server(self, sid):
        await self.conn.execute("INSERT OR IGNORE INTO blacklist_servers VALUES (?)", (sid,))
        await self.conn.commit()

    async def remove_blacklist_server(self, sid):
        await self.conn.execute("DELETE FROM blacklist_servers WHERE server_id = ?", (sid,))
        await self.conn.commit()

    async def is_server_blacklisted(self, sid):
        cur = await self.conn.execute("SELECT 1 FROM blacklist_servers WHERE server_id = ?", (sid,))
        return await cur.fetchone() is not None

    async def list_blacklist_servers(self):
        cur = await self.conn.execute("SELECT server_id FROM blacklist_servers ORDER BY server_id")
        return [r["server_id"] for r in await cur.fetchall()]

    async def add_blacklist_user(self, uid):
        await self.conn.execute("INSERT OR IGNORE INTO blacklist_users VALUES (?)", (uid,))
        await self.conn.commit()

    async def remove_blacklist_user(self, uid):
        await self.conn.execute("DELETE FROM blacklist_users WHERE user_id = ?", (uid,))
        await self.conn.commit()

    async def is_user_blacklisted(self, uid):
        cur = await self.conn.execute("SELECT 1 FROM blacklist_users WHERE user_id = ?", (uid,))
        return await cur.fetchone() is not None

    async def list_blacklist_users(self):
        cur = await self.conn.execute("SELECT user_id FROM blacklist_users ORDER BY user_id")
        return [r["user_id"] for r in await cur.fetchall()]

    # ---------------- usage ----------------
    async def get_usage(self, uid):
        cur = await self.conn.execute("SELECT used, cooldown FROM usage WHERE user_id = ?", (uid,))
        row = await cur.fetchone()
        if row is None:
            await self.conn.execute(
                "INSERT OR IGNORE INTO usage (user_id, used, cooldown) VALUES (?, 0, 0)", (uid,)
            )
            await self.conn.commit()
            return {"used": 0, "cooldown": 0}
        return {"used": row["used"], "cooldown": row["cooldown"]}

    async def set_usage(self, uid, used=None, cooldown=None):
        current = await self.get_usage(uid)
        used = current["used"] if used is None else used
        cooldown = current["cooldown"] if cooldown is None else cooldown
        await self.conn.execute(
            "UPDATE usage SET used = ?, cooldown = ? WHERE user_id = ?", (used, cooldown, uid)
        )
        await self.conn.commit()
        return {"used": used, "cooldown": cooldown}

    async def get_expired_cooldowns(self, now):
        cur = await self.conn.execute(
            "SELECT user_id FROM usage WHERE cooldown > 0 AND cooldown <= ? AND used > 0", (now,)
        )
        return [r["user_id"] for r in await cur.fetchall()]

    # ---------------- queue ----------------
    async def queue_size(self):
        cur = await self.conn.execute("SELECT COUNT(*) AS c FROM queue")
        return (await cur.fetchone())["c"]

    async def add_queue(self, uid, sgid, gid, cid, amount):
        key = uuid.uuid4().hex
        await self.conn.execute(
            "INSERT INTO queue (key, user_id, source_guild_id, guild_id, channel_id, amount, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", (key, uid, sgid, gid, cid, amount, int(time.time()))
        )
        await self.conn.commit()
        cur = await self.conn.execute("SELECT * FROM queue WHERE key = ?", (key,))
        return await cur.fetchone()

    async def queue_list(self):
        cur = await self.conn.execute("SELECT * FROM queue ORDER BY created_at ASC, id ASC")
        return await cur.fetchall()

    async def queue_position(self, uid):
        for i, row in enumerate(await self.queue_list(), start=1):
            if row["user_id"] == uid:
                return i
        return 0

    async def pop_queue(self):
        cur = await self.conn.execute("SELECT * FROM queue ORDER BY created_at ASC, id ASC LIMIT 1")
        row = await cur.fetchone()
        if row:
            await self.conn.execute("DELETE FROM queue WHERE id = ?", (row["id"],))
            await self.conn.commit()
        return row

    async def clear_queue(self):
        await self.conn.execute("DELETE FROM queue")
        await self.conn.commit()

    # ---------------- oauth ----------------
    async def save_oauth(self, uid, username, access, refresh, expires, authorized=True, scope=None):
        existing = await self.get_oauth(uid)
        if existing:
            username = username or existing["username"]
            scope = existing["scope"] if scope is None else scope
            await self.conn.execute(
                "UPDATE oauth_users SET username=?, access_token=?, refresh_token=?, "
                "expires_at=?, authorized=?, scope=? WHERE user_id=?",
                (username, access, refresh, expires, int(authorized), scope, uid),
            )
        else:
            await self.conn.execute(
                "INSERT INTO oauth_users (user_id, username, access_token, refresh_token, "
                "expires_at, authorized, scope, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, username, access, refresh, expires, int(authorized), scope or "", int(time.time())),
            )
        await self.conn.commit()

    async def get_oauth(self, uid):
        cur = await self.conn.execute("SELECT * FROM oauth_users WHERE user_id = ?", (uid,))
        return await cur.fetchone()

    async def set_authorized(self, uid, state):
        await self.conn.execute("UPDATE oauth_users SET authorized = ? WHERE user_id = ?", (int(state), uid))
        await self.conn.commit()

    async def get_authorized_users(self):
        cur = await self.conn.execute(
            "SELECT user_id FROM oauth_users WHERE authorized = 1 ORDER BY created_at ASC"
        )
        return [r["user_id"] for r in await cur.fetchall()]

    async def count_authorized(self):
        cur = await self.conn.execute("SELECT COUNT(*) AS c FROM oauth_users WHERE authorized = 1")
        return (await cur.fetchone())["c"]

    async def get_bad_scope_users(self):
        cur = await self.conn.execute(
            "SELECT user_id, username, scope FROM oauth_users "
            "WHERE authorized = 1 AND (scope IS NULL OR scope NOT LIKE '%guilds.join%')"
        )
        return await cur.fetchall()

    # ---------------- verified ----------------
    async def add_verified(self, gid, uid):
        await self.conn.execute(
            "INSERT OR REPLACE INTO verified (guild_id, user_id, verified_at) VALUES (?, ?, ?)",
            (gid, uid, int(time.time())),
        )
        await self.conn.commit()

    async def remove_verified(self, gid, uid):
        await self.conn.execute("DELETE FROM verified WHERE guild_id = ? AND user_id = ?", (gid, uid))
        await self.conn.commit()

    async def get_verified(self, gid=None):
        if gid is None:
            cur = await self.conn.execute("SELECT * FROM verified")
        else:
            cur = await self.conn.execute("SELECT * FROM verified WHERE guild_id = ?", (gid,))
        return await cur.fetchall()

    # ---------------- pulls ----------------
    async def record_pull(self, uid, gid):
        now = int(time.time())
        await self.conn.execute(
            "INSERT INTO pulls (user_id, guild_id, count, last_pull) VALUES (?, ?, 1, ?) "
            "ON CONFLICT(user_id, guild_id) DO UPDATE SET count = count + 1, last_pull = excluded.last_pull",
            (uid, gid, now),
        )
        await self.conn.commit()
        return await self.get_pull(uid, gid)

    async def get_pull(self, uid, gid):
        cur = await self.conn.execute(
            "SELECT * FROM pulls WHERE user_id = ? AND guild_id = ?", (uid, gid)
        )
        return await cur.fetchone()

    async def reset_pull(self, uid, gid):
        await self.conn.execute("DELETE FROM pulls WHERE user_id = ? AND guild_id = ?", (uid, gid))
        await self.conn.commit()

    async def list_pulls(self, limit=20):
        cur = await self.conn.execute(
            "SELECT * FROM pulls ORDER BY last_pull DESC LIMIT ?", (limit,)
        )
        return await cur.fetchall()
