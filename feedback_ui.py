"""Small public panels, private pickers and staff feedback forms."""
import logging
import re

import discord

from photo_members import matches

RED = 0xBE2335
NONE = discord.AllowedMentions.none()
log = logging.getLogger('LaVenganzaRP.feedback')


async def reply(i, content=None, **kwargs):
    sender = i.followup.send if i.response.is_done() else i.response.send_message
    return await sender(content, ephemeral=True, allowed_mentions=NONE, **kwargs)


async def failed(i, error):
    if isinstance(error, ValueError):
        return await reply(i, str(error))
    log.error('FEEDBACK interaction_failed', exc_info=error)
    await reply(i, 'Hubo un problema, bro. Revisa «Mis opiniones» antes de intentarlo otra vez.')


class FeedbackAction(discord.ui.DynamicItem[discord.ui.Button], template=r'lvfb:(?P<action>start|mine|stats|ticket|respond):(?P<rid>[0-9]+)'):
    def __init__(self, action, rid=0):
        labels = {'start': ('Dejar feedback', '⭐'), 'mine': ('Mis opiniones', '📋'),
                  'stats': ('Ver resultados', '📊'), 'ticket': ('Dejar feedback', '⭐'), 'respond': ('Responder', '💬')}
        label, emoji = labels[action]
        super().__init__(discord.ui.Button(label=label, emoji=emoji,
            style=discord.ButtonStyle.primary if action in ('start', 'ticket') else discord.ButtonStyle.secondary,
            custom_id=f'lvfb:{action}:{rid}'))
        self.action, self.rid = action, rid

    @classmethod
    async def from_custom_id(cls, i, item, match: re.Match):
        return cls(match['action'], int(match['rid']))

    async def callback(self, i):
        try:
            await i.client.feedback.handle(i, self.action, self.rid)
        except Exception as error:
            await failed(i, error)


def controls(*actions, rid=0):
    view = discord.ui.View(timeout=None)
    for action in actions:
        view.add_item(FeedbackAction(action, rid))
    return view


class OwnedView(discord.ui.View):
    def __init__(self, system, owner):
        super().__init__(timeout=600)
        self.system, self.owner = system, owner

    async def interaction_check(self, i):
        if i.user.id == self.owner and i.guild_id in (None, self.system.guild_id):
            return True
        await reply(i, 'Esta selección pertenece a quien la abrió, bro.')
        return False

    async def on_error(self, i, error, item):
        await failed(i, error)


class EntryChoice(OwnedView):
    @discord.ui.button(label='Valorar un ticket', emoji='🎫', style=discord.ButtonStyle.primary)
    async def tickets(self, i, button):
        await self.system.ticket_picker(i)

    @discord.ui.button(label='Me atendieron fuera de tickets', emoji='🎙️')
    async def outside(self, i, button):
        await self.system.staff_picker(i)


class StaffSearch(discord.ui.Modal):
    def __init__(self, picker):
        super().__init__(title='Buscar a quien te atendió')
        self.picker = picker
        self.query = discord.ui.TextInput(label='Nombre, usuario o apodo', required=False, max_length=100)
        self.add_item(self.query)

    async def on_submit(self, i):
        if not await self.picker.interaction_check(i):
            return
        self.picker.query, self.picker.page = self.query.value.strip(), 0
        self.picker.build()
        await i.response.edit_message(content=self.picker.text(), view=self.picker, allowed_mentions=NONE)


