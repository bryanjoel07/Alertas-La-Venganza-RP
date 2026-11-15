"""Suggestions, real customer reviews and persistent voting for the store channels."""
from contextlib import closing
import sqlite3
import time
import asyncio

import discord
from esschino import StudioView


class CommunityStore:
    def __init__(self, path):
        self.path = path

    def db(self):
        return sqlite3.connect(self.path, timeout=10)

    def initialize(self):
        with closing(self.db()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS studio_ideas(id INTEGER PRIMARY KEY,owner TEXT NOT NULL,
                    title TEXT NOT NULL,body TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pendiente',
                    reason TEXT NOT NULL DEFAULT '',message TEXT UNIQUE,created INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS studio_votes(idea INTEGER NOT NULL,user TEXT NOT NULL,
                    value INTEGER NOT NULL CHECK(value IN (-1,1)),PRIMARY KEY(idea,user));
                CREATE TABLE IF NOT EXISTS studio_reviews(id INTEGER PRIMARY KEY,owner TEXT NOT NULL,
                    product TEXT NOT NULL,rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                    body TEXT NOT NULL,message TEXT UNIQUE,updated INTEGER NOT NULL,UNIQUE(owner,product));
            ''')

    def idea(self, *, row_id=None, message=None):
        with closing(self.db()) as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM studio_ideas WHERE ' + ('id=?' if row_id else 'message=?'),
                             (row_id if row_id else str(message),)).fetchone()
            return dict(row) if row else None

    def new_idea(self, owner, title, body):
        with closing(self.db()) as db, db:
            recent = db.execute('SELECT created FROM studio_ideas WHERE owner=? ORDER BY id DESC LIMIT 1', (str(owner),)).fetchone()
            if recent and time.time() - recent[0] < 60:
                raise ValueError('Espera un minuto antes de publicar otra sugerencia.')
            return db.execute('INSERT INTO studio_ideas(owner,title,body,created) VALUES (?,?,?,?)',
                              (str(owner), title, body, int(time.time()))).lastrowid

    def idea_message(self, row_id, message):
        with closing(self.db()) as db, db:
            db.execute('UPDATE studio_ideas SET message=? WHERE id=?', (str(message), row_id))

    def vote(self, idea, user, value):
        with closing(self.db()) as db, db:
            row = db.execute('SELECT state FROM studio_ideas WHERE id=?', (idea,)).fetchone()
            if not row or row[0] in {'completada', 'descartada'}:
                raise ValueError('La votación de esta idea está cerrada.')
            previous = db.execute('SELECT value FROM studio_votes WHERE idea=? AND user=?', (idea, str(user))).fetchone()
            if previous and previous[0] == value:
                db.execute('DELETE FROM studio_votes WHERE idea=? AND user=?', (idea, str(user)))
            else:
                db.execute('INSERT OR REPLACE INTO studio_votes VALUES (?,?,?)', (idea, str(user), value))

    def counts(self, idea):
        with closing(self.db()) as db:
            return dict(db.execute('SELECT value,COUNT(*) FROM studio_votes WHERE idea=? GROUP BY value', (idea,)))

    def decide(self, idea, state, reason):
        if state not in {'pendiente', 'aceptada', 'en-desarrollo', 'completada', 'descartada'}:
            raise ValueError('Estado válido: pendiente, aceptada, en-desarrollo, completada o descartada.')
        with closing(self.db()) as db, db:
            db.execute('UPDATE studio_ideas SET state=?,reason=? WHERE id=?', (state, reason, idea))

    def review(self, owner, product, rating, body):
        product = product.strip().casefold()
        with closing(self.db()) as db, db:
            db.execute('INSERT INTO studio_reviews(owner,product,rating,body,updated) VALUES (?,?,?,?,?) '
                       'ON CONFLICT(owner,product) DO UPDATE SET rating=excluded.rating,body=excluded.body,updated=excluded.updated',
                       (str(owner), product, rating, body, int(time.time())))
            db.row_factory = sqlite3.Row
            return dict(db.execute('SELECT * FROM studio_reviews WHERE owner=? AND product=?', (str(owner), product)).fetchone())

    def review_message(self, row_id, message):
        with closing(self.db()) as db, db:
            db.execute('UPDATE studio_reviews SET message=? WHERE id=?', (str(message), row_id))

    def snapshot(self):
        with closing(self.db()) as db:
            db.row_factory = sqlite3.Row
            return {table: [dict(r) for r in db.execute('SELECT * FROM ' + table)]
                    for table in ('studio_ideas', 'studio_votes', 'studio_reviews')}


class IdeasPanel(StudioView):
    @discord.ui.button(label='Proponer una mejora', emoji='💡', custom_id='ec:idea:new', style=discord.ButtonStyle.primary)
    async def propose(self, i, button):
        await i.response.send_modal(IdeaModal(self.system.community))


class ReviewsPanel(StudioView):
    @discord.ui.button(label='Escribir mi reseña', emoji='⭐', custom_id='ec:review:new', style=discord.ButtonStyle.primary)
    async def write(self, i, button):
        self.system.community.customer(i)
        await i.response.send_modal(ReviewModal(self.system.community))


class IdeaVotes(StudioView):
    @discord.ui.button(label='A favor', emoji='👍', custom_id='ec:idea:up')
    async def up(self, i, button):
        await self.system.community.vote(i, 1)

    @discord.ui.button(label='En contra', emoji='👎', custom_id='ec:idea:down')
    async def down(self, i, button):
        await self.system.community.vote(i, -1)

    @discord.ui.button(label='Gestionar idea', emoji='🛠️', custom_id='ec:idea:state')
    async def state(self, i, button):
        if not self.system.staff(i.user):
            raise ValueError('Solo el equipo puede cambiar el estado de una idea.')
        row = self.system.community.idea_for(i)
        await i.response.send_modal(IdeaStateModal(self.system.community, row['id']))


class BaseModal(discord.ui.Modal):
    async def on_error(self, i, error):
        await StudioView(self.community.system).on_error(i, error, None)


class IdeaModal(BaseModal, title='Sugerencia · EssChino Studio'):
    subject = discord.ui.TextInput(label='Título de la idea', max_length=100)
    body = discord.ui.TextInput(label='Necesidad, propuesta y ejemplo', style=discord.TextStyle.paragraph, max_length=1600)

    def __init__(self, community):
        super().__init__()
        self.community = community

    async def on_submit(self, i):
        self.community.scope(i)
        await i.response.defer(ephemeral=True)
        async with self.community.lock:
            async def apply():
                row_id = await self.community.call('new_idea', i.user.id, str(self.subject), str(self.body))
                row = self.community.store.idea(row_id=row_id)
                channel = await self.community.channel(i, 'suggestions')
                message = await channel.send(embed=self.community.idea_embed(row), view=IdeaVotes(self.community.system),
                                             allowed_mentions=discord.AllowedMentions.none())
                await self.community.call('idea_message', row_id, message.id)
                return message
            message = await self.community.system.tracked(f'idea:{i.id}', 'Publicar sugerencia de tienda', apply)
        await i.followup.send(f'Tu idea está publicada: {message.jump_url}', ephemeral=True)


class IdeaStateModal(BaseModal, title='Estado de la sugerencia'):
    state = discord.ui.TextInput(label='Estado', placeholder='pendiente / aceptada / en-desarrollo / completada / descartada', max_length=30)
    reason = discord.ui.TextInput(label='Respuesta del equipo', style=discord.TextStyle.paragraph, max_length=700, required=False)

    def __init__(self, community, idea):
        super().__init__()
        self.community, self.idea = community, idea

    async def on_submit(self, i):
        self.community.scope(i)
        if not self.community.system.staff(i.user):
            raise ValueError('Solo el equipo puede gestionar las ideas.')
        await i.response.defer(ephemeral=True)
        async with self.community.lock:
            async def apply():
                await self.community.call('decide', self.idea, str(self.state).strip().casefold(), str(self.reason))
                row = self.community.store.idea(row_id=self.idea)
                channel = await self.community.channel(i, 'suggestions')
                await (await channel.fetch_message(int(row['message']))).edit(embed=self.community.idea_embed(row), view=IdeaVotes(self.community.system))
            await self.community.system.tracked(f'idea-state:{i.id}', 'Responder sugerencia de tienda', apply)
        await i.followup.send('Estado y respuesta actualizados.', ephemeral=True)


class ReviewModal(BaseModal, title='Reseña de cliente · EssChino Studio'):
    product = discord.ui.TextInput(label='Script o producto comprado', max_length=100)
    stars = discord.ui.TextInput(label='Puntuación del 1 al 5', max_length=1)
    body = discord.ui.TextInput(label='Tu experiencia real con el producto', style=discord.TextStyle.paragraph, max_length=1400)

    def __init__(self, community):
        super().__init__()
        self.community = community

    async def on_submit(self, i):
        self.community.customer(i)
        if str(self.stars) not in {'1', '2', '3', '4', '5'}:
            raise ValueError('La puntuación debe ser un número del 1 al 5.')
        await i.response.defer(ephemeral=True)
        async with self.community.lock:
            async def apply():
                row = await self.community.call('review', i.user.id, str(self.product), int(str(self.stars)), str(self.body))
                channel = await self.community.channel(i, 'reviews')
                embed = self.community.system.embed('⭐ Reseña de cliente verificado',
                    f'**Producto:** {row["product"]}\n**Cliente:** <@{i.user.id}>\n**Valoración:** {"⭐" * row["rating"]}\n\n{row["body"]}')
                embed.set_footer(text=f'EssChino Studio · Reseña #{row["id"]} · Opinión de un cliente verificado')
                message = None
                if row['message']:
                    try:
                        message = await channel.fetch_message(int(row['message']))
                    except discord.NotFound:
                        pass
                if message:
                    await message.edit(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                else:
                    message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                    await self.community.call('review_message', row['id'], message.id)
                return message
            message = await self.community.system.tracked(f'review:{i.id}', 'Publicar reseña de cliente', apply)
        await i.followup.send(f'Tu reseña está publicada: {message.jump_url}', ephemeral=True)


class StoreCommunity:
    def __init__(self, system, path):
        self.system, self.store = system, CommunityStore(path)
        self.lock = asyncio.Lock()

    async def call(self, method, *args):
        return await asyncio.to_thread(getattr(self.store, method), *args)

    async def start(self):
        await self.call('initialize')
        for view in (IdeasPanel, ReviewsPanel, IdeaVotes):
            self.system.bot.add_view(view(self.system))

    def panel_view(self, key):
        return (IdeasPanel if key == 'suggestions' else ReviewsPanel)(self.system)

    def scope(self, i):
        if i.guild_id != self.system.store.get('guild') or not isinstance(i.user, discord.Member) or i.user.bot:
            raise ValueError('Usa este panel dentro de EssChino Studio con tu cuenta.')

    def customer(self, i):
        self.scope(i)
        if self.system.store.get('role:customer') not in {r.id for r in i.user.roles}:
            raise ValueError('Para publicar una reseña necesitas una compra verificada y el rol Cliente.')

    async def channel(self, i, key):
        return i.guild.get_channel(self.system.channel_id(key)) or await self.system.bot.fetch_channel(self.system.channel_id(key))

    def idea_for(self, i):
        self.scope(i)
        row = self.store.idea(message=i.message.id)
        if i.channel_id != self.system.channel_id('suggestions') or not row:
            raise ValueError('Esa publicación no es una sugerencia de este bot.')
        return row

    def idea_embed(self, row):
        counts = self.store.counts(row['id'])
        embed = self.system.embed('💡 ' + row['title'],
            f'**Autor:** <@{row["owner"]}>\n**Estado:** {row["state"]}\n\n{row["body"]}')
        embed.add_field(name='Votos de la comunidad', value=f'👍 {counts.get(1,0)} · 👎 {counts.get(-1,0)}', inline=False)
        if row['reason']:
            embed.add_field(name='Respuesta del equipo', value=row['reason'], inline=False)
        return embed.set_footer(text=f'EssChino Studio · Idea #{row["id"]} · Un voto por miembro')

    async def vote(self, i, value):
        row = self.idea_for(i)
        await i.response.defer(ephemeral=True)
        async with self.lock:
            async def apply():
                await self.call('vote', row['id'], i.user.id, value)
                await i.message.edit(embed=self.idea_embed(self.store.idea(row_id=row['id'])), view=IdeaVotes(self.system))
            await self.system.tracked(f'idea-vote:{i.id}', 'Votar sugerencia de tienda', apply)
        await i.followup.send('Tu voto se ha actualizado.', ephemeral=True)
