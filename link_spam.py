"""Moderación de enlaces repetidos en canales distintos del mismo servidor."""
import asyncio
from contextlib import closing
import hashlib
import json
import logging
import re
import sqlite3
import time
from urllib.parse import urlsplit

import discord
from linkify_it import LinkifyIt

log = logging.getLogger("LaVenganzaRP.antispam")
WINDOW = 300
CHANNEL_LIMIT = 3
STAFF_CHANNEL = 1515887549678223380
LINKS = LinkifyIt()
INVITE_HOSTS = {"discord.com", "www.discord.com", "discordapp.com", "www.discordapp.com"}


def link_keys(content):
    """Solo guarda huellas de destinos; conserva ruta, consulta y fragmento."""
    keys = set()
    for match in LINKS.match(content) or ():
        try:
            url = urlsplit(match.url)
            if url.scheme not in ("http", "https") or not url.hostname:
                continue
            host = url.hostname.lower()
            port = url.port
        except ValueError:
            continue
        code = None
        if port is None and not url.username and not url.password:
            if host in {"discord.gg", "www.discord.gg"}:
                code = re.fullmatch(r"/([A-Za-z0-9_-]+)/?", url.path)
            elif host in INVITE_HOSTS:
                code = re.fullmatch(r"/invite/([A-Za-z0-9_-]+)/?", url.path)
        key = ("invite", code[1]) if code else ("url", host, port, url.username, url.password,
                                                 url.path or "/", url.query, url.fragment)
        keys.add(hashlib.sha256(json.dumps(key).encode()).hexdigest())
    return keys


