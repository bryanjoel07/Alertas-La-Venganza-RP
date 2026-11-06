"""Encuestas de disponibilidad en el canal de reunión. Cada papeleta sustituye a la anterior."""
import asyncio
from datetime import datetime
import logging
import time

import discord

from meetings import CHANNELS, PR, escaped, meeting_error

log = logging.getLogger("LaVenganzaRP.encuestas")
SLOTS = (1, 2, 3)


def winners(poll, now):
    eligible = [i for i in SLOTS if poll[f"slot{i}"] > now and poll["counts"][i] > 0]
    best = max((poll["counts"][i] for i in eligible), default=0)
    return [i for i in eligible if poll["counts"][i] == best]


def poll_embed(poll):
    now = int(time.time())
    embed = discord.Embed(title=f"🗳️ {escaped(poll['title'])}",
                          description="Marca todos los horarios que te sirven. Puedes cambiar tu selección.",
                          color=0xD60000)
    leaders = winners(poll, now)
    for i in SLOTS:
        start, count = poll[f"slot{i}"], poll["counts"][i]
        marker = " · Más votado" if i in leaders else ""
        if start <= now:
            marker = " · Horario pasado"
        people = "persona disponible" if count == 1 else "personas disponibles"
        embed.add_field(name=f"Horario {i}{marker}", value=f"<t:{start}:F>\n**{count}** {people}", inline=False)
    embed.set_footer(text="Horas en tu zona local · El staff elige entre los horarios empatados.")
    return embed


