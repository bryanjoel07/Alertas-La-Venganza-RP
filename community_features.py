"""Weekly challenges, private fitting room and the persistent bot guide."""
import asyncio
import hashlib
import json
import logging
from pathlib import Path
import time

import discord
from discord import app_commands

from economy_delivery import LABELS
from economy_store import outfit_for
from player_cards import profile_embed
from profiles_hub import normalized, profile_overwrites
from weekly_challenges import WeeklyChallenges

log = logging.getLogger('LaVenganzaRP.comunidad')
GUIDE_NAME = '📖┊𝐆𝐮𝐢𝐚-𝐃𝐞𝐥-𝐁𝐨𝐭'
GUIDE_MARKER = 'La Venganza RP · Guía del bot'


async def respond(i,**kwargs):
    sender = i.followup.send if i.response.is_done() else i.response.send_message
    await sender(ephemeral=True,allowed_mentions=discord.AllowedMentions.none(),**kwargs)


class ClaimView(discord.ui.View):
    def __init__(self,features,user):
        super().__init__(timeout=180)
        self.features,self.user = features,user

    @discord.ui.button(label='Reclamar recompensas',emoji='🪙',style=discord.ButtonStyle.primary)
    async def claim(self,i,button):
        if i.user.id != self.user:
            return await respond(i,content='Abre tus propios retos con /retos.')
        await i.response.defer(ephemeral=True)
        amount = await asyncio.to_thread(self.features.weekly.claim,i.user.id)
        await respond(i,content=f'✅ Recibiste **{amount} 🪙**.' if amount else 'No tienes recompensas nuevas pendientes.',
                      embed=await self.features.challenge_embed(i.user.id),view=ClaimView(self.features,i.user.id))


class TryPicker(discord.ui.Select):
    def __init__(self,features,products):
        super().__init__(placeholder='Elige un cosmético para probar sin comprar',
                         options=[discord.SelectOption(label=p['name'][:100],value=p['sku'],
                                  description=f"{p['price']} 🪙 · Vista previa gratuita") for p in products[:25]])
        self.features = features

    async def callback(self,i):
        await self.features.try_product(i,self.values[0])


class TryView(discord.ui.View):
    def __init__(self,features,user,sku):
        super().__init__(timeout=180)
        self.features,self.user,self.sku = features,user,sku

    async def interaction_check(self,i):
        if i.user.id == self.user:
            return True
        await respond(i,content='Abre tu propio probador con /probar.')
        return False

    @discord.ui.button(label='Revisar compra',emoji='🛍️',style=discord.ButtonStyle.primary)
    async def buy(self,i,button):
        try:
            await self.features.economy.preview(i,self.sku,i.user)
        except ValueError as error:
            await respond(i,content=str(error))


class GuideView(discord.ui.View):
    def __init__(self,features):
        super().__init__(timeout=None)
        self.features = features

    async def interaction_check(self,i):
        log.info('Botón guía recibido: %s',i.data.get('custom_id','desconocido'))
        if not i.response.is_done():
            await i.response.defer(ephemeral=True,thinking=True)
        return True

    @discord.ui.button(label='Mi perfil',emoji='👤',custom_id='lvrp:guide:profile',row=0)
    async def profile(self,i,button):
        command = self.features.economy.bot.tree.get_command('perfil',guild=discord.Object(id=i.guild_id))
        await command.callback(i)

    @discord.ui.button(label='Tienda',emoji='🛍️',custom_id='lvrp:guide:shop',row=0)
    async def shop(self,i,button):
        await self.features.economy.shop(i)

    @discord.ui.button(label='Probador',emoji='👔',custom_id='lvrp:guide:try',row=0)
    async def fitting(self,i,button):
        await self.features.show_picker(i)

    @discord.ui.button(label='Retos y monedas',emoji='🏆',custom_id='lvrp:guide:challenges',row=1)
    async def challenges(self,i,button):
        await self.features.show_challenges(i)

    @discord.ui.button(label='Ser streamer',emoji='📺',custom_id='lvrp:guide:streamer',row=1)
    async def streamer(self,i,button):
        await self.features.economy.bot.streamers.issue_code(i)

    @discord.ui.button(label='Mi saldo',emoji='🪙',custom_id='lvrp:guide:balance',row=1)
    async def balance(self,i,button):
        await self.features.economy.balance(i)

    async def on_error(self,i,error,item):
        log.error('Error en guía del bot',exc_info=(type(error),error,error.__traceback__))
        await respond(i,content='No se pudo abrir esta opción. Usa el comando correspondiente o inténtalo de nuevo.')


