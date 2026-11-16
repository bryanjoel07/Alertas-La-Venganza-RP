"""Idempotent, journaled refresh of existing storefront panels after the first sale launch."""
import asyncio
import hashlib
import logging

import discord

from launch_content import PRODUCT, VERSION, PUBLIC_STORE_URL, panel_copy

log = logging.getLogger('EssChinoStudio.launch')
GUILD_ID = 1514871828189941881
BOT_ID = 1571639486591402174
PROTECTED = 1514871828672151573
TOPICS = {
    'welcome':'Empieza aquí · bienvenida, catálogo y compras de Community Sanctions System.',
    'rules':'Normas de compras, licencias, convivencia y soporte de Community Sanctions System.',
    'announcements':'Community Sanctions System ya está a la venta · lanzamientos oficiales EssChino.',
    'buying':'Cómo comprar Community Sanctions System en Tebex y verificar tu pedido.',
    'shop':'Community Sanctions System disponible en Tebex · compra oficial y atención por ticket.',
    'catalog':'Community Sanctions System · funciones, frameworks, requisitos e idiomas.',
    'demos':'Demostraciones oficiales de Community Sanctions System · consultas por ticket.',
    'offers':'Precios y promociones de Community Sanctions System según Tebex y sus condiciones.',
    'changelog':'Community Sanctions System · versiones, cambios y actualización conservando datos.',
    'support':'Compras, entrega, instalación, errores y verificación de clientes de Community Sanctions System.',
    'install':'Instalación de Community Sanctions System · QBCore, Qbox, ESX y standalone.',
    'faq':'Community Sanctions System · compra, entrega, requisitos, idiomas y soporte.',
    'general':'Comunidad EssChino · proyectos FiveM y Community Sanctions System.',
    'suggestions':'Mejoras para Community Sanctions System · propone una idea y vota.',
    'reviews':'Experiencias reales con Community Sanctions System tras verificar la compra.',
    'staff':'Coordinación privada del lanzamiento y soporte de Community Sanctions System.',
    'management':'Pedidos y tickets privados de Community Sanctions System · seguimiento del equipo.',
    'log':'Registro privado de soporte y verificación de compras de Community Sanctions System.',
    'direction':'Dirección privada de EssChino Studio · tienda activa y gestión del lanzamiento.',
}


class StoreLaunch:
    def __init__(self, system, panel_keys):
        self.system, self.panel_keys = system, tuple(panel_keys)
        self.lock = asyncio.Lock()

    async def ready(self, guild):
        if guild.id != GUILD_ID or self.system.bot.user.id != BOT_ID:
            raise ValueError('El lanzamiento solo corresponde al nuevo bot de EssChino Studio.')
        async with self.lock:
            if PUBLIC_STORE_URL and not self.system.store.get('shop_url'):
                from esschino import valid_shop_url
                async def snapshot_url():
                    return {'guild_id':guild.id, 'shop_url':self.system.store.get('shop_url')}
                async def configure():
                    await self.system.call('put', 'shop_url', valid_shop_url(PUBLIC_STORE_URL))
                await self.system.bot.changes.tracked('STORE_LAUNCH', 'Conectar tienda pública verificada',
                    configure, request_id=VERSION + ':store-url', snapshot=snapshot_url)
            stamp = VERSION + ':' + hashlib.sha256((self.system.store.get('shop_url') or '').encode()).hexdigest()[:12]
            updated = 0
            for key in (*self.panel_keys, 'direction', 'setup'):
                receipt = 'launch-panel:' + key
                if self.system.store.get(receipt) == stamp:
                    continue
                cid = PROTECTED if key in {'direction','setup'} else self.system.channel_id(key)
                mid = self.system.store.get('completion_message') if key == 'setup' else self.system.store.get('panel:' + key)
                if not cid or not mid:
                    raise ValueError(f'Falta el panel registrado {key}; no se creará un duplicado.')
                channel = guild.get_channel(cid) or await self.system.bot.fetch_channel(cid)
                if channel.guild.id != GUILD_ID:
                    raise ValueError('El canal del lanzamiento no pertenece a EssChino Studio.')
                message = await channel.fetch_message(mid)
                if message.author.id != BOT_ID or len(message.embeds) != 1 or message.embeds[0].fields:
                    raise ValueError('No se confirmó el panel original que se debe actualizar.')
                embed = message.embeds[0].copy()
                if key in {'direction','setup'}:
                    title, body = panel_copy(key, 'es', embed.title, embed.description, self.system.panel_values())
                else:
                    title, body = self.system.panel(key)
                embed.title, embed.description = title, body
                if len(title) > 256 or len(body) > 4096:
                    raise ValueError('El panel del lanzamiento supera los límites de Discord.')
                view = self.system.languages.attach(self.system.panel_view(key), key)
                expected_ids = {item.get('custom_id') for row in view.to_components() for item in row['components'] if item.get('custom_id')}
                expected_links = {item['url'] for row in view.to_components() for item in row['components'] if item.get('url')}
                topic = TOPICS.get(key)

                async def snapshot(channel=channel, mid=mid, receipt=receipt):
                    saved = await channel.fetch_message(mid)
                    current = await self.system.bot.fetch_channel(channel.id)
                    return {'guild_id':guild.id, 'channel_id':channel.id, 'message_id':mid,
                        'topic':current.topic, 'receipt':self.system.store.get(receipt),
                        'content':saved.content, 'embeds':[e.to_dict() for e in saved.embeds],
                        'components':[row.to_dict() for row in saved.components],
                        'attachments':[{'id':a.id,'filename':a.filename,'url':a.url,'size':a.size} for a in saved.attachments],
                        'overwrites':[{'id':str(o.id),'type':o.type,'allow':str(o.allow),'deny':str(o.deny)} for o in current._overwrites]}

                async def apply(message=message, embed=embed, view=view, channel=channel, topic=topic,
                                mid=mid, receipt=receipt, expected_ids=expected_ids, expected_links=expected_links):
                    # Omit attachments entirely so Discord retains the existing banner.
                    await message.edit(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
                    if topic and channel.topic != topic:
                        await channel.edit(topic=topic, reason='Lanzamiento de Community Sanctions System solicitado por el propietario')
                    confirmed = await channel.fetch_message(mid)
                    controls = [item for row in confirmed.components for item in row.children]
                    if (confirmed.embeds[0].title, confirmed.embeds[0].description) != (embed.title, embed.description):
                        raise ValueError('Discord no confirmó el texto del lanzamiento.')
                    if not expected_ids.issubset({getattr(item,'custom_id',None) for item in controls}):
                        raise ValueError('Discord no confirmó los controles e idiomas del panel.')
                    if expected_links != {item.url for item in controls if getattr(item,'url',None)}:
                        raise ValueError('Discord no confirmó los enlaces de compra.')
                    if embed.image.url and not confirmed.embeds[0].image.url:
                        raise ValueError('No se confirmó la imagen anterior del panel.')
                    await self.system.call('put', receipt, stamp)

                await self.system.bot.changes.tracked('STORE_LAUNCH', 'Actualizar para la venta el panel ' + key,
                    apply, request_id=f'{stamp}:{key}:{mid}', snapshot=snapshot)
                updated += 1
            await self.system.call('put','store_launch', stamp)
            log.info('STORE_LAUNCH_READY guild=%s panels=%s updated=%s product=%s public_shop=%s',
                guild.id, len(self.panel_keys) + 2, updated, PRODUCT, bool(self.system.store.get('shop_url')))
