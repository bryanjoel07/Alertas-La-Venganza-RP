"""Edición del estado en el mensaje original de txAdmin, si su autor está conectado."""
from datetime import datetime, timezone
from copy import deepcopy
import logging

import aiohttp

AUTHOR_ID = 1310673597051699352
log = logging.getLogger("LaVenganzaRP.salud")


def status_change(message, state, max_age):
    if message.author.id != AUTHOR_ID or state not in ("up", "down"):
        return None
    embeds = [deepcopy(e.to_dict()) for e in message.embeds]
    for original, embed in zip(message.embeds, embeds):
        # The producer's heartbeat must stay unchanged, including after our own edit.
        if not original.timestamp or (datetime.now(timezone.utc) - original.timestamp).total_seconds() <= max_age:
            continue
        for field in embed.get("fields", []):
            if field["name"].strip("> ").casefold() not in ("status", "estado"):
                continue
            value = "```\n" + ("🟢 Online" if state == "up" else "🔴 Offline") + "\n```"
            if field["value"] == value:
                return None
            field["value"] = value
            return embeds
    return None


class OriginalPanel:
    def __init__(self, token, channel_id, message_id):
        self.token = token
        self.author_verified = False
        self.url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}"

    async def update(self, message, state, max_age):
        changes = status_change(message, state, max_age) if self.token and message else None
        if changes is None:
            return
        headers = {"Authorization": f"Bot {self.token}"}
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as http:
            if not self.author_verified:
                async with http.get("https://discord.com/api/v10/users/@me",allow_redirects=False) as response:
                    if response.status == 401 or (response.status == 200 and int((await response.json())["id"]) != AUTHOR_ID):
                        self.token = None
                        log.warning("La credencial configurada no pertenece al autor del panel de Connect.")
                        return
                    response.raise_for_status()
                    self.author_verified = True
            async with http.patch(self.url,json={"embeds":changes},allow_redirects=False) as response:
                if response.status in (401,403,404):
                    self.token = None
                    log.warning("Discord no permite editar el panel original (HTTP %s).",response.status)
                    return
                response.raise_for_status()
                log.info("Estado del panel original actualizado: %s",state)