class MeetingPolls:
    def __init__(self, system):
        self.system = system
        self.store = system.store

    def initialize(self):
        with self.store.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS meeting_polls (
                message_id INTEGER PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
                slot1 INTEGER NOT NULL, slot2 INTEGER NOT NULL, slot3 INTEGER NOT NULL,
                location TEXT NOT NULL, agenda TEXT NOT NULL, description TEXT NOT NULL,
                meeting_id INTEGER UNIQUE REFERENCES meetings(id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS meeting_poll_votes (
                message_id INTEGER NOT NULL REFERENCES meeting_polls(message_id),
                user_id INTEGER NOT NULL, slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 3),
                PRIMARY KEY(message_id,user_id,slot))""")

    async def start(self):
        await asyncio.to_thread(self.initialize)
        self.system.bot.add_view(PollView(self))

    @staticmethod
    def parse(raw):
        try:
            slots = [int(datetime.strptime(s.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=PR).timestamp())
                     for s in raw.strip().splitlines()]
        except ValueError:
            raise ValueError("Usa AAAA-MM-DD HH:MM para cada horario, en hora de Puerto Rico.") from None
        if len(slots) != 3 or len(set(slots)) != 3 or min(slots) <= time.time():
            raise ValueError("Escribe tres horarios futuros distintos, uno por línea.")
        return slots

    def save(self, message_id, poll):
        with self.store.db() as db:
            db.execute("""INSERT INTO meeting_polls(message_id,kind,title,slot1,slot2,slot3,location,agenda,description)
                          VALUES (:message_id,:kind,:title,:slot1,:slot2,:slot3,:location,:agenda,:description)""",
                       dict(poll, message_id=message_id))

    async def publish(self, interaction, channel, kind, title, slots, location, agenda, description):
        if not all((title, agenda, description)):
            raise ValueError("Completa el nombre, la agenda y la descripción.")
        poll = dict(kind=kind, title=title, slot1=slots[0], slot2=slots[1], slot3=slots[2],
                    location=location, agenda=agenda, description=description, counts=dict.fromkeys(SLOTS, 0))
        async with self.system.lock:
            message = await channel.send(embed=poll_embed(poll), view=PollView(self), allowed_mentions=discord.AllowedMentions.none())
            try:
                await asyncio.to_thread(self.save, message.id, poll)
            except Exception:
                await message.delete()
                raise
        await interaction.followup.send(f"🗳️ Encuesta publicada: {message.jump_url}", ephemeral=True)

    @staticmethod
    def read(db, message_id, channel_id):
        row = db.execute("SELECT * FROM meeting_polls WHERE message_id=?", (message_id,)).fetchone()
        if not row or CHANNELS[row["kind"]] != channel_id:
            raise ValueError("Encuesta no encontrada en este canal.")
        poll = dict(row)
        counts = dict.fromkeys(SLOTS, 0)
        counts.update(db.execute("SELECT slot,COUNT(*) FROM meeting_poll_votes WHERE message_id=? GROUP BY slot", (message_id,)))
        poll["counts"] = counts
        return poll

    def vote(self, message_id, channel_id, user_id, choices):
        with self.store.db() as db:
            poll = self.read(db, message_id, channel_id)
            if poll["meeting_id"]:
                raise ValueError("La reunión ya fue creada. La votación está cerrada.")
            if any(i not in SLOTS or poll[f"slot{i}"] <= time.time() for i in choices):
                raise ValueError("Elige horarios que todavía no hayan pasado.")
            db.execute("DELETE FROM meeting_poll_votes WHERE message_id=? AND user_id=?", (message_id, user_id))
            db.executemany("INSERT INTO meeting_poll_votes VALUES (?,?,?)", [(message_id, user_id, i) for i in set(choices)])
            return self.read(db, message_id, channel_id)

    def choose(self, message_id, channel_id, author, choice=None):
        # La decisión y la reunión comparten transacción. Reutilizar el mensaje hace idempotente la publicación.
        with self.store.db() as db:
            poll = self.read(db, message_id, channel_id)
            if poll["meeting_id"]:
                return poll["meeting_id"], []
            now = int(time.time())
            leaders = winners(poll, now)
            if not leaders:
                raise ValueError("Hace falta al menos un voto por un horario futuro.")
            if choice is None and len(leaders) > 1:
                return None, [(i, poll[f"slot{i}"]) for i in leaders]
            selected = leaders[0] if choice is None else choice
            if selected not in leaders:
                raise ValueError("Los votos cambiaron. Vuelve a pulsar «Crear reunión».")
            values = (poll["title"], poll[f"slot{selected}"], poll["location"], poll["agenda"], poll["description"])
            meeting_id = self.store.insert(db, values, author, poll["kind"], now)
            db.execute("UPDATE meetings SET status='scheduled',message_id=? WHERE id=?", (message_id, meeting_id))
            db.execute("UPDATE meeting_polls SET meeting_id=? WHERE message_id=?", (meeting_id, message_id))
            return meeting_id, []

    async def finish(self, interaction, message_id, choice=None):
        await interaction.response.defer(ephemeral=True)
        await self.system.channel_access(interaction, interaction.channel_id, admin=True)
        async with self.system.lock:
            key, ties = await asyncio.to_thread(self.choose, message_id, interaction.channel_id, interaction.user.id, choice)
            if ties:
                await interaction.followup.send("Empate. Elige uno de los horarios más votados:",
                                                view=TieView(self, message_id, ties), ephemeral=True)
                return
            meeting = await self.system.call("get", key)
            if meeting["status"] != "scheduled":
                raise ValueError(f"La reunión #{key} ya terminó.")
            notice = await self.system.refresh_notice(key)
            notice += await self.system.snapshot_notice(meeting)
        await interaction.followup.send(f"✅ Reunión #{key} programada para <t:{meeting['starts_at']}:F>." + notice, ephemeral=True)


class PollView(discord.ui.View):
    def __init__(self, polls):
        super().__init__(timeout=None)
        self.polls = polls

    @discord.ui.select(custom_id="lvrp:poll:availability", placeholder="Mis horarios disponibles",
                       min_values=1, max_values=3, options=[
                           *[discord.SelectOption(label=f"Horario {i}", value=str(i)) for i in SLOTS],
                           discord.SelectOption(label="Ninguno / retirar mi voto", value="none")])
    async def availability(self, interaction, select):
        await interaction.response.defer(ephemeral=True)
        await self.polls.system.channel_access(interaction, interaction.channel_id)
        selected = interaction.data["values"]
        if "none" in selected and len(selected) != 1:
            raise ValueError("Selecciona «Ninguno» solo o marca los horarios que te sirven.")
        choices = [] if selected == ["none"] else list(map(int, selected))
        async with self.polls.system.lock:
            poll = await asyncio.to_thread(self.polls.vote, interaction.message.id, interaction.channel_id, interaction.user.id, choices)
            try:
                await interaction.message.edit(embed=poll_embed(poll), allowed_mentions=discord.AllowedMentions.none())
                notice = ""
            except discord.HTTPException:
                log.exception("Fallo al refrescar encuesta %s", interaction.message.id)
                notice = " El recuento quedó guardado, pero Discord no pudo actualizar el panel."
        result = "Tus horarios: " + ", ".join(map(str, sorted(choices))) if choices else "Retiraste tu voto."
        await interaction.followup.send(result + notice, ephemeral=True)

    @discord.ui.button(label="Crear reunión", style=discord.ButtonStyle.success, custom_id="lvrp:poll:schedule")
    async def schedule(self, interaction, button):
        await self.polls.finish(interaction, interaction.message.id)

    async def on_error(self, interaction, error, item):
        await meeting_error(interaction, error)


class TieView(discord.ui.View):
    def __init__(self, polls, message_id, ties):
        super().__init__(timeout=180)
        self.polls, self.message_id = polls, message_id
        self.pick.options = [discord.SelectOption(label=f"Horario {i} · {datetime.fromtimestamp(start, PR):%d/%m %H:%M} PR",
                                                 value=str(i)) for i, start in ties]

    @discord.ui.select(placeholder="Elegir horario para crear la reunión")
    async def pick(self, interaction, select):
        await self.polls.finish(interaction, self.message_id, int(interaction.data["values"][0]))

    async def on_error(self, interaction, error, item):
        await meeting_error(interaction, error)
