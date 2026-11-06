"""Un mensaje editable por evento/reunión, con su ID persistente y sin pings."""
import asyncio
import logging
import sqlite3
import time
from contextlib import closing
from weakref import WeakValueDictionary

import discord

log = logging.getLogger("LaVenganzaRP.listas")
SUMMARY_SCHEMA = """CREATE TABLE IF NOT EXISTS public_summaries (
    kind TEXT NOT NULL, entity_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
    message_id INTEGER, state TEXT NOT NULL DEFAULT 'empty',
    PRIMARY KEY(kind,entity_id)
);"""


class SummaryMessages:
    def __init__(self, bot, path):
        self.bot, self.path = bot, path
        self.locks = WeakValueDictionary()
        self.countdowns = {}

    def message_lock(self, key):
        return self.locks.setdefault(key, asyncio.Lock())

    def stop_countdown(self, key):
        task = self.countdowns.pop(key, None)
        if task:
            task.cancel()

    def start_countdown(self, key, message, embed, start, rendered_at):
        self.stop_countdown(key)
        if start is not None and start > rendered_at:
            self.countdowns[key] = asyncio.create_task(self.tick(key, message, embed, start))

    async def tick(self, key, message, embed, start):
        delay = 1
        try:
            while True:
                await asyncio.sleep(delay)
                await self.bot.wait_until_ready()
                async with self.message_lock(key):
                    now = int(time.time())
                    try:
                        await message.edit(embed=with_countdown(embed, key[0], start, now),
                                           allowed_mentions=discord.AllowedMentions.none())
                    except (discord.NotFound, discord.Forbidden):
                        return
                    except (discord.HTTPException, OSError):
                        log.warning("No se pudo refrescar el reloj de %s #%s", *key)
                        delay = min(max(delay, 1) * 2, 60)
                        continue
                    if now >= start:
                        return
                    delay = 1 - time.time() % 1
        finally:
            if self.countdowns.get(key) is asyncio.current_task():
                self.countdowns.pop(key)

    def transaction(self, action, kind, entity_id, channel_id=None, message_id=None):
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            if action == "get":
                db.execute("INSERT OR IGNORE INTO public_summaries(kind,entity_id,channel_id) VALUES (?,?,?)", (kind, entity_id, channel_id))
                return dict(db.execute("SELECT * FROM public_summaries WHERE kind=? AND entity_id=?", (kind, entity_id)).fetchone())
            if action == "reserve":
                result = db.execute("UPDATE public_summaries SET state='pending',message_id=NULL WHERE kind=? AND entity_id=? AND (state='empty' OR message_id=?)", (kind, entity_id, message_id))
                if result.rowcount != 1:
                    raise RuntimeError("La lista tiene una publicación pendiente. Revisa los logs antes de reenviarla.")
            elif action == "saved":
                db.execute("UPDATE public_summaries SET state='published',message_id=? WHERE kind=? AND entity_id=?", (message_id, kind, entity_id))
            elif action == "retry":
                db.execute("UPDATE public_summaries SET state='empty' WHERE kind=? AND entity_id=? AND state='pending'", (kind, entity_id))
            elif action == "removed":
                db.execute("UPDATE public_summaries SET state='removed' WHERE kind=? AND entity_id=?", (kind, entity_id))

    async def db(self, *args, **kwargs):
        return await asyncio.to_thread(self.transaction, *args, **kwargs)

    async def update(self, kind, entity_id, channel_id, embed, starts_at=None):
        key = (kind, entity_id)
        async with self.message_lock(key):
            if starts_at is None:
                self.stop_countdown(key)
            row = await self.db("get", kind, entity_id, channel_id)
            if row["state"] == "removed":
                return
            if row["channel_id"] != channel_id:
                raise RuntimeError("El canal de la lista no coincide con el anuncio.")
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            rendered_at = int(time.time())
            displayed = with_countdown(embed, kind, starts_at, rendered_at)
            if row["message_id"]:
                try:
                    message = await channel.fetch_message(row["message_id"])
                    await message.edit(embed=displayed, allowed_mentions=discord.AllowedMentions.none())
                    self.start_countdown(key, message, embed, starts_at, rendered_at)
                    return
                except discord.NotFound:
                    # Se eliminó la lista: se repone una vez, sin tocar el anuncio.
                    pass
            await self.db("reserve", kind, entity_id, message_id=row["message_id"])
            try:
                message = await channel.send(embed=displayed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException as exc:
                # Solo reintentar rechazos inequívocos; un 5xx/timeout puede haber entregado el mensaje.
                if exc.status in (400, 403, 404):
                    await self.db("retry", kind, entity_id)
                raise
            await self.db("saved", kind, entity_id, message_id=message.id)
            self.start_countdown(key, message, embed, starts_at, rendered_at)

    async def remove(self, kind, entity_id, channel_id):
        key = (kind, entity_id)
        async with self.message_lock(key):
            self.stop_countdown(key)
            row = await self.db("get", kind, entity_id, channel_id)
            if row["state"] == "pending":
                raise RuntimeError("La lista tiene una entrega pendiente de revisar antes de eliminarla.")
            if row["state"] == "removed":
                return
            if row["message_id"]:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                try:
                    message = await channel.fetch_message(row["message_id"])
                    await message.delete()
                except discord.NotFound:
                    pass
            await self.db("removed", kind, entity_id)


def with_countdown(embed, kind, start, now):
    if start is None:
        return embed
    remaining = max(0, start - now)
    hours, rest = divmod(remaining, 3600)
    minutes, seconds = divmod(rest, 60)
    clock = f"**{hours:02d} h · {minutes:02d} min · {seconds:02d} s**" if remaining else "**Ya comenzó**"
    title = "Inicio del evento" if kind == "event" else "Inicio de la reunión"
    data = embed.to_dict()
    data["fields"] = [*data.get("fields", []), {"name": f"⏰ {title}", "value": f"<t:{start}:F>\n{clock}", "inline": False}]
    return discord.Embed.from_dict(data)


def mention_list(user_ids, limit=1000, numbered=False):
    """No corta menciones; reserva espacio para indicar cuántos quedan fuera."""
    ids = list(user_ids)
    lines = []
    used = 0
    for index, user_id in enumerate(ids, 1):
        line = f"{index}. <@{int(user_id)}>" if numbered else f"<@{int(user_id)}>"
        if used + len(line) + 1 > limit - 85:
            break
        lines.append(line)
        used += len(line) + 1
    remaining = len(ids) - len(lines)
    if remaining:
        lines.append(f"… y {remaining} más. Consulta la lista completa con el comando indicado abajo.")
    return "\n".join(lines) or "Todavía nadie."


def event_summary(event, users):
    status = {"open": "🟢 Inscripciones abiertas", "finished": "🏆 Evento finalizado", "closed": "🔒 Evento cerrado"}.get(event["status"], "Inscripciones cerradas")
    title = discord.utils.escape_markdown(str(event["title"])).replace("@", "@\u200b")
    embed = discord.Embed(title=f"📋 INSCRITOS — {title}", description=f"👥 **{len(users)}/{event['capacity']} participantes**\n{status}\n\n" + mention_list(users, limit=3400, numbered=True), color=0xD60000)
    embed.set_footer(text=f"LA VENGANZA RP | Evento #{event['id']} | Lista completa: Participantes o /evento participantes")
    return embed


def meeting_summary(meeting, responses):
    status = {"scheduled": "🟢 Confirmaciones abiertas", "cancelled": "🔒 Reunión cancelada", "finished": "✅ Reunión finalizada"}.get(meeting["status"], "Preparando reunión")
    title = discord.utils.escape_markdown(str(meeting["title"])).replace("@", "@\u200b")
    embed = discord.Embed(title=f"📋 CONFIRMACIONES — {title}", description=status, color=0xD60000)
    for key, label in (("yes", "✅ Asistirán"), ("no", "❌ No asistirán"), ("maybe", "❔ Tal vez")):
        users = [row["user_id"] for row in responses if row["response"] == key]
        embed.add_field(name=f"{label} · {len(users)}", value=mention_list(users), inline=False)
    embed.set_footer(text=f"LA VENGANZA RP | Reunión #{meeting['id']} | Confirmaciones, no asistencia real | Lista completa: /reunion asistencia")
    return embed
