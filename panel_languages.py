"""Private translations of official panels, with the public Spanish copy intact."""
import logging

import discord

from panel_translations import LANGUAGES, TRANSLATIONS, UI_TEXT

log = logging.getLogger('EssChinoStudio.languages')
GUILD_ID = 1514871828189941881
VERSION = 'panel-languages-v1'


class LanguageButton(discord.ui.DynamicItem[discord.ui.Button],
        template=r'ec:lang:(?P<panel>[a-z_]+):(?P<language>en|pt-BR|fr|de)'):
    def __init__(self, panel, language):
        metadata = next(item for item in LANGUAGES if item['code'] == language)
        self.panel, self.language = panel, language
        super().__init__(discord.ui.Button(label=metadata['name'], emoji=metadata['emoji'],
            custom_id=f'ec:lang:{panel}:{language}', style=discord.ButtonStyle.secondary))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['panel'], match['language'])

    async def callback(self, interaction):
        try:
            await interaction.client.esschino.languages.show(interaction, self.panel, self.language)
        except Exception as error:
            log.error('PANEL_LANGUAGES interaction_failed type=%s', type(error).__name__, exc_info=error)
            send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
            await send(str(error) if isinstance(error, ValueError) else 'No se pudo cargar la traducción. Inténtalo de nuevo.', ephemeral=True)