class Picker(OwnedView):
    def __init__(self, system, owner, rows, kind):
        super().__init__(system, owner)
        self.rows, self.kind, self.page, self.query = rows, kind, 0, ''
        self.build()

    def filtered(self):
        return [m for m in self.rows if matches(m, self.query)] if self.kind == 'staff' else self.rows

    def text(self):
        count = len(self.filtered())
        intro = 'Elige a quien te atendió. También aparecen quienes están desconectados.' if self.kind == 'staff' else 'Elige el ticket resuelto o cerrado que quieres valorar. También puedes valorar uno cuyo canal ya se eliminó.'
        return f'{intro}\nPágina {self.page+1}/{max(1,(count+24)//25)} · {count} '+('personas' if self.kind == 'staff' else 'tickets pendientes de valorar')

    def build(self):
        self.clear_items()
        rows = self.filtered()
        pages = max(1, (len(rows)+24)//25)
        self.page = min(self.page, pages-1)
        page = rows[self.page*25:(self.page+1)*25]
        if page:
            options = [discord.SelectOption(label=m.display_name[:100], value=str(m.id), description=('@'+m.name)[:100]) for m in page] if self.kind == 'staff' else [
                discord.SelectOption(label=f"Ticket #{r['id']} · {r['subject']}"[:100], value=str(r['id']), description='Solo administración' if r['department'] == 'staff' else 'Atención verificada en ticket') for r in page]
            select = discord.ui.Select(placeholder='¿Quién te atendió?' if self.kind == 'staff' else 'Elige un ticket para valorar', options=options, row=0)

            async def choose(i):
                selected = int(select.values[0])
                if self.kind == 'staff':
                    await self.system.outside_form(i, selected)
                else:
                    await self.system.ticket_form(i, selected)
            select.callback = choose
            self.add_item(select)
        for label, delta, disabled in [('Anterior', -1, self.page == 0), ('Siguiente', 1, self.page == pages-1)]:
            button = discord.ui.Button(label=label, disabled=disabled, row=1)

            async def turn(i, delta=delta):
                self.page += delta
                self.build()
                await i.response.edit_message(content=self.text(), view=self, allowed_mentions=NONE)
            button.callback = turn
            self.add_item(button)
        if self.kind == 'staff':
            button = discord.ui.Button(label='Buscar', emoji='🔎', row=1)

            async def search(i):
                await i.response.send_modal(StaffSearch(self))
            button.callback = search
            self.add_item(button)


class FeedbackForm(discord.ui.Modal):
    def __init__(self, system, *, ticket=None, staff=None, reserved=False, visibility='private'):
        super().__init__(title='¿Cómo te atendieron?', timeout=600)
        self.system, self.ticket, self.staff, self.reserved = system, ticket, staff, reserved
        self.default_visibility = 'private' if reserved else visibility
        self.stars = discord.ui.Select(custom_id='stars', placeholder='Elige de 1 a 5 estrellas', options=[
            discord.SelectOption(label='⭐'*n+' · '+label, value=str(n)) for n,label in enumerate(('Muy mala', 'Mala', 'Regular', 'Buena', 'Excelente'), 1)])
        self.comment = discord.ui.TextInput(custom_id='comment', style=discord.TextStyle.paragraph,
            placeholder='¿Qué hicieron bien o qué deberían mejorar?', required=False, max_length=1000)
        self.visibility = discord.ui.Select(custom_id='visibility', options=[
            discord.SelectOption(label='Solo administración', value='private', default=self.default_visibility == 'private'),
            *([] if reserved else [discord.SelectOption(label='Publicar en Feedback', value='public', default=self.default_visibility == 'public')])])
        self.add_item(discord.ui.Label(text='¿Cuántas estrellas le das?', component=self.stars))
        self.add_item(discord.ui.Label(text='¿Quieres contar cómo te fue?', component=self.comment))
        self.add_item(discord.ui.Label(text='¿Dónde quieres que se vea?',
            description='Los reportes contra staff quedan solo para administración.' if reserved else 'Si la publicas, se verán tu nombre, las estrellas y tu comentario.', component=self.visibility))
        self.topic = None
        if ticket is None:
            self.topic = discord.ui.TextInput(custom_id='topic', placeholder='Ejemplo: me ayudaron por voz con un problema.', max_length=160, min_length=3)
            self.add_item(discord.ui.Label(text='¿Con qué te ayudaron?', component=self.topic))

    async def on_submit(self, i):
        await i.response.defer(ephemeral=True, thinking=True)
        try:
            score = self.stars.values[0] if self.stars.values else ''
            if score not in ('1','2','3','4','5'):
                raise ValueError('Elige de 1 a 5 estrellas, bro.')
            visibility = self.visibility.values[0] if self.visibility.values else self.default_visibility
            await self.system.submit(i, int(score), self.comment.value, visibility,
                ticket=self.ticket, staff=self.staff, topic=self.topic.value if self.topic else '')
        except Exception as error:
            await failed(i, error)

    async def on_error(self, i, error):
        await failed(i, error)


class Mine(OwnedView):
    def __init__(self, system, owner, rows, page=0):
        super().__init__(system, owner)
        select = discord.ui.Select(placeholder='Ver o retirar una opinión', options=[discord.SelectOption(
            label=f"#{r['id']} · {'⭐'*r['score']} · "+('Retirada' if r['hidden_at'] else 'Pública' if r['visibility']=='public' else 'Privada'), value=str(r['id'])) for r in rows])

        async def select_row(i):
            await self.system.detail(i, int(select.values[0]))
        select.callback = select_row
        self.add_item(select)
        for label, delta, disabled in [('Anterior', -1, page == 0), ('Siguiente', 1, len(rows) < 8)]:
            button = discord.ui.Button(label=label, disabled=disabled)

            async def turn(i, delta=delta):
                await self.system.mine(i, page+delta)
            button.callback = turn
            self.add_item(button)


class Withdraw(OwnedView):
    def __init__(self, system, owner, rid, reason='Retirada por su autor', admin=False):
        super().__init__(system, owner)
        self.rid, self.reason, self.admin = rid, reason, admin

    @discord.ui.button(label='Retirar opinión', emoji='🗑️', style=discord.ButtonStyle.danger)
    async def confirm(self, i, button):
        await self.system.withdraw(i, self.rid, self.reason, self.admin)

    @discord.ui.button(label='Cancelar')
    async def cancel(self, i, button):
        await i.response.edit_message(content='No se retiró la opinión.', embed=None, view=None)
        self.stop()


class StaffReply(discord.ui.Modal):
    def __init__(self, system, rid):
        super().__init__(title='Responder al feedback')
        self.system, self.rid = system, rid
        self.text = discord.ui.TextInput(label='Tu respuesta', style=discord.TextStyle.paragraph, max_length=1000)
        self.add_item(self.text)

    async def on_submit(self, i):
        await i.response.defer(ephemeral=True)
        try:
            await self.system.respond(i, self.rid, self.text.value)
        except Exception as error:
            await failed(i, error)