class CommunityFeatures:
    def __init__(self,economy):
        self.economy = economy
        self.weekly = WeeklyChallenges(economy.store)
        self.guide_view = GuideView(self)
        self.guide_published = False

    async def start(self):
        await asyncio.to_thread(self.weekly.initialize)
        self.economy.bot.add_view(self.guide_view)

    async def challenge_embed(self,user):
        data = await asyncio.to_thread(self.weekly.progress,user)
        embed = discord.Embed(title='🏆 RETOS SEMANALES | LA VENGANZA RP',color=0xD60000,
            description=f"Renuevan <t:{data['ends']}:F> · lunes a medianoche de Puerto Rico.\n"
                        'Hasta **450 🪙 por semana**. Solo cuenta actividad nueva confirmada; no se paga por mensajes, AFK ni inscripciones.')
        for g in data['goals']:
            state = '✅ Cobrado' if g['claimed'] else '🪙 Listo para reclamar' if g['done'] else '⏳ Pendiente'
            embed.add_field(name=f"{g['label']} · {g['reward']} 🪙",value=state,inline=False)
        embed.set_footer(text='Staff confirma participación y asistencia · No hay pagos duplicados')
        return embed

    async def show_challenges(self,i):
        if not i.response.is_done():
            await i.response.defer(ephemeral=True)
        await respond(i,embed=await self.challenge_embed(i.user.id),view=ClaimView(self,i.user.id))

    def available(self,user):
        now = time.time()
        return [p for p in self.economy.store.rotation(user=user)['products'] if p['active'] and p['stock']!=0
                and (not p['campaign_start'] or p['campaign_start']<=now)
                and (not p['campaign_end'] or p['campaign_end']>now)]

    async def show_picker(self,i):
        if not i.response.is_done():
            await i.response.defer(ephemeral=True)
        products = self.available(i.user.id)
        view = discord.ui.View(timeout=180)
        if products:
            view.add_item(TryPicker(self,products))
        await respond(i,content='👔 **Probador privado:** no cobra, no equipa y no cambia tus roles.\n'
                      'Para texto o color personalizado usa `/probar articulo:… texto:…`.',view=view)

    async def try_product(self,i,sku,text=''):
        if not i.response.is_done():
            await i.response.defer(ephemeral=True)
        product = next((p for p in self.available(i.user.id) if p['sku']==sku),None)
        if product is None:
            return await respond(i,content='Ese artículo no está disponible en tu rotación actual.')
        data = await self.economy.bot.event_features.call('profile',i.user.id,1)
        embed = profile_embed(i.user,data)
        self.economy.decorate(embed,i.user.id)
        payload = json.loads(product['payload'])
        kind = product['kind']
        file = None
        if kind == 'voice':
            sample = 'Sala privada por 7 días, con acceso por invitación. La prueba no crea una sala.'
        else:
            defaults = dict(plate='LVRP-7',signature='¡Nos vemos en la ciudad!',custom_color='#D60000',
                            nickname='RP',bio='La ciudad más real · El rol más duro')
            try:
                selections = outfit_for(product,text or defaults.get(kind,''))
            except ValueError as error:
                return await respond(i,content=str(error))
            sample = '\n'.join(f"**{LABELS.get(slot,slot)}:** {discord.utils.escape_markdown(str(value))}" for slot,value in selections.items())
            replaced = {LABELS.get(slot,slot) for slot in selections}
            original = [f for f in embed.fields if f.name not in replaced]
            embed.clear_fields()
            for f in original:
                embed.add_field(name=f.name,value=f.value,inline=f.inline)
            if kind in ('theme','color','custom_color','bundle'):
                embed.color = int(selections.get('color',f"{payload.get('color',0xD60000):06X}"),16)
            if kind == 'banner':
                art = payload.get('art')
                if art not in ('garaje','salinas','parrilla'):
                    return await respond(i,content='Este banner no tiene una ilustración disponible.')
                file = discord.File(Path(__file__).parent/'assets'/'banners'/f'{art}.jpg')
                embed.set_image(url=f'attachment://{art}.jpg')
        # Other equipped banners are private repository URLs; attach their original locally.
        if file is None and embed.image.url and '/assets/banners/' in embed.image.url:
            art = embed.image.url.rsplit('/',1)[-1]
            if art in ('garaje.jpg','salinas.jpg','parrilla.jpg'):
                file = discord.File(Path(__file__).parent/'assets'/'banners'/art)
                embed.set_image(url=f'attachment://{art}')
        while len(embed.fields)>=25:
            embed.remove_field(6)
        embed.add_field(name=f"👔 Prueba: {product['name']}",value=sample[:1024],inline=False)
        while len(embed)>5800 and len(embed.fields)>7:
            embed.remove_field(6)
        embed.set_footer(text=f"VISTA PREVIA · {product['price']} monedas si compras · No se ha cobrado ni equipado")
        kwargs = dict(embed=embed,view=TryView(self,i.user.id,sku))
        if file:
            kwargs['file'] = file
        await respond(i,**kwargs)

    def guide_embed(self):
        store = self.economy.store
        embed = discord.Embed(title='📖 GUÍA DEL BOT | LA VENGANZA RP',color=0xD60000,
            description='Tu perfil, tus monedas y las actividades de la comunidad, en un solo lugar.\nUsa los botones: las consultas se abren en privado.')
        for title,body in (
            ('👤 Tu perfil','`/perfil` muestra saldo, cosméticos, eventos y podios. Usa **Actualizar** después de comprar.'),
            ('🪙 Cómo ganar monedas','`/retos`: hasta **450 🪙 semanales** por actividad confirmada. Los eventos también tienen premios configurados por staff. Una inscripción o estar AFK no cuenta.'),
            ('🛍️ Tienda y probador',f"Tienda: <#{store.config('shop_channel')}>. Usa `/probar` antes de comprar; `/comprar` exige confirmación. `/inventario` y `/equipar` gestionan lo que ya tienes."),
            ('🎁 Regalos y ahorro','`/regalar` solicita confirmación del destinatario. `/deseos` guarda artículos y `/saldo` muestra tu meta de ahorro.'),
            ('🏁 Eventos y reuniones','Inscríbete desde los anuncios. El staff confirma asistencia y resultados; los premios y retos usan esos registros.'),
            ('📺 Creadores','Solicita el rol con el botón **Ser streamer**. Verifica tu canal y guarda su enlace. Los avisos requieren **La Venganza RP** en el título. El staff también puede usar `/streamer registrar`.'),
            ('📡 Estado del servidor','SERVER UP diario: **6:30 p. m. Puerto Rico**. Caídas, recuperaciones y mantenimiento se anuncian por separado.'),
        ):
            embed.add_field(name=title,value=body,inline=False)
        embed.set_footer(text='LA VENGANZA RP · Consultas privadas · Monedas de la comunidad, no dinero de FiveM')
        return embed

    async def ensure_guide(self,guild):
        if self.guide_published:
            return
        streamers = self.economy.bot.streamers
        role, minimum = streamers.config(guild)
        if role is None:
            from streamer_panel import ROLE_ID
            role = guild.get_role(ROLE_ID)
        if streamers.safe_role(role):
            with streamers.db() as db:
                db.execute('INSERT OR IGNORE INTO streamer_config VALUES (?,?,?)',(guild.id,role.id,minimum))
            log.info('Registro de creadores listo: rol=%s (%s), mínimo=%s; registro administrativo disponible',role.name,role.id,minimum)
        else:
            log.warning('Registro de creadores requiere configurar un rol seguro y asignable')
        store = self.economy.store
        category = self.economy.delivery.category(guild)
        saved = store.config('guide_channel')
        channel = guild.get_channel(int(saved)) if saved else None
        if channel is None:
            candidates = [c for c in await guild.fetch_channels() if isinstance(c,discord.TextChannel)
                          and c.category_id==category.id and (c.topic==GUIDE_MARKER or normalized(c.name)=='guiadelbot')]
            if len(candidates)>1:
                raise ValueError('Hay varias guías del bot; requiere seleccionar un destino.')
            channel = candidates[0] if candidates else None
        if channel is None:
            channel = await guild.create_text_channel(GUIDE_NAME,category=category,topic=GUIDE_MARKER,
                    overwrites=profile_overwrites(guild,category.overwrites),reason='Guía del bot solicitada por el administrador')
        store.runtime_config('guide_channel',channel.id)
        message = None
        if store.config('guide_message'):
            try:
                message = await channel.fetch_message(int(store.config('guide_message')))
            except discord.NotFound:
                pass
        if message is None:
            async for candidate in channel.history(limit=30):
                if candidate.author.id==guild.me.id and candidate.embeds and candidate.embeds[0].title=='📖 GUÍA DEL BOT | LA VENGANZA RP':
                    message=candidate
                    break
        embed = self.guide_embed()
        if message:
            await message.edit(embed=embed,view=self.guide_view,allowed_mentions=discord.AllowedMentions.none())
        else:
            message=await channel.send(embed=embed,view=self.guide_view,allowed_mentions=discord.AllowedMentions.none())
        store.runtime_config('guide_message',message.id)
        self.economy.bot.add_view(self.guide_view,message_id=message.id)
        self.guide_published = True
        log.info('Guía del bot lista: canal=%s mensaje=%s; retos y probador activos',channel.id,message.id)

    def register(self,player):
        @player('retos','Ver y reclamar retos semanales de participación verificada')
        async def challenges(i:discord.Interaction):
            await self.show_challenges(i)

        @player('probar','Probar un cosmético en privado antes de comprar')
        async def fitting(i:discord.Interaction,articulo:str='',texto:app_commands.Range[str,1,100]=''):
            if articulo:
                await self.try_product(i,articulo,texto)
            else:
                await self.show_picker(i)

        @fitting.autocomplete('articulo')
        async def choices(i:discord.Interaction,current:str):
            return [app_commands.Choice(name=p['name'][:100],value=p['sku']) for p in self.available(i.user.id)
                    if current.casefold() in p['name'].casefold() or current.casefold() in p['sku'].casefold()][:25]

        @player('guia','Abrir la guía del bot con botones de ayuda')
        async def guide(i:discord.Interaction):
            await respond(i,embed=self.guide_embed(),view=GuideView(self))
