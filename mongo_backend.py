import logging
import time

from motor.motor_asyncio import AsyncIOMotorClient

log = logging.getLogger("venice.mongo")

KEYS = {
    "settings": ["key"],
    "role_limits": ["role_id"],
    "blacklist_servers": ["server_id"],
    "blacklist_users": ["user_id"],
    "usage": ["user_id"],
    "queue": ["key"],
    "verified": ["guild_id", "user_id"],
    "oauth_users": ["user_id"],
    "pulls": ["user_id", "guild_id"],
}


class MongoBackend:
    def __init__(self, uri, db_name):
        self.client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=4000)
        self.db = self.client[db_name]

    async def ping(self):
        try:
            await self.client.admin.command("ping")
            return True
        except Exception:
            return False

    async def close(self):
        self.client.close()

    async def apply_op(self, collection, op, payload):
        coll = self.db[collection]
        if op == "clear":
            await coll.delete_many({})
            return
        key = {k: payload[k] for k in KEYS[collection]}
        if op == "delete":
            await coll.delete_one(key)
        elif op == "insert":
            await coll.update_one(key, {"$setOnInsert": payload}, upsert=True)
        else:
            await coll.update_one(key, {"$set": payload}, upsert=True)

    # ---------------- settings ----------------
    async def get_setting(self, key, default=None):
        row = await self.db.settings.find_one({"key": key})
        return row["value"] if row else default

    async def set_setting(self, key, value):
        await self.db.settings.update_one({"key": key}, {"$set": {"value": str(value)}}, upsert=True)

    # ---------------- role limits ----------------
    async def get_role_limits(self):
        return {r["role_id"]: r["amount"] async for r in self.db.role_limits.find({})}

    async def set_role_limit(self, role_id, amount):
        await self.db.role_limits.update_one(
            {"role_id": role_id}, {"$set": {"amount": amount}}, upsert=True
        )

    async def remove_role_limit(self, role_id):
        await self.db.role_limits.delete_one({"role_id": role_id})

    # ---------------- blacklists ----------------
    async def add_blacklist_server(self, sid):
        await self.db.blacklist_servers.update_one(
            {"server_id": sid}, {"$setOnInsert": {"server_id": sid}}, upsert=True
        )

    async def remove_blacklist_server(self, sid):
        await self.db.blacklist_servers.delete_one({"server_id": sid})

    async def is_server_blacklisted(self, sid):
        return await self.db.blacklist_servers.find_one({"server_id": sid}) is not None

    async def list_blacklist_servers(self):
        return [r["server_id"] async for r in self.db.blacklist_servers.find({}).sort("server_id", 1)]

    async def add_blacklist_user(self, uid):
        await self.db.blacklist_users.update_one(
            {"user_id": uid}, {"$setOnInsert": {"user_id": uid}}, upsert=True
        )

    async def remove_blacklist_user(self, uid):
        await self.db.blacklist_users.delete_one({"user_id": uid})

    async def is_user_blacklisted(self, uid):
        return await self.db.blacklist_users.find_one({"user_id": uid}) is not None

    async def list_blacklist_users(self):
        return [r["user_id"] async for r in self.db.blacklist_users.find({}).sort("user_id", 1)]

    # ---------------- usage ----------------
    async def get_usage(self, uid):
        row = await self.db.usage.find_one({"user_id": uid})
        if row is None:
            await self.db.usage.update_one(
                {"user_id": uid}, {"$setOnInsert": {"used": 0, "cooldown": 0}}, upsert=True
            )
            return {"used": 0, "cooldown": 0}
        return {"used": row.get("used", 0), "cooldown": row.get("cooldown", 0)}

    async def set_usage(self, uid, used=None, cooldown=None):
        current = await self.get_usage(uid)
        used = current["used"] if used is None else used
        cooldown = current["cooldown"] if cooldown is None else cooldown
        await self.db.usage.update_one(
            {"user_id": uid}, {"$set": {"used": used, "cooldown": cooldown}}, upsert=True
        )
        return {"used": used, "cooldown": cooldown}

    async def get_expired_cooldowns(self, now):
        cursor = self.db.usage.find({"cooldown": {"$gt": 0, "$lte": now}, "used": {"$gt": 0}})
        return [r["user_id"] async for r in cursor]

    # ---------------- queue ----------------
    async def queue_size(self):
        return await self.db.queue.count_documents({})

    async def add_queue(self, uid, sgid, gid, cid, amount):
        import uuid
        doc = {
            "key": uuid.uuid4().hex, "user_id": uid, "source_guild_id": sgid,
            "guild_id": gid, "channel_id": cid, "amount": amount, "created_at": int(time.time()),
        }
        await self.db.queue.insert_one(dict(doc))
        return doc

    async def queue_list(self):
        return [r async for r in self.db.queue.find({}).sort([("created_at", 1), ("_id", 1)])]

    async def queue_position(self, uid):
        for i, row in enumerate(await self.queue_list(), start=1):
            if row["user_id"] == uid:
                return i
        return 0

    async def pop_queue(self):
        return await self.db.queue.find_one_and_delete({}, sort=[("created_at", 1), ("_id", 1)])

    async def clear_queue(self):
        await self.db.queue.delete_many({})

    # ---------------- oauth ----------------
    async def save_oauth(self, uid, username, access, refresh, expires, authorized=True, scope=None):
        existing = await self.get_oauth(uid)
        doc = {
            "user_id": uid,
            "username": username or (existing["username"] if existing else None),
            "access_token": access, "refresh_token": refresh, "expires_at": expires,
            "authorized": int(authorized),
            "scope": existing.get("scope", "") if scope is None and existing else (scope or ""),
        }
        await self.db.oauth_users.update_one({"user_id": uid}, {"$set": doc}, upsert=True)

    async def get_oauth(self, uid):
        return await self.db.oauth_users.find_one({"user_id": uid})

    async def set_authorized(self, uid, state):
        await self.db.oauth_users.update_one({"user_id": uid}, {"$set": {"authorized": int(state)}})

    async def get_authorized_users(self):
        cursor = self.db.oauth_users.find({"authorized": 1}).sort("created_at", 1)
        return [r["user_id"] async for r in cursor]

    async def count_authorized(self):
        return await self.db.oauth_users.count_documents({"authorized": 1})

    async def get_bad_scope_users(self):
        cursor = self.db.oauth_users.find(
            {"authorized": 1, "scope": {"$not": {"$regex": "guilds\\.join"}}}
        )
        return [r async for r in cursor]

    # ---------------- verified ----------------
    async def add_verified(self, gid, uid):
        await self.db.verified.update_one(
            {"guild_id": gid, "user_id": uid},
            {"$set": {"verified_at": int(time.time())}}, upsert=True,
        )

    async def remove_verified(self, gid, uid):
        await self.db.verified.delete_one({"guild_id": gid, "user_id": uid})

    async def get_verified(self, gid=None):
        query = {} if gid is None else {"guild_id": gid}
        return [r async for r in self.db.verified.find(query)]

    # ---------------- pulls ----------------
    async def record_pull(self, uid, gid):
        now = int(time.time())
        await self.db.pulls.update_one(
            {"user_id": uid, "guild_id": gid},
            {"$inc": {"count": 1}, "$set": {"last_pull": now}}, upsert=True,
        )
        return await self.get_pull(uid, gid)

    async def get_pull(self, uid, gid):
        return await self.db.pulls.find_one({"user_id": uid, "guild_id": gid})

    async def reset_pull(self, uid, gid):
        await self.db.pulls.delete_one({"user_id": uid, "guild_id": gid})

    async def list_pulls(self, limit=20):
        return [r async for r in self.db.pulls.find({}).sort("last_pull", -1).limit(limit)]
