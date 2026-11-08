"""Discord resources for La Venganza Exclusive. The SQLite inventory owns the entitlements."""

import asyncio
import json
import logging
import time

import discord

from economy_store import outfit_for
from meetings import ROLES

log = logging.getLogger("LaVenganzaRP.economia")
ROLE_KINDS = {"color", "custom_color", "title", "bundle"}
LABELS = {
    "insignia": "Insignia",
    "titulo": "Título",
    "tema": "Tema",
    "color": "Color",
    "prefijo": "Prefijo",
    "frase": "Frase",
    "victoria": "Celebración",
    "trofeo": "Trofeo destacado",
}


class Delivery:
    def __init__(self, store):
        self.store = store
        self.lock = asyncio.Lock()

    def category(self, guild, voice=False):
        category_id = (
            self.store.config("voice_category") if voice else ""
        ) or self.store.config("category")
        category = guild.get_channel(int(category_id))
        if not isinstance(category, discord.CategoryChannel):
            raise ValueError("No encuentro la categoría configurada en este servidor.")
        return category

    def preflight(self, member, kind):
        guild = member.guild
        me = guild.me
        if kind in ROLE_KINDS:
            if (
                not me.guild_permissions.manage_roles
                or member.top_role >= me.top_role
                or guild.owner_id == member.id
            ):
                raise ValueError(
                    "La jerarquía o los permisos actuales del bot impiden entregar el rol a este jugador."
                )
            if kind != "title":
                blocking = [
                    r
                    for r in member.roles
                    if r.color.value and (r >= me.top_role or r.id in ROLES)
                ]
                if blocking:
                    raise ValueError(
                        "El color de un rol superior o de Staff tiene prioridad sobre este cosmético."
                    )
        if kind == "nickname" and (
            not me.guild_permissions.manage_nicknames
            or member.top_role >= me.top_role
            or member.id == guild.owner_id
        ):
            raise ValueError(
                "El bot no puede cambiar el apodo de este miembro por permisos o jerarquía."
            )
        if kind == "voice":
            category = self.category(guild, True)
            perms = category.permissions_for(me)
            if not (
                perms.manage_channels
                and perms.manage_roles
                and perms.view_channel
                and perms.connect
            ):
                raise ValueError(
                    "El bot necesita ver, conectar y gestionar canales y permisos en la categoría de voz."
                )

    async def role(self, guild, slot, value):
        color = int(value, 16) if slot == "color" else 0
        key = f"role:{slot}:{value}"
        item = self.store.resource(key)
        role = (
            guild.get_role(item["resource_id"])
            if item and item["resource_id"]
            else None
        )
        if role and (
            role.permissions.value
            or role.managed
            or role >= guild.me.top_role
            or role.mentionable
            or role.color.value != color
        ):
            raise ValueError(
                "El rol cosmético tiene cambios de permisos, color o jerarquía que Staff debe revisar."
            )
        if role is None:
            name = f"LV · {value}"
            # First persist the intent. A role created before an interrupted response is discoverable by name.
            existing = [r for r in await guild.fetch_roles() if r.name == name]
            if existing:
                if (
                    not item
                    or len(existing) != 1
                    or item["state"] != "creating"
                    and existing[0].id != item["resource_id"]
                    or existing[0] >= guild.me.top_role
                    or existing[0].permissions.value
                    or existing[0].managed
                    or existing[0].mentionable
                    or existing[0].color.value != color
                ):
                    raise ValueError(
                        "Hay un rol con el nombre reservado. Staff debe revisar el conflicto."
                    )
                role = existing[0]
            else:
                self.store.resource(key, None, "creating")
                role = await guild.create_role(
                    name=name,
                    permissions=discord.Permissions.none(),
                    color=discord.Color(color),
                    reason="La Venganza Exclusive",
                )
            self.store.resource(key, role.id, "ready")
        if any(
            channel.overwrites_for(role).pair()[0].value for channel in guild.channels
        ):
            raise ValueError(
                "Un canal concede acceso adicional al rol cosmético. Staff debe revisar sus permisos."
            )
        if slot == "color" and role.position < guild.me.top_role.position - 1:
            await role.edit(
                position=guild.me.top_role.position - 1,
                reason="Mostrar color cosmético",
            )
        return role

    def equip(self, member, key, value):
        p = self.store.purchase(key, member.id)
        self.preflight(member, p["kind"])
        self.store.set_outfit(member.id, p["id"], outfit_for(p, value))

    async def sync_member(self, member):
        equipped = {r["slot"]: r for r in self.store.equipped(member.id)}
        wanted = set()
        managed = {
            r["resource_id"]
            for r in self.store.rows(
                "SELECT resource_id FROM eco_resources WHERE key LIKE 'role:%' AND state='ready'"
            )
        }
        for slot in ("color", "titulo"):
            row = equipped.get(slot)
            if row:
                self.preflight(member, "color" if slot == "color" else "title")
                role = await self.role(member.guild, slot, row["value"])
                wanted.add(role.id)
                if role not in member.roles:
                    await member.add_roles(role, reason="Cosmético equipado")
        for role in member.roles:
            if role.id in managed - wanted:
                if role.permissions.value or role.managed:
                    raise ValueError("Staff debe revisar un rol cosmético modificado.")
                await member.remove_roles(role, reason="Cosmético retirado")
        nick = equipped.get("prefijo")
        key = f"nick:{member.id}"
        state = self.store.config(key)
        if nick:
            self.preflight(member, "nickname")
            original = json.loads(state)["original"] if state else member.nick
            target = f"{nick['value']} {original or member.name}"[:32]
            self.store.runtime_config(
                key, json.dumps({"original": original, "target": target})
            )
            if member.nick != target:
                await member.edit(nick=target, reason="Prefijo cosmético")
        elif state:
            saved = json.loads(state)
            if member.nick == saved["target"]:
                await member.edit(
                    nick=saved["original"], reason="Retirar prefijo cosmético"
                )
            self.store.runtime_config(key, "")
        self.store.rows("DELETE FROM eco_sync WHERE user_id=?", (member.id,))

    async def voice(self, guild, p):
        marker = "exclusive-" + p["id"]
        if p["status"] == "pending":
            category = self.category(guild, True)
            channels = await guild.fetch_channels()
            room = next(
                (
                    c
                    for c in channels
                    if isinstance(c, discord.VoiceChannel) and c.name == marker
                ),
                None,
            )
            owner = await guild.fetch_member(p["recipient"])
            self.preflight(owner, "voice")
            if room is None:
                access = {
                    guild.default_role: discord.PermissionOverwrite(
                        view_channel=False, connect=False
                    ),
                    guild.me: discord.PermissionOverwrite(
                        view_channel=True,
                        manage_channels=True,
                        manage_roles=True,
                        connect=True,
                    ),
                    owner: discord.PermissionOverwrite(
                        view_channel=True, connect=True, speak=True
                    ),
                }
                for role in guild.roles:
                    if role.id in ROLES:
                        access[role] = discord.PermissionOverwrite(
                            view_channel=True, connect=True, speak=True
                        )
                room = await guild.create_voice_channel(
                    marker,
                    category=category,
                    overwrites=access,
                    reason="Sala Exclusive " + p["id"],
                )
            self.store.delivery(p["id"], room.id)
            await room.edit(name="Sala de " + owner.display_name[:70])
            return
        room = guild.get_channel(p["resource_id"]) if p["resource_id"] else None
        if p["status"] == "refunded" and not p["resource_id"]:
            room = next(
                (
                    c
                    for c in await guild.fetch_channels()
                    if isinstance(c, discord.VoiceChannel) and c.name == marker
                ),
                None,
            )
            if room:
                self.store.rows(
                    "UPDATE eco_purchases SET resource_id=? WHERE id=?",
                    (room.id, p["id"]),
                )
        if room is None and p["resource_id"]:
            try:
                room = await guild.fetch_channel(p["resource_id"])
            except discord.NotFound:
                pass
        if room:
            if not isinstance(room, discord.VoiceChannel) or room.guild.id != guild.id:
                raise ValueError("Canal de voz inesperado.")
            if p["delivery_state"] != "closing":
                await room.edit(
                    overwrites={
                        guild.default_role: discord.PermissionOverwrite(
                            view_channel=False, connect=False
                        ),
                        guild.me: discord.PermissionOverwrite(
                            view_channel=True, connect=True, manage_channels=True
                        ),
                        **{
                            r: discord.PermissionOverwrite(
                                view_channel=True, connect=True
                            )
                            for r in guild.roles
                            if r.id in ROLES
                        },
                    },
                    reason="Vencimiento o devolución de sala",
                )
                self.store.rows(
                    "UPDATE eco_purchases SET delivery_state='closing' WHERE id=?",
                    (p["id"],),
                )
                try:
                    owner = await guild.fetch_member(p["recipient"])
                    await owner.send(
                        "Terminó tu sala de voz Exclusive. Se eliminará cuando quede vacía."
                    )
                except discord.HTTPException:
                    pass
            if room.voice_states:
                return
            await room.delete(reason="Sala Exclusive vacía al vencer")
        self.store.rows(
            "UPDATE eco_purchases SET delivery_state='closed',status=CASE WHEN status='refunded' THEN status ELSE 'expired' END WHERE id=?",
            (p["id"],),
        )

    async def recover(self, guild):
        async with self.lock:
            for p in self.store.rows(
                """SELECT * FROM eco_purchases WHERE kind='voice' AND delivery_state!='closed'
                    AND (status IN ('pending','refunded') OR expires<=?)""",
                (int(time.time()),),
            ):
                try:
                    await self.voice(guild, p)
                except (ValueError, discord.HTTPException) as exc:
                    log.warning("Entrega de sala %s pendiente: %s", p["id"], exc)
            for r in self.store.rows("SELECT user_id FROM eco_sync"):
                try:
                    await self.sync_member(await guild.fetch_member(r["user_id"]))
                except (ValueError, discord.HTTPException) as exc:
                    log.warning(
                        "Entrega de cosméticos para %s pendiente: %s", r["user_id"], exc
                    )