class SpamStore:
    def __init__(self, path):
        self.path = path

    def initialize(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS spam_links (
                    author INTEGER, link TEXT, channel INTEGER, message INTEGER, posted REAL,
                    PRIMARY KEY(author,link,message));
                CREATE INDEX IF NOT EXISTS spam_links_time ON spam_links(posted);
                CREATE TABLE IF NOT EXISTS spam_cases (
                    id INTEGER PRIMARY KEY, author INTEGER NOT NULL, opened REAL NOT NULL,
                    result TEXT, notice INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS spam_case_author ON spam_cases(author,opened);
            """)

    def record(self, author, channel, message, posted, keys, now):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM spam_links WHERE posted < ?", (now - WINDOW,))
            if not keys or posted < now - WINDOW or posted > now + 5:
                return None
            db.executemany("INSERT OR IGNORE INTO spam_links VALUES (?,?,?,?,?)",
                           [(author, key, channel, message, posted) for key in keys])
            if db.execute("SELECT 1 FROM spam_cases WHERE author=? AND opened>=?", (author, now-WINDOW)).fetchone():
                return None
            rows = db.execute("""SELECT link,channel,message FROM spam_links WHERE author=? AND link IN
                (SELECT link FROM spam_links WHERE author=? GROUP BY link HAVING COUNT(DISTINCT channel)>=?)""",
                              (author, author, CHANNEL_LIMIT)).fetchall()
            if not rows:
                return None
            case = db.execute("INSERT INTO spam_cases(author,opened) VALUES (?,?)", (author, now)).lastrowid
            db.execute("DELETE FROM spam_links WHERE author=?", (author,))
            return case, sorted({(c, m) for _, c, m in rows}), {key for key, _, _ in rows}

    def save_result(self, case, result):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE spam_cases SET result=? WHERE id=?", (result, case))

    def claim_notices(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id,author,result FROM spam_cases WHERE notice=0 AND result IS NOT NULL ORDER BY id").fetchall()
            db.executemany("UPDATE spam_cases SET notice=1 WHERE id=?", [(case,) for case, _, _ in rows])
            return rows

    def interrupted(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE spam_cases SET result=? WHERE result IS NULL",
                       ("Proceso interrumpido. Revisa el registro de auditoría y los mensajes.",))


class LinkSpamGuard:
    def __init__(self, bot, path, guild_id):
        self.bot, self.guild_id = bot, guild_id
        self.store = SpamStore(path)

    async def start(self):
        await asyncio.to_thread(self.store.initialize)
        await asyncio.to_thread(self.store.interrupted)

    def staff_channel(self, guild):
        channel = guild.get_channel(STAFF_CHANNEL)
        if channel and not channel.permissions_for(guild.default_role).view_channel:
            return channel
        return None

    async def ready(self, guild):
        channel = self.staff_channel(guild)
        writable = bool(channel and channel.permissions_for(guild.me).send_messages)
        visible = [c for c in guild.text_channels if c.permissions_for(guild.me).view_channel]
        manageable = sum(c.permissions_for(guild.me).manage_messages and c.permissions_for(guild.me).read_message_history for c in visible)
        log.info("Antispam activo: ban_members=%s canales_moderables=%s/%s staff_privado=%s",
                 guild.me.guild_permissions.ban_members, manageable, len(visible), writable)
        await self.report(guild)

    async def report(self, guild):
        channel = self.staff_channel(guild)
        if not channel or not channel.permissions_for(guild.me).send_messages:
            log.error("Antispam: canal privado de moderación no disponible")
            return
        for case, author, result in await asyncio.to_thread(self.store.claim_notices):
            try:
                await channel.send(f"🛡️ **Antispam · Caso #{case}**\nCuenta: <@{author}> (`{author}`)\n{result}",
                                   allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                log.exception("Antispam: no se pudo confirmar el aviso del caso #%s: %s", case, result)

    async def observe(self, message):
        guild = message.guild
        if not guild or guild.id != self.guild_id or message.author.bot or message.webhook_id:
            return
        keys = link_keys(message.content)
        if not keys:
            return
        claim = await asyncio.to_thread(self.store.record, message.author.id, message.channel.id, message.id,
                                        message.created_at.timestamp(), keys, time.time())
        if not claim:
            return
        case, copies, matches = claim
        try:
            result = await self.enforce(guild, message.author, case, copies, matches)
        except Exception:
            log.exception("Antispam: error durante el caso #%s", case)
            result = "Acción incompleta. Revisa el registro de auditoría y los mensajes."
        await asyncio.to_thread(self.store.save_result, case, result)
        log.info("Antispam caso #%s: %s", case, result)
        await self.report(guild)

    async def enforce(self, guild, author, case, copies, keys):
        reason = f"Antispam #{case}: mismo enlace en al menos 3 canales en 5 minutos"
        try:
            await guild.ban(author, delete_message_seconds=0, reason=reason)
            ban = "Ban aplicado."
        except discord.Forbidden:
            ban = "Ban pendiente: revisa el permiso Banear miembros y la jerarquía de roles."
        except discord.HTTPException as exc:
            ban = f"Ban sin confirmar (Discord {exc.status}). Revisa el registro de auditoría."
        deleted = absent = edited = 0
        failed = []
        for channel_id, message_id in copies:
            try:
                channel = self.bot.get_partial_messageable(channel_id, guild_id=guild.id)
                current = await channel.fetch_message(message_id)
                if current.author.id != author.id or not keys.intersection(link_keys(current.content)):
                    edited += 1
                    continue
                await current.delete()
                deleted += 1
            except discord.NotFound:
                absent += 1
            except discord.HTTPException:
                failed.append(channel_id)
        channels = sorted({c for c, _ in copies})
        locations = ", ".join(f"<#{c}>" for c in channels[:12])
        result = (f"Mismo enlace en {len(channels)} canales en 5 minutos: {locations}.\n{ban}\n"
                  f"Mensajes eliminados: {deleted}/{len(copies)}. Ya ausentes: {absent}. Editados: {edited}.")
        if failed:
            result += f" Pendientes: {len(failed)} en " + ", ".join(f"<#{c}>" for c in sorted(set(failed))[:12])
        return result
