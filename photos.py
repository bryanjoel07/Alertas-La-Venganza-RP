"""Photo of the week in the existing Fotos channel. Original posts stay intact."""
import asyncio
from datetime import datetime, timezone
import io
import json
import logging
import mimetypes
import os
from pathlib import Path
import time
from urllib.parse import urlsplit,unquote

import discord
from discord import app_commands

from economy_store import SLOTS
from photo_store import PhotoStore, week_bounds
from photo_members import MemberDirectory,DirectoryUnavailable,MemberPicker,NativePickerFallback

log = logging.getLogger('LaVenganzaRP.photos')
FOTOS_CHANNEL = 1513422142014754976
COLOR = 0xD60000
MAX_UPLOAD = 25 * 1024 * 1024
IMAGE_TYPES = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif'}
PANEL_TITLE = '📸 FOTO DE LA SEMANA | LA VENGANZA RP'


def is_image(attachment):
    return Path(attachment.filename).suffix.lower() in IMAGE_TYPES and (
        (attachment.content_type or '').startswith('image/') or (attachment.width and attachment.height))


def images(message,include_inline=False,filename=None,exclude=None):
    result=[a for a in message.attachments if is_image(a)]
    if not include_inline:return result
    # Discord hides files used by attachment:// embeds from message.attachments.
    # Recover only Discord CDN images in this channel; never fetch external embed URLs.
    state=getattr(message,'_state',None)
    if state is None:return result
    known={a.id for a in result}
    for embed in message.embeds:
        image=embed.image
        url=image.url
        if not url:continue
        parsed=urlsplit(url);parts=parsed.path.split('/')
        if parsed.scheme!='https' or parsed.hostname not in ('cdn.discordapp.com','media.discordapp.net'):continue
        if len(parts)!=5 or parts[1]!='attachments' or parts[2]!=str(FOTOS_CHANNEL) or not parts[3].isdigit():continue
        uid=int(parts[3]);name=unquote(parts[4])
        if uid in known or uid==exclude or (filename is not None and name!=filename) or Path(name).suffix.lower() not in IMAGE_TYPES:continue
        proxy=image.proxy_url or url
        proxy_parts=urlsplit(proxy)
        if proxy_parts.scheme!='https' or proxy_parts.hostname not in ('cdn.discordapp.com','media.discordapp.net'):
            proxy=url
        attached=discord.Attachment(data=dict(id=str(uid),filename=name,size=0,url=url,proxy_url=proxy,
            content_type=mimetypes.guess_type(name)[0],width=image.width,height=image.height),state=state)
        result.append(attached);known.add(uid)
    return result


def image_reference(message,fallback,filename=None,exclude=None):
    attached=images(message,include_inline=True,filename=filename,exclude=exclude) if message is not None else []
    return 'attachment://'+attached[0].filename if attached else fallback


def closed(entry, now=None):
    return not entry['active'] or entry['week_state'] != 'open' or (int(time.time()) if now is None else now) >= entry['ends']


async def answer(i, text, **kwargs):
    sender = i.followup.send if i.response.is_done() else i.response.send_message
    return await sender(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(), **kwargs)


class PhotoButton(discord.ui.DynamicItem[discord.ui.Button], template=r'lv:photo:(?P<entry>[0-9]+):(?P<action>vote|remove)'):
    def __init__(self, entry, action, count=0, disabled=False):
        super().__init__(discord.ui.Button(
            label=f'Votar · {count}' if action == 'vote' else 'Quitar voto',
            emoji='❤️' if action == 'vote' else '↩️', custom_id=f'lv:photo:{entry}:{action}',
            style=discord.ButtonStyle.secondary, disabled=disabled))
        self.entry, self.action = entry, action

    @classmethod
    async def from_custom_id(cls, i, item, match):
        return cls(int(match['entry']), match['action'])

    async def callback(self, i):
        await i.response.defer(ephemeral=True)
        try:
            await i.client.photos.vote(i, self.entry, self.action == 'vote')
        except ValueError as error:
            await answer(i, str(error))
        except discord.HTTPException:
            await answer(i, 'No pudimos actualizar la votación ahora. Inténtalo otra vez.')
        except Exception:
            log.exception('PHOTOS vote_error entry=%s', self.entry)
            await answer(i, 'No pudimos completar el voto ahora. Inténtalo otra vez.')


class UploadButton(discord.ui.DynamicItem[discord.ui.Button], template=r'lv:photo:upload'):
    def __init__(self):
        super().__init__(discord.ui.Button(label='Subir foto',emoji='📸',custom_id='lv:photo:upload',style=discord.ButtonStyle.primary))

    @classmethod
    async def from_custom_id(cls, i, item, match):
        return cls()

    async def callback(self, i):
        try:
            await i.client.photos.open_upload(i)
        except ValueError as error:
            await answer(i,str(error))
        except discord.HTTPException:
            await answer(i,'No pudimos abrir la subida ahora. Inténtalo otra vez.')


class UploadForm(discord.ui.Modal):
    def __init__(self, system, selected_users=None):
        super().__init__(title='Subir tu foto',timeout=600)
        self.system=system
        self.photo=discord.ui.FileUpload(custom_id='photo',min_values=1,max_values=1)
        self.caption=discord.ui.TextInput(custom_id='caption',style=discord.TextStyle.paragraph,required=False,max_length=500,placeholder='Un título o lo que quieras contar de tu foto.')
        self.selected_users=tuple(selected_users or ())
        self.mentions=discord.ui.UserSelect(custom_id='mentions',placeholder='Busca por nombre (opcional)',min_values=0,max_values=5,required=False) if selected_users is None else None
        self.add_item(discord.ui.Label(text='Elige tu foto',component=self.photo))
        summary=('Menciones: '+', '.join(m.display_name for m in self.selected_users))[:100] if self.selected_users else 'Sin menciones.'
        self.add_item(discord.ui.Label(text='¿Quieres ponerle un texto?',description=summary if selected_users is not None else None,component=self.caption))
        if self.mentions is not None:
            self.add_item(discord.ui.Label(text='¿Quieres mencionar a alguien?',component=self.mentions))

    async def on_submit(self,i):
        await i.response.defer(ephemeral=True,thinking=True)
        try:
            if len(self.photo.values)!=1:
                raise ValueError('Elige una foto para subirla, bro.')
            await self.system.submit_upload(i,self.photo.values[0],self.caption.value,self.mentions.values if self.mentions is not None else self.selected_users)
        except ValueError as error:
            await answer(i,str(error))
        except discord.HTTPException:
            await answer(i,'La foto quedó pendiente si alcanzó a guardarse. El bot volverá a intentar publicarla.')

    async def on_error(self,i,error):
        log.error('PHOTOS upload_error',exc_info=error)
        await answer(i,'No pudimos completar la subida. Revisa /foto semana antes de intentarlo otra vez.')


class PhotoUploadPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(UploadButton())


class PhotoControls(discord.ui.View):
    def __init__(self, entry, count=0, disabled=False):
        super().__init__(timeout=None)
        self.add_item(PhotoButton(entry, 'vote', count, disabled))
        self.add_item(PhotoButton(entry, 'remove', count, disabled))
        self.add_item(UploadButton())


class PhotoSystem:
    def __init__(self, bot, path, guild_id):
        self.bot, self.guild_id = bot, guild_id
        self.photo_channel_id=FOTOS_CHANNEL
        self.member_directory=MemberDirectory(bot,guild_id)
        self.store = PhotoStore(path)
        self.lock = asyncio.Lock()
        self.ready_lock = asyncio.Lock()
        self.prepared = False
        self.task = None
        self.group = app_commands.Group(name='foto', description='Fotos, votos y premios semanales para la tienda')
        self.register()

    def enabled(self):
        return os.getenv('PHOTO_CONTEST_ENABLED', '1') == '1'

    async def call(self, method, *args, **kwargs):
        return await asyncio.to_thread(getattr(self.store, method), *args, **kwargs)

    async def start(self):
        await self.call('initialize')
        self.bot.add_dynamic_items(PhotoButton,UploadButton)
        self.task = asyncio.create_task(self.loop(), name='photo-of-the-week')

    async def channel(self):
        channel = await self.bot.fetch_channel(FOTOS_CHANNEL)
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild_id:
            raise ValueError('El canal de Fotos no corresponde a La Venganza RP.')
        return channel

    def source_link(self, entry):
        target=entry['control'] if entry.get('post_mode')=='post' and entry['control'] else entry['source']
        return f"https://discord.com/channels/{self.guild_id}/{FOTOS_CHANNEL}/{target}"

    def control_embed(self, row, message=None):
        embed = discord.Embed(title=f"📸 Foto #{row['id']} · Votación semanal", color=COLOR,
            description=f"Publicada por <@{row['author']}> · **{row['votes']} votos**\n" +
                ('Votación cerrada.' if closed(row) else f"Cierra <t:{row['ends']}:F>.") +
                (f"\n[Ver la foto]({self.source_link(row)})" if row.get('post_mode','reply')=='reply' else ''))
        if row.get('post_mode') in ('pending','post'):
            embed.set_image(url=image_reference(message,row['url'],filename=f"foto-{row['id']}{Path(row['filename']).suffix.lower()}",
                exclude=row['attachment'] if row['source']!=row.get('control') else None))
            if row.get('caption'):
                embed.description=discord.utils.escape_markdown(row['caption'])+'\n\n'+embed.description
        else:
            embed.set_thumbnail(url=row['url'])
        embed.set_footer(text=f"La Venganza RP · Foto #{row['id']} · {row['week']}")
        return embed

    def panel_embed(self, week):
        embed = discord.Embed(title=PANEL_TITLE, color=COLOR, description=
            'Pulsa **📸 Subir foto**. Primero puedes elegir a quién mencionar en la lista o usar **Buscar**; después pulsa **Elegir foto** para subir la imagen y su texto. Tu foto aparecerá con tu nombre y los botones **❤️ Votar** y **↩️ Quitar voto** en la misma publicación.\n\n'
            'Puedes votar una vez por cada foto de los demás y cambiar de opinión quitando tu voto. '
            'Las fotos compiten de lunes a domingo, hora de Puerto Rico. '
            'Al terminar la semana destacamos la más votada con el nombre de quien la publicó. '
            'Si empatan, gana la que se publicó primero.\n\n'
            f"**Cierre de esta semana:** <t:{week['ends']}:F>\n"
            'Usa `/foto semana` para ver cómo va la votación.')
        embed.add_field(name='🪙 Premios de la semana',value=
            '\n'.join(f'{medal} **{coins} monedas**' for medal,coins in zip(('🥇','🥈','🥉'),self.store.reward_rates(week['week'])))+
            '\nUn puesto por jugador: cuenta tu foto más votada, con al menos un voto. '
            'Al cerrar la semana, las monedas van directo a tu saldo para comprar cosas para tu perfil. '
            'Mira tus monedas con `/saldo`.',inline=False)
        if week['prize_name']:
            embed.add_field(name='🎁 Extra para el primer lugar', value=week['prize_name'], inline=False)
        embed.set_footer(text='LA VENGANZA RP · Fotos de la semana')
        return embed

    async def pin(self, message, value=True):
        if message.author.id != self.bot.user.id or message.channel.id != FOTOS_CHANNEL:
            return
        winner = await self.call('announced_winner', message.id)
        if value and (not winner or winner['ends'] > int(time.time())):
            raise ValueError('Solo se fija la foto ganadora después del cierre semanal.')
        if not value and not winner and not any(e.title == PANEL_TITLE for e in message.embeds):
            return
        if message.pinned == value:
            return
        async def snapshot():
            current = await message.channel.fetch_message(message.id)
            return {'channel': message.channel.id, 'message': message.id, 'pinned': current.pinned}
        async def operation():
            if value:
                await message.pin(reason='Foto de la semana solicitada por el propietario')
            else:
                await message.unpin(reason='Reservar los destacados para las fotos ganadoras al cerrar la semana')
        await self.bot.changes.tracked('PHOTO_PIN', 'Destacar publicación de Fotos', operation,
            request_id=f"{message.id}:{int(value)}", snapshot=snapshot)

    async def panel(self, channel):
        week = await self.call('current')
        message = None
        saved = self.store.config('panel')
        if saved:
            try:
                message = await channel.fetch_message(int(saved))
            except discord.NotFound:
                pass
        if not message:
            async for previous in channel.history(limit=100):
                if previous.author.id == self.bot.user.id and any(e.title == PANEL_TITLE for e in previous.embeds):
                    message = previous
                    break
        if message and message.author.id != self.bot.user.id:
            raise ValueError('El panel guardado no pertenece a este bot.')
        if message:
            await message.edit(embed=self.panel_embed(week), view=PhotoUploadPanel(), allowed_mentions=discord.AllowedMentions.none())
        else:
            message = await channel.send(embed=self.panel_embed(week), view=PhotoUploadPanel(), allowed_mentions=discord.AllowedMentions.none())
        self.store.config('panel', message.id)
        self.store.config('panel_week', week['week'])
        if message.pinned:
            await self.pin(message, False)
            confirmed = await channel.fetch_message(message.id)
            if confirmed.pinned:
                raise RuntimeError('Discord no confirmó que el panel quedó sin fijar.')
            log.info('PHOTOS panel_unpinned channel=%s message=%s winner_only=True', channel.id, message.id)

    async def source(self, channel, row):
        try:
            message = await channel.fetch_message(row['source'])
        except discord.NotFound:
            await self.call('deleted', row['source'])
            return None, None
        own_post=row.get('post_mode')=='post' and row['source']==row['control'] and message.author.id==self.bot.user.id
        if message.author.id != row['author'] and not own_post:
            raise ValueError('La publicación de la foto no coincide con su autor.')
        attachments = images(message,include_inline=own_post,filename=f"foto-{row['id']}{Path(row['filename']).suffix.lower()}" if own_post else None)
        await self.call('sync_source', message.id, {a.id for a in attachments})
        item = next((a for a in attachments if a.id == row['attachment']), None)
        if item:
            row['url'] = item.url
            await self.call('image_url', row['id'], item.url)
        return message, item

    async def upload_channel(self,i):
        if not self.enabled() or i.guild_id!=self.guild_id or i.channel_id!=FOTOS_CHANNEL or i.user.bot:
            raise ValueError('Usa 📸 Subir foto dentro del canal de Fotos de La Venganza RP.')
        channel=await self.channel()
        permissions=channel.permissions_for(i.user)
        if not permissions.view_channel or not permissions.send_messages:
            raise ValueError('Necesitas poder escribir en Fotos para subir una foto.')
        return channel

    async def open_upload(self,i):
        channel=await self.upload_channel(i)
        await i.response.defer(ephemeral=True,thinking=True)
        try:
            members=await self.member_directory.load(channel.guild)
        except DirectoryUnavailable as error:
            log.warning('PHOTOS member_directory_unavailable reason=%s status=%s',error.reason,error.status)
            return await answer(i,'No pudimos cargar la lista completa ahora. Puedes continuar con el selector de Discord mientras se revisa.',view=NativePickerFallback(self,i.user.id))
        visible=[m for m in members if channel.permissions_for(m).view_channel]
        picker=MemberPicker(self,i.user.id,visible)
        await answer(i,picker.content(),view=picker)

    async def show_upload_form(self,i,selected):
        await self.upload_channel(i)
        await i.response.send_modal(UploadForm(self,selected))

    async def submit_upload(self,i,attachment,caption='',mentions=()):
        channel=await self.upload_channel(i)
        selected=[]
        if len(mentions)>5:
            raise ValueError('Puedes mencionar hasta 5 personas en tu foto.')
        for user in mentions:
            uid=getattr(user,'id',None)
            if not isinstance(uid,int) or uid<=0:
                raise ValueError('Elige a las personas desde el campo de menciones.')
            try:member=await channel.guild.fetch_member(uid)
            except discord.NotFound:raise ValueError('Esa persona ya no está en el servidor.') from None
            if not channel.permissions_for(member).view_channel:
                raise ValueError('Esa persona no puede ver el canal de Fotos.')
            if uid not in selected:selected.append(uid)
        if not is_image(attachment):
            raise ValueError('Elige una imagen JPG, PNG, WEBP, GIF o AVIF.')
        limit=min(channel.guild.filesize_limit,MAX_UPLOAD)
        if not 0<attachment.size<=limit:
            raise ValueError(f'El bot puede subir fotos de hasta {limit//1048576} MB. Usa una foto más ligera, bro.')
        data=await attachment.read()
        if not data or len(data)>limit:
            raise ValueError('La foto supera lo que puede publicar el bot. Usa una más ligera.')
        async with self.lock:
            entry=await self.call('upload',i.id,attachment.id,i.user.id,attachment.filename,attachment.url,data,caption.strip(),mentions=selected)
            message=await self.ensure_post(await self.call('entry',entry),channel)
        await answer(i,f'📸 Tu foto ya está publicada con tus votos: {self.source_link(self.store.entry(entry))}')
        log.info('PHOTOS upload_published entry=%s message=%s owner=%s',entry,message.id,i.user.id)

    async def cleanup_legacy(self,row,channel):
        old_id=row.get('retired_control')
        if not old_id or old_id in (row['source'],row['control']):
            return
        try:
            old=await channel.fetch_message(old_id)
        except discord.NotFound:
            await self.call('retired',row['id']);return
        ids=[getattr(c,'custom_id',None) for r in old.components for c in r.children]
        if old.author.id!=self.bot.user.id or old.attachments or f"lv:photo:{row['id']}:vote" not in ids or not old.reference or old.reference.message_id!=row['source']:
            log.warning('PHOTOS legacy_cleanup_skipped entry=%s message=%s',row['id'],old_id)
            return
        async def snapshot():
            try:
                current=await channel.fetch_message(old_id)
                return {'channel':channel.id,'message':old_id,'author':current.author.id,'content':current.content,
                    'embeds':[e.to_dict() for e in current.embeds],'components':[r.to_dict() for r in current.components]}
            except discord.NotFound:
                return {'channel':channel.id,'message':old_id,'deleted':True}
        async def remove():
            try:await old.delete()
            except discord.NotFound:pass
        await self.bot.changes.tracked('PHOTO_LEGACY_CONTROL','Reemplazar respuesta de votos por foto completa',remove,
            request_id=str(old_id),snapshot=snapshot)
        await self.call('retired',row['id'])
        log.info('PHOTOS legacy_card_replaced entry=%s old_reply=%s photo_post=%s votes=%s original_preserved=True',
            row['id'],old_id,row['control'],row['votes'])

    async def ensure_post(self,row,channel):
        if row['post_mode']=='post':
            message=await channel.fetch_message(row['control'])
        else:
            message=None
            if row['post_started']:
                after=datetime.fromtimestamp(row['post_started']-5,timezone.utc)
                async for candidate in channel.history(after=after,oldest_first=True,limit=None):
                    ids=[getattr(c,'custom_id',None) for r in candidate.components for c in r.children]
                    if candidate.author.id==self.bot.user.id and not candidate.reference and f"lv:photo:{row['id']}:vote" in ids:
                        message=candidate;break
            if not message:
                await self.call('posting',row['id'])
                row=await self.call('entry',row['id'])
                kwargs={}
                embed=self.control_embed(row)
                if row['media'] is not None:
                    filename=f"foto-{row['id']}{Path(row['filename']).suffix.lower()}"
                    embed.set_image(url='attachment://'+filename)
                    kwargs['file']=discord.File(io.BytesIO(row['media']),filename=filename)
                elif row['upload_key']:
                    raise ValueError('No encontramos la imagen de esta subida. Vuelve a subirla, bro.')
                mentions=json.loads(row['mentions'])
                message=await channel.send(content=' '.join(f'<@{uid}>' for uid in mentions) or None,
                    embed=embed,view=PhotoControls(row['id'],row['votes'],closed(row)),
                    allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=uid) for uid in mentions],roles=False,everyone=False,replied_user=False),**kwargs)
            confirmed=await channel.fetch_message(message.id)
            if confirmed.reference or not any(e.image.url for e in confirmed.embeds):
                raise RuntimeError('Discord no confirmó la publicación de foto con votos.')
            files=images(confirmed,include_inline=True,filename=f"foto-{row['id']}{Path(row['filename']).suffix.lower()}",
                exclude=row['attachment'] if not row['upload_key'] else None)
            attached=files[0] if files else None
            await self.call('posted',row['id'],confirmed.id,attached.id if attached else row['attachment'],attached.url if attached else row['url'])
            row=await self.call('entry',row['id'])
            message=confirmed
        if message.author.id!=self.bot.user.id:
            raise ValueError('Esta publicación no pertenece al bot.')
        if message.attachments:
            row['url']=message.attachments[0].url
        edit={'embed':self.control_embed(row,message),'view':PhotoControls(row['id'],row['votes'],closed(row)),
            'allowed_mentions':discord.AllowedMentions.none()}
        content=' '.join(f'<@{uid}>' for uid in json.loads(row['mentions']))
        if (message.content or '')!=content:
            edit['content']=content or None
        await message.edit(**edit)
        self.store.config(f'image_layout_v2:{message.id}','1')
        await self.call('rendered',row['id'],row['votes'],closed(row))
        await self.cleanup_legacy(row,channel)
        return message

    async def ensure_control(self, row, source):
        if row['post_mode']=='reply':
            image=next((a for a in images(source) if a.id==row['attachment']),None)
            if not image:
                raise ValueError('La foto original ya no está disponible.')
            data=None
            if image.size<=min(source.guild.filesize_limit,MAX_UPLOAD):
                data=await image.read()
            await self.call('stage_post',row['id'],data)
            row=await self.call('entry',row['id'])
        return await self.ensure_post(row,source.channel)

    async def observe(self, message):
        if not self.enabled() or not message.guild or message.guild.id != self.guild_id or message.channel.id != FOTOS_CHANNEL or message.author.bot:
            return
        async with self.lock:
            attachments = images(message)
            await self.call('sync_source', message.id, {a.id for a in attachments})

    async def edited(self, payload):
        if self.enabled() and payload.guild_id == self.guild_id and payload.channel_id == FOTOS_CHANNEL:
            channel = await self.channel()
            try:
                await self.observe(await channel.fetch_message(payload.message_id))
            except discord.NotFound:
                await self.call('deleted', payload.message_id)

    async def deleted(self, guild, channel, messages):
        if self.enabled() and guild == self.guild_id and channel == FOTOS_CHANNEL:
            for message in messages:
                await self.call('deleted', message)

    async def scan(self, channel):
        week, start, _ = week_bounds(int(time.time()))
        cursor = self.store.config('cursor') if self.store.config('scan_week') == week else ''
        after = discord.Object(id=int(cursor)) if cursor else datetime.fromtimestamp(start, timezone.utc)
        async for message in channel.history(after=after, oldest_first=True, limit=None):
            await self.observe(message)
            self.store.config('cursor', message.id)
            self.store.config('scan_week', week)

    async def refresh_controls(self, channel):
        for row in await self.call('refresh_entries', int(time.time())):
            if row['control'] and row['rendered_count'] == row['votes'] and row['rendered_closed'] == int(closed(row)):
                continue
            try:
                async with self.lock:
                    row = await self.call('entry', row['id'])
                    if row['post_mode']=='pending':
                        if row['active']:
                            await self.ensure_post(row,channel)
                    elif row['control']:
                        message = await channel.fetch_message(row['control'])
                        if message.author.id != self.bot.user.id:
                            raise ValueError('Ese mensaje no pertenece al bot.')
                        if row['post_mode']=='post' and message.attachments:
                            row['url']=message.attachments[0].url
                        await message.edit(embed=self.control_embed(row,message),
                            view=PhotoControls(row['id'], row['votes'], closed(row)), allowed_mentions=discord.AllowedMentions.none())
                        self.store.config(f'image_layout_v2:{message.id}','1')
                        await self.call('rendered', row['id'], row['votes'], closed(row))
                    elif not closed(row):
                        source, image = await self.source(channel, row)
                        if source and image:
                            await self.ensure_control(row, source)
                    else:
                        await self.call('rendered', row['id'], row['votes'], True)
            except discord.NotFound:
                await self.call('deleted', row['control'])
            except Exception:
                log.exception('PHOTOS control_refresh_pending entry=%s', row['id'])

    async def vote(self, i, entry, add):
        if not self.enabled() or i.guild_id != self.guild_id or i.channel_id != FOTOS_CHANNEL or i.user.bot:
            raise ValueError('Vota desde la foto en el canal de Fotos de La Venganza RP.')
        async with self.lock:
            row = await self.call('entry', entry)
            if not row or not i.message or i.message.id != row['control']:
                raise ValueError('Este control de votos ya no está disponible.')
            channel = await self.channel()
            if not channel.permissions_for(i.user).view_channel:
                raise ValueError('No tienes acceso a esta votación.')
            source, image = await self.source(channel, row)
            if not source or not image:
                raise ValueError('La foto fue retirada y ya no participa.')
            changed = await self.call('vote', entry, i.user.id, add)
            current = await self.call('entry', entry)
            try:
                await self.ensure_control(current, source)
            except discord.HTTPException:
                log.warning('PHOTOS count_update_pending entry=%s', entry)
        await answer(i, ('❤️ Tu voto quedó guardado.' if add else 'Quitaste tu voto.') if changed else
            ('Ya votaste por esta foto.' if add else 'No tenías un voto en esta foto.'))

    def winner_embed(self, week, message=None):
        row = self.store.entry(week['winner']) if week['winner'] else None
        if row:
            embed = discord.Embed(title='🏆 FOTO DE LA SEMANA | LA VENGANZA RP', color=COLOR,
                description=f"📸 Publicada por <@{row['author']}>\n❤️ **{week['winning_votes']} votos**\n[Ver la publicación original]({self.source_link(row)})")
            if week['image_url']:
                embed.set_image(url=image_reference(message,week['image_url'],filename=week['filename'],exclude=row['attachment']))
            podium=self.store.ranking(week['week']) if week['podium_closed'] is not None else []
            if podium:
                embed.add_field(name='🏅 Podio de la semana',value='\n\n'.join(
                    f"{('🥇','🥈','🥉')[r['place']-1]} <@{r['author']}> · **{r['coins']} monedas** · ❤️ {r['votes']} votos\n"
                    f"[Ver su foto]({self.source_link(r)})" for r in podium),inline=False)
                shop=self.bot.economy.store.config('shop_channel')
                embed.add_field(name='🛍️ A disfrutar esos premios',value=
                    'Las monedas ya están en sus saldos. Usa `/saldo` para verlas y '+
                    (f'pásate por <#{shop}>' if shop else 'pásate por la tienda')+
                    ' para comprar cosas para tu perfil.',inline=False)
            if week['prize_name']:
                embed.add_field(name='🎁 Extra para el primer lugar', value=week['prize_name'] + ('\nYa está en tu inventario. Usa `/inventario` para verlo.' if week['prize_receipt'] else '\nEl staff está pendiente de su entrega.'), inline=False)
        else:
            embed = discord.Embed(title='📸 FOTO DE LA SEMANA', color=COLOR,
                description='Esta semana no hubo fotos con votos para elegir una ganadora. La nueva ronda ya está abierta: ¡sube tu foto y participa!')
        embed.add_field(name='Semana', value=f"<t:{week['starts']}:d> — <t:{week['ends']-1}:d>", inline=False)
        embed.set_footer(text=f"LA VENGANZA RP · Foto de la semana · {week['week']}")
        return embed

    async def settle(self, channel, week):
        async with self.lock:
            week=await self.call('week',week['week'])
            if not week or week['state']=='published' or week['ends']>int(time.time()):return
            rows = await self.call('entries', week['week'])
            if week['podium_closed'] is None:
                winner_image=None;eligible=[];authors=set()
                for row in rows:
                    if row['active'] and row['votes'] and row['author'] not in authors:
                        _,image=await self.source(channel,row)
                        if image:
                            authors.add(row['author']);eligible.append((row['id'],row['author'],row['votes']))
                            if winner_image is None:winner_image=image
                            if len(eligible)==3:break
                week=await self.call('freeze',week['week'])
                media=None
                if eligible:
                    limit=min(getattr(channel.guild,'filesize_limit',MAX_UPLOAD),MAX_UPLOAD)
                    data=None
                    if winner_image.size<=limit:
                        try:data=await winner_image.read()
                        except discord.HTTPException:data=await winner_image.read(use_cached=True)
                        if len(data)>limit:data=None
                    filename=f"foto-{eligible[0][0]}{Path(winner_image.filename).suffix.lower()}"
                    media=(data,filename,winner_image.url)
                podium=await self.call('reward_podium',week['week'],self.bot.user.id,expected=eligible,media=media)
                week = await self.call('week', week['week'])
                if week['podium_closed'] is None and week['winner'] and media:
                    if week['winner']!=eligible[0][0]:
                        raise ValueError('Las fotos cambiaron mientras cerraba la semana. Se revisarán otra vez.')
                    await self.call('stage',week['week'],*media)
                    week=await self.call('week',week['week'])
                if week['podium_closed'] is not None:
                    log.info('PHOTOS podium_paid week=%s places=%s users=%s coins=%s',week['week'],len(podium),
                        [r['author'] for r in podium],[r['coins'] for r in podium])
            if not rows:
                await self.call('published', week['week'], None)
                return
            message = None
            if week['publishing']:
                after = datetime.fromtimestamp(week['publishing'] - 5, timezone.utc)
                marker = f"LA VENGANZA RP · Foto de la semana · {week['week']}"
                async for previous in channel.history(after=after, oldest_first=True, limit=None):
                    if previous.author.id == self.bot.user.id and any(e.footer.text == marker for e in previous.embeds):
                        message = previous
                        break
            if not message:
                await self.call('publishing', week['week'], int(time.time()))
                embed = self.winner_embed(week)
                kwargs = {}
                if week['image'] is not None:
                    embed.set_image(url='attachment://' + week['filename'])
                    kwargs['file'] = discord.File(io.BytesIO(week['image']), filename=week['filename'])
                row = self.store.entry(week['winner']) if week['winner'] else None
                podium=self.store.ranking(week['week']) if week['podium_closed'] is not None else []
                winners=[r['author'] for r in podium] or ([row['author']] if row else [])
                content=('🏆 ¡Ya tenemos el podio de Fotos de esta semana! '+
                    ' '.join(f'<@{uid}>' for uid in winners)+' 🎉') if podium else (f"🏆 <@{row['author']}>, ¡tu foto ganó esta semana!" if row else None)
                message = await channel.send(content=content,
                    embed=embed, allowed_mentions=discord.AllowedMentions(users=[discord.Object(uid) for uid in winners], roles=False, everyone=False), **kwargs)
            files=images(message,include_inline=True)
            url = files[0].url if files else week['image_url']
            await self.call('published', week['week'], message.id, url)
            log.info('PHOTOS winner_published week=%s winner=%s votes=%s message=%s', week['week'], week['winner'], week['winning_votes'], message.id)
        previous = self.store.config('winner_pin')
        if previous and int(previous) != message.id:
            try:
                old = await channel.fetch_message(int(previous))
                await self.pin(old, False)
            except discord.HTTPException:
                log.warning('PHOTOS previous_winner_unpin_pending message=%s', previous)
        if week['winner']:
            try:
                await self.pin(message)
                self.store.config('winner_pin', message.id)
            except discord.HTTPException:
                log.warning('PHOTOS winner_pin_pending message=%s', message.id)

    async def deliver_prize(self, channel, week):
        try:
            await self.call('award', week['week'], self.bot.user.id)
        except ValueError as error:
            if week['prize_error'] != str(error):
                log.warning('PHOTOS prize_pending week=%s reason=%s', week['week'], str(error))
                await self.call('prize_error', week['week'], error)
            return
        current = await self.call('week', week['week'])
        if current['announcement']:
            message = await channel.fetch_message(current['announcement'])
            if message.author.id == self.bot.user.id:
                await message.edit(embed=self.winner_embed(current,message),
                    allowed_mentions=discord.AllowedMentions.none())

    async def repair_image_layout(self,channel):
        repaired=0
        for row in await self.call('entries'):
            if row['post_mode']!='post' or not row['control']:continue
            key=f"image_layout_v2:{row['control']}"
            if self.store.config(key):continue
            try:message=await channel.fetch_message(row['control'])
            except discord.NotFound:
                self.store.config(key,'missing');continue
            if message.author.id!=self.bot.user.id or message.reference:continue
            filename=f"foto-{row['id']}{Path(row['filename']).suffix.lower()}"
            excluded=row['attachment'] if row['source']!=row['control'] else None
            attached=images(message,include_inline=True,filename=filename,exclude=excluded)
            if len(attached)!=1:continue
            marker=f"La Venganza RP · Foto #{row['id']} · {row['week']}"
            if len(message.embeds)!=1 or message.embeds[0].footer.text!=marker:continue
            ids=[getattr(c,'custom_id',None) for r in message.components for c in r.children]
            if f"lv:photo:{row['id']}:vote" not in ids:continue
            original_ids=[a.id for a in attached]
            embed=discord.Embed.from_dict(message.embeds[0].to_dict())
            embed.set_image(url=image_reference(message,row['url'],filename=filename,exclude=excluded))
            async def snapshot():
                current=await channel.fetch_message(message.id)
                stored=self.store.entry(row['id'])
                return dict(entry=row['id'],source=stored['source'],attachment=stored['attachment'],active=stored['active'],votes=stored['votes'],
                    message=current.id,content=current.content,embeds=[e.to_dict() for e in current.embeds],
                    attachments=[dict(id=a.id,filename=a.filename,url=a.url) for a in images(current,include_inline=True)],
                    components=[r.to_dict() for r in current.components])
            async def repair():
                await message.edit(embed=embed,allowed_mentions=discord.AllowedMentions.none())
                confirmed=await channel.fetch_message(message.id)
                if [a.id for a in images(confirmed,include_inline=True)]!=original_ids or len(confirmed.embeds)!=1 or not confirmed.embeds[0].image.url:
                    raise RuntimeError('Discord no confirmó la foto y su archivo después del ajuste.')
                actual=attached[0]
                filename=f"foto-{row['id']}{Path(row['filename']).suffix.lower()}"
                if row['upload_key'] and row['source']==row['control'] and row['attachment']!=actual.id and actual.filename==filename:
                    await self.call('rebind_post_image',row['id'],message.id,actual.id,actual.url)
            await self.bot.changes.tracked('PHOTO_IMAGE_LAYOUT','Mostrar la foto una sola vez dentro de su tarjeta',repair,
                request_id=f'{message.id}:v2',snapshot=snapshot)
            self.store.config(key,'1');repaired+=1
            current=self.store.entry(row['id'])
            log.info('PHOTOS image_layout_repaired entry=%s message=%s attachments=%s active=%s votes=%s '
                'inline_files=%s binding_repaired=%s reactivated=%s single_image_reference=True original_preserved=True',
                row['id'],message.id,len(attached),current['active'],current['votes'],not bool(message.attachments),
                row['attachment']!=current['attachment'],not row['active'] and bool(current['active']))
        log.info('PHOTOS image_layout_verified repaired=%s attachment_reference_on_updates=True files_preserved=True',repaired)

    async def ready(self):
        if not self.enabled():
            return
        async with self.ready_lock:
            if self.prepared:
                return
            channel = await self.channel()
            permissions = channel.permissions_for(channel.guild.me)
            if not all(getattr(permissions, p) for p in ('view_channel', 'read_message_history', 'send_messages', 'embed_links', 'attach_files')):
                raise ValueError('El bot necesita ver Fotos, leer el historial y enviar mensajes, imágenes y enlaces.')
            if Path(self.bot.economy.store.path).resolve()!=self.store.path.resolve():
                raise RuntimeError('Fotos y la tienda deben usar la misma base para entregar las monedas.')
            rewards=await self.call('reward_status')
            await self.panel(channel)
            panel=await channel.fetch_message(int(self.store.config('panel')))
            prize_field=next((f.value for e in panel.embeds for f in e.fields if f.name=='🪙 Premios de la semana'),'')
            if not all(f'{coins} monedas' in prize_field for coins in rewards['rewards']):
                raise RuntimeError('Discord no confirmó los premios de Fotos en su panel.')
            log.info('PHOTOS economy_verified rewards=%s currency=eco_accounts ledger=eco_ledger same_database=True '
                'distinct_players=True minimum_votes=1 ties=earliest_photo coins_since=%s paid_positions=%s panel_verified=True',
                list(rewards['rewards']),rewards['since'],rewards['paid_positions'])
            await self.scan(channel)
            async with self.lock:
                await self.repair_image_layout(channel)
            # Recheck existing controls after offline deletions without touching original posts.
            week = await self.call('current')
            verified = 0
            pinned_sources = []
            for row in await self.call('entries', week['week']):
                if row['active']:
                    async with self.lock:
                        if row['post_mode']=='pending':
                            message=await self.ensure_post(row,channel)
                        else:
                            source, image = await self.source(channel, row)
                            if not source or not image:
                                continue
                            if source.pinned:
                                pinned_sources.append(source.id)
                            message = await self.ensure_control(row, source)
                        confirmed = await channel.fetch_message(message.id)
                        ids = [getattr(c, 'custom_id', None) for r in confirmed.components for c in r.children]
                        if ids != [f"lv:photo:{row['id']}:vote", f"lv:photo:{row['id']}:remove",'lv:photo:upload'] or confirmed.reference:
                            raise RuntimeError('Discord no confirmó la foto y sus botones en una sola publicación.')
                        verified += 1
            commands = await self.bot.tree.fetch_commands(guild=discord.Object(id=self.guild_id))
            command = next((c.to_dict() for c in commands if c.name == 'foto'), {})
            if not {'semana', 'premio','subir','retirar'} <= {o['name'] for o in command.get('options', [])}:
                raise RuntimeError('Discord no confirmó los comandos de Fotos.')
            try:
                try:
                    members=await self.member_directory.load(channel.guild)
                except DirectoryUnavailable as error:
                    if error.reason!='permission':raise
                    try:
                        enabled=await self.member_directory.enable_member_listing()
                    except discord.HTTPException as enable_error:
                        log.warning('PHOTOS member_access_enable_failed status=%s',enable_error.status)
                        raise error from None
                    if not enabled:raise
                    log.info('PHOTOS member_access_enabled application=%s gateway_subscription_unchanged=True',self.bot.user.id)
                    members=await self.member_directory.load(channel.guild,force=True)
                log.info('PHOTOS member_directory_verified total=%s visible_in_photos=%s source=%s pages_of=25 normalized_name_search=True offline_included=True',
                    len(members),sum(channel.permissions_for(m).view_channel for m in members),self.member_directory.source)
            except DirectoryUnavailable as error:
                log.warning('PHOTOS member_directory_unavailable reason=%s status=%s',error.reason,error.status)
            log.info('PHOTOS pin_policy_verified winner_only_after_close=True panel_pinned=False current_week_pinned_sources=%s', pinned_sources)
            form=UploadForm(self).to_dict()
            if form['components'][0]['component']['type']!=19:
                raise RuntimeError('No se confirmó el selector de fotos del formulario.')
            mentions=form['components'][2]['component']
            if mentions['type']!=5 or mentions.get('required') or mentions['min_values']!=0 or mentions['max_values']!=5:
                raise RuntimeError('No se confirmó el campo opcional de menciones.')
            self.prepared = True
            log.info('PHOTOS upload_form_verified image=True optional_caption=True optional_mentions=True max_mentions=5 notify_selected_only=True')
            log.info('PHOTOS controls_verified channel=%s entries=%s buttons=vote,remove,upload commands=semana,premio,subir,retirar self_votes=False single_photo_post=True replies=False', channel.id, verified)
            log.info('PHOTOS ready channel=%s name=%s week=%s entries=%s closes=%s timezone=America/Puerto_Rico originals_preserved=True persistent_buttons=True',
                channel.id, channel.name, week['week'], len(self.store.entries(week['week'])), week['ends'])

    async def tick(self):
        channel = await self.channel()
        await self.scan(channel)
        for entry in await self.call('pending_posts'):
            try:
                async with self.lock:
                    row=await self.call('entry',entry)
                    if row['post_mode']=='pending' and row['active']:
                        await self.ensure_post(row,channel)
                    elif row['post_mode']=='post':
                        await self.cleanup_legacy(row,channel)
            except Exception:
                log.exception('PHOTOS post_pending entry=%s',entry)
        for week in await self.call('due'):
            try:
                await self.settle(channel, week)
            except Exception:
                log.exception('PHOTOS weekly_close_pending week=%s', week['week'])
        await self.refresh_controls(channel)
        for week in await self.call('pending_prizes'):
            try:
                await self.deliver_prize(channel, week)
            except discord.HTTPException:
                log.warning('PHOTOS prize_message_pending week=%s', week['week'])
        if self.store.config('panel_week') != week_bounds(int(time.time()))[0]:
            await self.panel(channel)

    async def loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            if self.enabled():
                try:
                    await self.ready()
                    await self.tick()
                except Exception:
                    log.exception('PHOTOS background_error; votes and photos preserved')
            await asyncio.sleep(60)

    def register(self):
        @self.group.command(name='subir',description='Subir una foto con tu nombre y los votos en la misma publicación')
        async def upload(i:discord.Interaction):
            await self.open_upload(i)

        @self.group.command(name='retirar',description='Retirar una foto tuya publicada por el bot')
        async def withdraw(i:discord.Interaction,foto:app_commands.Range[int,1]):
            def check(click,row):
                if click.guild_id!=self.guild_id or not row or row['post_mode']!='post' or not row['active']:
                    raise ValueError('Esa foto no está disponible para retirar.')
                if click.user.id!=row['author'] and not click.user.guild_permissions.manage_messages:
                    raise ValueError('Solo el autor o el staff que puede moderar mensajes puede retirar esta foto.')
            row=await self.call('entry',foto);check(i,row)
            from economy import Confirm
            async def confirmed(click):
                async with self.lock:
                    current=await self.call('entry',foto);check(click,current)
                    channel=await self.channel()
                    message=await channel.fetch_message(current['control'])
                    if message.author.id!=self.bot.user.id:
                        raise ValueError('Esa publicación no pertenece al bot.')
                    async def snapshot():
                        return {'entry':foto,'photo_message':current['control'],'owner':current['author'],'active':self.store.entry(foto)['active'],'votes':self.store.entry(foto)['votes']}
                    async def remove():
                        await message.delete()
                        await self.call('deleted',message.id)
                    await self.bot.changes.tracked('PHOTO_WITHDRAW','Retirar foto por petición de su autor o staff',remove,request_id=str(click.id),snapshot=snapshot)
                return 'Tu foto quedó retirada de la votación.'
            await answer(i,'¿Retirar esta foto y sacarla de la votación?',view=Confirm(i.user.id,confirmed))

        @self.group.command(name='semana', description='Ver el podio de Fotos, sus premios y cuándo cierra la semana')
        async def standings(i: discord.Interaction):
            if i.guild_id != self.guild_id:
                raise ValueError('Consulta la votación desde La Venganza RP.')
            await i.response.defer(ephemeral=True)
            week = await self.call('current')
            rows = await self.call('ranking', week['week'])
            embed = self.panel_embed(week)
            embed.add_field(name='🏅 Así va el podio',value='Todavía puede cambiar hasta que cierre la semana.' if rows else
                'Todavía no hay fotos con votos. ¡Sube la tuya y participa!',inline=False)
            for row in rows:
                embed.add_field(name=f"{('🥇','🥈','🥉')[row['place']-1]} Foto #{row['id']} · {row['votes']} votos",
                    value=f"<@{row['author']}> · **{row['coins']} monedas** si termina aquí · [Ver foto]({self.source_link(row)})",inline=False)
            await answer(i, None, embed=embed)

        @self.group.command(name='premio', description='Elegir o quitar el artículo extra para el primer lugar')
        async def prize(i: discord.Interaction, articulo: str, semana: str = None):
            self.bot.economy.authorized(i)
            await i.response.defer(ephemeral=True)
            current = await self.call('current')
            target = semana or current['week']
            sku = None if articulo == 'ninguno' else articulo
            from economy import Confirm
            async def confirmed(click):
                self.bot.economy.authorized(click)
                async with self.lock:
                    async def snapshot():
                        row = self.store.week(target)
                        return {k: row[k] for k in ('week', 'prize_sku', 'prize_actor', 'prize_receipt')} if row else {}
                    async def change():
                        await self.call('prize', target, sku, click.user.id)
                    await self.bot.changes.tracked('PHOTO_PRIZE', 'Elegir premio de Fotos', change, request_id=str(click.id), snapshot=snapshot)
                channel = await self.channel()
                row = self.store.week(target)
                if row['state'] == 'published' and row['winner']:
                    await self.deliver_prize(channel, row)
                await self.panel(channel)
                return 'Extra guardado para el primer lugar. Se entrega en su inventario, además de las monedas.' if sku else 'Esta semana queda sin artículo extra. Los premios de monedas siguen activos.'
            item = next((p for p in self.bot.economy.store.products() if p['sku'] == sku and p['active'] and p['kind'] in SLOTS), None)
            if sku and not item:
                raise ValueError('Elige un artículo de perfil del catálogo.')
            await answer(i, f"¿Guardar **{discord.utils.escape_markdown(item['name']) if item else 'Sin artículo extra'}** para el primer lugar de la semana del {target}?",
                view=Confirm(i.user.id, confirmed))

        @prize.autocomplete('articulo')
        async def prize_choices(i, current):
            self.bot.economy.authorized(i)
            products = await asyncio.to_thread(self.bot.economy.store.products)
            choices = [app_commands.Choice(name='Sin artículo extra (se mantienen las monedas)', value='ninguno')]
            choices.extend(app_commands.Choice(name=p['name'][:100], value=p['sku']) for p in products
                if p['active'] and p['kind'] in SLOTS and current.casefold() in (p['name']+' '+p['sku']).casefold())
            return choices[:25]

        @self.group.error
        async def error(i, failure):
            error = getattr(failure, 'original', failure)
            if not isinstance(error, ValueError):
                log.error('PHOTOS command_error', exc_info=error)
            await answer(i, str(error) if isinstance(error, ValueError) else 'No pudimos completar eso ahora. Inténtalo otra vez.')
