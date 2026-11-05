import asyncio
import json
import logging

from database import SqliteBackend
from mongo_backend import MongoBackend

log = logging.getLogger("venice.store")

PING_INTERVAL = 20


class Store:
    def __init__(self, sqlite_path, mongo_uri=None, mongo_db="syncx"):
        self.sqlite = SqliteBackend(sqlite_path)
        self.mongo = MongoBackend(mongo_uri, mongo_db) if mongo_uri else None
        self.online = False
        self._task = None

    # ---------------- lifecycle ----------------
    async def connect(self):
        await self.sqlite.connect()
        if self.mongo is None:
            log.info("MONGO_URI unset - SQLite only")
            return

        if await self.mongo.ping():
            replayed = await self.sync_pending()
            self.online = True
            log.info("MongoDB primary active (replayed %d pending ops)", replayed)
        else:
            log.warning("MongoDB unreachable at boot - SQLite fallback active")

        self._task = asyncio.create_task(self._health_loop())

    async def close(self):
        if self._task:
            self._task.cancel()
        await self.sqlite.close()
        if self.mongo is not None:
            await self.mongo.close()

    async def _health_loop(self):
        while True:
            try:
                alive = await self.mongo.ping()
                if alive and not self.online:
                    pending = await self.sqlite.pending_count()
                    log.info("MongoDB reachable again - replaying %d ops", pending)
                    await self.sync_pending()
                    self.online = True
                    log.info("Switched to MongoDB")
                elif not alive and self.online:
                    self.online = False
                    log.warning("MongoDB lost - SQLite fallback active")
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("Health loop error")
            await asyncio.sleep(PING_INTERVAL)

    async def sync_pending(self):
        if self.mongo is None:
            return 0
        ops = await self.sqlite.pending_ops()
        if not ops:
            return 0
        done = []
        for row in ops:
            try:
                await self.mongo.apply_op(row["collection"], row["op"], json.loads(row["payload"]))
                done.append(row["id"])
            except Exception:
                log.exception("Replay failed for op %s", row["id"])
                break
        await self.sqlite.clear_pending(done)
        return len(done)

    async def _journal(self, collection, op, payload):
        await self.sqlite.log_op(collection, op, payload)

    # ---------------- settings ----------------
    async def get_setting(self, key, default=None):
        backend = self.mongo if self.online else self.sqlite
        return await backend.get_setting(key, default)

    async def get_setting_int(self, key, default=0):
        value = await self.get_setting(key)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    async def set_setting(self, key, value):
        if self.online:
            return await self.mongo.set_setting(key, value)
        await self.sqlite.set_setting(key, value)
        await self._journal("settings", "upsert", {"key": key, "value": str(value)})

    # ---------------- role limits ----------------
    async def get_role_limits(self):
        backend = self.mongo if self.online else self.sqlite
        return await backend.get_role_limits()

    async def set_role_limit(self, role_id, amount):
        if self.online:
            return await self.mongo.set_role_limit(role_id, amount)
        await self.sqlite.set_role_limit(role_id, amount)
        await self._journal("role_limits", "upsert", {"role_id": role_id, "amount": amount})

    async def remove_role_limit(self, role_id):
        if self.online:
            return await self.mongo.remove_role_limit(role_id)
        await self.sqlite.remove_role_limit(role_id)
        await self._journal("role_limits", "delete", {"role_id": role_id})

    # ---------------- blacklists ----------------
    async def add_blacklist_server(self, sid):
        if self.online:
            return await self.mongo.add_blacklist_server(sid)
        await self.sqlite.add_blacklist_server(sid)
        await self._journal("blacklist_servers", "insert", {"server_id": sid})

    async def remove_blacklist_server(self, sid):
        if self.online:
            return await self.mongo.remove_blacklist_server(sid)
        await self.sqlite.remove_blacklist_server(sid)
        await self._journal("blacklist_servers", "delete", {"server_id": sid})

    async def is_server_blacklisted(self, sid):
        backend = self.mongo if self.online else self.sqlite
        return await backend.is_server_blacklisted(sid)

    async def list_blacklist_servers(self):
        backend = self.mongo if self.online else self.sqlite
        return await backend.list_blacklist_servers()

    async def add_blacklist_user(self, uid):
        if self.online:
            return await self.mongo.add_blacklist_user(uid)
        await self.sqlite.add_blacklist_user(uid)
        await self._journal("blacklist_users", "insert", {"user_id": uid})

    async def remove_blacklist_user(self, uid):
        if self.online:
            return await self.mongo.remove_blacklist_user(uid)
        await self.sqlite.remove_blacklist_user(uid)
        await self._journal("blacklist_users", "delete", {"user_id": uid})

    async def is_user_blacklisted(self, uid):
        backend = self.mongo if self.online else self.sqlite
        return await backend.is_user_blacklisted(uid)

    async def list_blacklist_users(self):
        backend = self.mongo if self.online else self.sqlite
        return await backend.list_blacklist_users()

    # ---------------- usage ----------------
    async def get_usage(self, uid):
        backend = self.mongo if self.online else self.sqlite
        return await backend.get_usage(uid)

    async def set_usage(self, uid, used=None, cooldown=None):
        if self.online:
            return await self.mongo.set_usage(uid, used, cooldown)
        result = await self.sqlite.set_usage(uid, used, cooldown)
        await self._journal("usage", "upsert", {"user_id": uid, **result})

    async def get_expired_cooldowns(self, now):
        backend = self.mongo if self.online else self.sqlite
        return await backend.get_expired_cooldowns(now)

    # ---------------- queue ----------------
    async def queue_size(self):
        backend = self.mongo if self.online else self.sqlite
        return await backend.queue_size()

    async def add_queue(self, uid, sgid, gid, cid, amount):
        if self.online:
            return await self.mongo.add_queue(uid, sgid, gid, cid, amount)
        row = await self.sqlite.add_queue(uid, sgid, gid, cid, amount)
        await self._journal("queue", "insert", {
            "key": row["key"], "user_id": uid, "source_guild_id": sgid,
            "guild_id": gid, "channel_id": cid, "amount": amount,
            "created_at": row["created_at"],
        })
        return row

    async def queue_list(self):
        backend = self.mongo if self.online else self.sqlite
        return await backend.queue_list()

    async def queue_position(self, uid):
        backend = self.mongo if self.online else self.sqlite
        return await backend.queue_position(uid)

    async def pop_queue(self):
        if self.online:
            row = await self.mongo.pop_queue()
            if row:
                await self._journal("queue", "delete", {"key": row["key"]})
            return row
        row = await self.sqlite.pop_queue()
        if row:
            await self._journal("queue", "delete", {"key": row["key"]})
        return row

    async def clear_queue(self):
        if self.online:
            return await self.mongo.clear_queue()
        await self.sqlite.clear_queue()
        await self._journal("queue", "clear", {})

    # ---------------- oauth ----------------
    async def get_oauth(self, uid):
        backend = self.mongo if self.online else self.sqlite
        return await backend.get_oauth(uid)

    async def save_oauth(self, uid, username, access, refresh, expires, authorized=True, scope=None):
        if self.online:
            return await self.mongo.save_oauth(uid, username, access, refresh, expires, authorized, scope)
        await self.sqlite.save_oauth(uid, username, access, refresh, expires, authorized, scope)
        await self._journal("oauth_users", "upsert", {
            "user_id": uid, "username": username, "access_token": access,
            "refresh_token": refresh, "expires_at": expires,
            "authorized": int(authorized), "scope": scope or "",
        })

    async def set_authorized(self, uid, state):
        if self.online:
            return await self.mongo.set_authorized(uid, state)
        await self.sqlite.set_authorized(uid, state)
        row = await self.sqlite.get_oauth(uid)
        if row:
            await self._journal("oauth_users", "upsert", dict(row))

    async def get_authorized_users(self):
        backend = self.mongo if self.online else self.sqlite
        return await backend.get_authorized_users()

    async def count_authorized(self):
        backend = self.mongo if self.online else self.sqlite
        return await backend.count_authorized()

    async def get_bad_scope_users(self):
        backend = self.mongo if self.online else self.sqlite
        return await backend.get_bad_scope_users()

    # ---------------- verified ----------------
    async def add_verified(self, gid, uid):
        if self.online:
            return await self.mongo.add_verified(gid, uid)
        await self.sqlite.add_verified(gid, uid)
        await self._journal("verified", "upsert", {"guild_id": gid, "user_id": uid})

    async def remove_verified(self, gid, uid):
        if self.online:
            return await self.mongo.remove_verified(gid, uid)
        await self.sqlite.remove_verified(gid, uid)
        await self._journal("verified", "delete", {"guild_id": gid, "user_id": uid})

    async def get_verified(self, gid=None):
        backend = self.mongo if self.online else self.sqlite
        return await backend.get_verified(gid)

    # ---------------- pulls ----------------
    async def get_pull(self, uid, gid):
        backend = self.mongo if self.online else self.sqlite
        return await backend.get_pull(uid, gid)

    async def record_pull(self, uid, gid):
        if self.online:
            return await self.mongo.record_pull(uid, gid)
        row = await self.sqlite.record_pull(uid, gid)
        await self._journal("pulls", "upsert", {
            "user_id": uid, "guild_id": gid, "count": row["count"], "last_pull": row["last_pull"],
        })
        return row

    async def reset_pull(self, uid, gid):
        if self.online:
            return await self.mongo.reset_pull(uid, gid)
        await self.sqlite.reset_pull(uid, gid)
        await self._journal("pulls", "delete", {"user_id": uid, "guild_id": gid})

    async def list_pulls(self, limit=20):
        backend = self.mongo if self.online else self.sqlite
        return await backend.list_pulls(limit)
