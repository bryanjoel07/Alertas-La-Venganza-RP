import asyncio
import hashlib
import logging
import re
import time
import unicodedata
from datetime import datetime, timezone

import discord
from discord.ext import tasks

from stream_proof import live_target, public_link
from streamers import inspect_stream

CHANNEL = 1513653533340073994
log = logging.getLogger(__name__)
APPROVED = """SELECT r.id,r.member,p.owner,p.saved_url FROM streamer_requests r
JOIN streamer_profiles p ON p.request_id=r.id AND p.owner=r.owner
WHERE r.guild=? AND r.state IN ('verificada','entregada','manual') AND p.saved_url=p.verified_url"""


def matches(profile, live):
    if not live or not re.search(r"(?<!\w)la\s+venganza\s+rp(?!\w)",
                                 unicodedata.normalize("NFKC", live["title"]), re.I):
        return False
    url = public_link(profile["saved_url"])
    return profile["owner"] in (live["owner"], "perfil:" + url.hostname.removeprefix("www.") + url.path.rstrip("/"))


class LiveAlerts:
    def __init__(self, client, streamers, guild, probe=inspect_stream):
        self.client, self.streamers, self.guild, self.probe = client, streamers, guild, probe
        self.slots = asyncio.Semaphore(2)
        self.last_status = None

    def init_db(self):
        with self.streamers.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS streamer_live_alerts(
                platform TEXT, session TEXT, first_attempt INTEGER NOT NULL, message INTEGER,
                PRIMARY KEY(platform,session))""")

    def start(self):
        if self.poll.is_running():return
        self.init_db()
        self.poll.start()

    async def check(self, channel, p):
        if not live_target(p["saved_url"]):
            return
        async with self.slots:
            live = await self.probe(p["saved_url"], live=True)
        if not matches(p, live):
            return
        key = (live["platform"], live["session"])
        footer = f"LA VENGANZA RP | {key[0]} · Directo {key[1]}"
        with self.streamers.db() as db:
            row = db.execute("SELECT * FROM streamer_live_alerts WHERE platform=? AND session=?", key).fetchone()
        if row and row["message"]:
            return
        try:
            await channel.guild.fetch_member(p["member"])
        except discord.NotFound:
            return
        with self.streamers.db() as db:
            if not db.execute(APPROVED + " AND r.id=? AND p.saved_url=? AND p.owner=?",
                              (self.guild,p["id"],p["saved_url"],p["owner"])).fetchone():
                return
            inserted = db.execute("INSERT OR IGNORE INTO streamer_live_alerts VALUES (?,?,?,NULL)",
                                  (*key,int(time.time()))).rowcount
            row = db.execute("SELECT * FROM streamer_live_alerts WHERE platform=? AND session=?", key).fetchone()
        if row["message"]:
            return
        msg = None
        if not inserted:
            after = datetime.fromtimestamp(row["first_attempt"] - 10, timezone.utc)
            async for candidate in channel.history(limit=None, after=after):
                if candidate.author.id == self.client.user.id and any(e.footer.text == footer for e in candidate.embeds):
                    msg = candidate
                    break
        if msg is None:
            title = discord.utils.escape_markdown(live["title"][:250])
            embed = discord.Embed(title="🔴 EN DIRECTO | LA VENGANZA RP", colour=0xD60000,
                                  description=f"📺 <@{p['member']}> inició un directo en **{key[0]}**.\n🎬 {title}")
            embed.set_footer(text=footer)
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label="Ver directo", emoji="📺", url=live["link"]))
            nonce = int.from_bytes(hashlib.blake2b(footer.encode(), digest_size=8).digest(), "big") >> 1
            msg = await channel.send(embed=embed, view=view, nonce=nonce, allowed_mentions=discord.AllowedMentions.none())
        with self.streamers.db() as db:
            db.execute("UPDATE streamer_live_alerts SET message=? WHERE platform=? AND session=?", (msg.id,*key))

    @tasks.loop(minutes=2)
    async def poll(self):
        try:
            channel = self.client.get_channel(CHANNEL)
            perms = channel.permissions_for(channel.guild.me) if channel and channel.guild.id == self.guild else None
            ready = bool(perms and perms.view_channel and perms.send_messages and perms.embed_links and perms.read_message_history)
            with self.streamers.db() as db:
                profiles = db.execute(APPROVED, (self.guild,)).fetchall()
            status = (ready, len(profiles))
            if status != self.last_status:
                log.info("Monitor de directos: canal=%s permisos=%s perfiles registrados=%s", CHANNEL, *status)
                self.last_status = status
            if ready:
                results = await asyncio.gather(*(self.check(channel, p) for p in profiles), return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        log.warning("Aviso de directo pendiente: %s", type(result).__name__)
        except Exception:
            log.exception("No se pudo comprobar el canal de directos")

    @poll.before_loop
    async def before(self):
        await self.client.wait_until_ready()
