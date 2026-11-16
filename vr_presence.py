import logging
import os

import discord.gateway as gateway

log = logging.getLogger("venice.vr")

ENABLED = os.getenv("VR_PRESENCE", "1") != "0"

VR_PROPERTIES = {
    "$os": "android",
    "$browser": "Discord VR",
    "$device": "Discord VR",
}


def install() -> bool:
    if not ENABLED:
        log.info("VR presence disabled via VR_PRESENCE=0")
        return False

    original = gateway.DiscordWebSocket.send_as_json
    if getattr(original, "__vr_patched__", False):
        return True

    async def send_as_json(self, data):
        if isinstance(data, dict) and data.get("op") == 2:
            payload = data.get("d")
            if isinstance(payload, dict) and isinstance(payload.get("properties"), dict):
                log.debug("IDENTIFY properties before: %s", payload["properties"])
                payload["properties"] = {**payload["properties"], **VR_PROPERTIES}
                log.debug("IDENTIFY properties forced: %s", payload["properties"])
        return await original(self, data)

    send_as_json.__vr_patched__ = True
    gateway.DiscordWebSocket.send_as_json = send_as_json
    log.info("VR identify properties installed")
    return True