class PanelLanguages:
    def __init__(self, system):
        self.system = system

    def start(self):
        self.system.bot.add_dynamic_items(LanguageButton)

    def attach(self, view, key, language='es'):
        if key not in TRANSLATIONS['en']:
            raise ValueError('El panel no tiene traducciones registradas.')
        view = view or discord.ui.View(timeout=None)
        # Real callbacks stay on their original View; never clone controls with
        # View.from_message, which would replace their behavior with empty callbacks.
        for index, item in enumerate(view.children):
            item.row = 0 if isinstance(item, discord.ui.Select) else index // 5
            if language != 'es' and isinstance(item, discord.ui.Button) and item.label:
                item.label = UI_TEXT[language].get(item.label, item.label)
            if language != 'es' and isinstance(item, discord.ui.Select):
                item.placeholder = UI_TEXT[language].get(item.placeholder, item.placeholder)
                for option in item.options:
                    option.label = UI_TEXT[language].get(option.label, option.label)
        row = max((item.row for item in view.children), default=-1) + 1
        for metadata in LANGUAGES:
            button = LanguageButton(key, metadata['code'])
            button.row = row
            if metadata['code'] == language:
                button.item.style = discord.ButtonStyle.primary
            view.add_item(button)
        return view

    def channel_id(self, key):
        return 1514871828672151573 if key in {'direction', 'setup'} else self.system.channel_id(key)

    def message_id(self, key):
        return self.system.store.get('completion_message') if key == 'setup' else self.system.store.get('panel:' + key)

    def translated_embed(self, key, language, source):
        title, body = TRANSLATIONS[language][key]
        values = {name: f'<#{self.system.channel_id(name)}>' for name in
                  ('welcome','rules','catalog','demos','shop','support','changelog','install','suggestions','reviews')}
        url = self.system.store.get('shop_url')
        values['shop_url'] = url or ''
        values['shop_intro'] = TRANSLATIONS[language]['shop_configured' if url else 'shop_pending'][1].format_map(values)
        values['setup_shop'] = TRANSLATIONS[language]['setup_configured' if url else 'setup_pending'][1]
        embed = source.embeds[0].copy()
        embed.title, embed.description = title, body.format_map(values)
        if embed.fields:
            raise ValueError('Este panel contiene campos nuevos que todavía no tienen traducción.')
        embed.set_footer(text='EssChino Studio · ' + next(x['name'] for x in LANGUAGES if x['code'] == language))
        # An ephemeral copy must use the signed attachment URL, not an attachment
        # reference belonging to a different message. The original files stay put.
        for name in ('image', 'thumbnail'):
            url = getattr(embed, name).url
            if url and url.startswith('attachment://'):
                filename = url.split('://', 1)[1]
                attachment = next((a for a in source.attachments if a.filename == filename), None)
                if attachment:
                    getattr(embed, 'set_' + name)(url=attachment.url)
        return embed

    async def show(self, i, key, language):
        if (i.guild_id != GUILD_ID or not isinstance(i.user, discord.Member) or i.user.bot
                or language not in TRANSLATIONS or key not in TRANSLATIONS[language]
                or i.message.author.id != self.system.bot.user.id):
            raise ValueError('Este botón pertenece a los paneles de EssChino Studio.')
        cid, mid = self.channel_id(key), self.message_id(key)
        if i.channel_id != cid or not mid:
            raise ValueError('No se confirmó el panel original de esta traducción.')
        channel = i.guild.get_channel(cid)
        if channel is None:
            channel = await self.system.bot.fetch_channel(cid)
        if channel.guild.id != GUILD_ID:
            raise ValueError('El panel no pertenece al servidor EssChino Studio.')
        permissions = channel.permissions_for(i.user)
        if not permissions.view_channel or not permissions.read_message_history:
            raise ValueError('No tienes acceso al panel original.')
        private_copy = i.message.flags.ephemeral
        if not private_copy and i.message.id != mid:
            raise ValueError('Esta publicación no es el panel oficial registrado.')
        await i.response.defer(ephemeral=True, thinking=not private_copy)
        source = await channel.fetch_message(mid)
        if source.author.id != self.system.bot.user.id or not source.embeds:
            raise ValueError('No se encontró el panel oficial de EssChino Studio.')
        embed = self.translated_embed(key, language, source)
        view = self.attach(self.system.panel_view(key), key, language)
        if private_copy:
            await i.edit_original_response(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        else:
            await i.followup.send(embed=embed, view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def ready(self, guild, panel_keys):
        updated = 0
        for key in (*panel_keys, 'direction', 'setup'):
            cid = self.channel_id(key)
            channel = guild.get_channel(cid) or await self.system.bot.fetch_channel(cid)
            mid = self.message_id(key)
            if not mid and key == 'direction':
                async for candidate in channel.history(limit=100):
                    if candidate.author.id == self.system.bot.user.id and any(e.footer.text == 'EssChino · Dirección privada' for e in candidate.embeds):
                        mid = candidate.id
                        await self.system.call('put', 'panel:direction', mid)
                        break
            if not mid:
                raise ValueError(f'Falta el panel {key}; no se inventó un mensaje de reemplazo.')
            message = await channel.fetch_message(mid)
            if message.author.id != self.system.bot.user.id or not message.embeds:
                raise ValueError(f'El panel {key} no pertenece al nuevo bot.')
            expected = {f'ec:lang:{key}:{x["code"]}' for x in LANGUAGES}
            actual = {getattr(item, 'custom_id', None) for row in message.components for item in row.children}
            if expected.issubset(actual) and not any(value and value.endswith(':es') for value in actual):
                continue
            async def snapshot(channel=channel, mid=mid):
                saved = await channel.fetch_message(mid)
                return dict(guild_id=guild.id, channel_id=channel.id, message_id=mid,
                    content=saved.content, embeds=[e.to_dict() for e in saved.embeds],
                    components=[r.to_dict() for r in saved.components],
                    attachments=[dict(id=a.id, filename=a.filename, size=a.size, url=a.url) for a in saved.attachments])
            async def apply(message=message, key=key):
                await message.edit(view=self.attach(self.system.panel_view(key), key), allowed_mentions=discord.AllowedMentions.none())
            await self.system.bot.changes.tracked('PANEL_LANGUAGES', 'Añadir idiomas al panel ' + key, apply,
                request_id=f'{VERSION}:{key}:{mid}', snapshot=snapshot)
            confirmed = await channel.fetch_message(mid)
            ids = {getattr(item, 'custom_id', None) for row in confirmed.components for item in row.children}
            if not expected.issubset(ids) or any(value and value.endswith(':es') for value in ids):
                raise ValueError('Discord no confirmó todos los botones de idiomas.')
            if [e.to_dict() for e in message.embeds] != [e.to_dict() for e in confirmed.embeds]:
                # Discord may refresh proxy/dimension metadata, so compare only
                # the authored information rather than CDN-generated fields.
                if any((a.title,a.description) != (b.title,b.description) for a,b in zip(message.embeds,confirmed.embeds)):
                    raise ValueError('La información original en español cambió al añadir los botones.')
            updated += 1
        log.info('PANEL_LANGUAGES verified panels=%s updated=%s languages=%s spanish_button=False public_spanish=True',
            len(panel_keys)+2, updated, [x['code'] for x in LANGUAGES])
