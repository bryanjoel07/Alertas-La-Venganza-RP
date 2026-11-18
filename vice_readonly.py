"""View-only district panels with reaction cleanup, without changing visibility."""
import asyncio
import logging

import discord

from vice_design import BOT_ID, GUILD_ID, CHANNELS

log = logging.getLogger('ViceDistrict.readonly')
READONLY_VERSION = 'vice-view-only-v1'
READONLY_POLICIES = frozenset({'read', 'staffread', 'adminread', 'closed'})
WRITE_FLAGS = ('send_messages', 'send_tts_messages', 'send_voice_messages', 'send_polls',
               'embed_links', 'attach_files', 'add_reactions', 'external_emojis',
               'external_stickers', 'create_public_threads', 'create_private_threads',
               'send_messages_in_threads', 'use_external_apps', 'use_application_commands')


def lock_overwrites(guild, rules):
    """Keep visibility/voice bits and neutralize every existing publication allow."""
    result = {target: discord.PermissionOverwrite.from_pair(*overwrite.pair())
              for target, overwrite in rules.items()}
    result.setdefault(guild.default_role, discord.PermissionOverwrite())
    for target, overwrite in result.items():
        if target == guild.me:
            continue
        overwrite.update(**{flag: False for flag in WRITE_FLAGS})
    bot = result.setdefault(guild.me, discord.PermissionOverwrite())
    bot.update(view_channel=True, read_message_history=True, send_messages=True,
               send_messages_in_threads=True, embed_links=True, attach_files=True,
               manage_messages=True, use_application_commands=True)
    return result


class ReadOnlyChannels:
    def __init__(self, system):
        self.system = system
        self.ready_lock = asyncio.Lock()
        self.reaction_lock = asyncio.Lock()

    def target_ids(self):
        keys = [spec[0] for spec in CHANNELS if spec[4] in READONLY_POLICIES and not spec[5]]
        ids = {self.system.channel_id(key) for key in keys + ['voicepanel', 'ticket_archive']}
        ids.update(int(row['channel']) for row in self.system.store.tickets() if row['state'] == 'closed')
        return {int(value) for value in ids if value}

    def is_target(self, channel):
        if channel is None or channel.guild.id != GUILD_ID:
            return False
        if isinstance(channel, discord.Thread):
            return channel.parent_id in self.target_ids()
        return isinstance(channel, discord.TextChannel) and channel.id in self.target_ids()

    async def clear_message(self, channel, message):
        self.system.validate_guild(channel.guild)
        if not self.is_target(channel) or message.channel.id != channel.id or not message.reactions:
            return False
        async def snapshot():
            try:
                current = await channel.fetch_message(message.id)
            except discord.NotFound:
                return dict(guild=GUILD_ID, channel=channel.id, message=message.id, missing=True)
            return dict(guild=GUILD_ID, channel=channel.id, message=message.id,
                        reactions=[dict(emoji=str(r.emoji), count=r.count) for r in current.reactions])
        async def clear():
            try:
                await message.clear_reactions()
            except discord.NotFound:
                pass
        await self.system.track('READONLY_REACTIONS', 'Retirar reacciones de un panel de solo lectura',
            clear, f'{channel.id}:{message.id}:{discord.utils.utcnow().timestamp()}', snapshot=snapshot)
        return True

    async def reaction_add(self, payload):
        if payload.guild_id != GUILD_ID:
            return
        guild = self.system.bot.get_guild(GUILD_ID)
        self.system.validate_guild(guild)
        channel = guild.get_channel_or_thread(payload.channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(payload.channel_id)
            except discord.NotFound:
                return
        if not self.is_target(channel):
            return
        async with self.reaction_lock:
            try:
                message = await channel.fetch_message(payload.message_id)
                await self.clear_message(channel, message)
            except discord.NotFound:
                return

    async def clear_history(self, channel):
        async for message in channel.history(limit=None):
            if message.reactions:
                await self.clear_message(channel, message)

    async def ready(self):
        async with self.ready_lock:
            if self.system.store.get('readonly_release') == READONLY_VERSION:
                return
            guild = self.system.bot.get_guild(GUILD_ID)
            self.system.validate_guild(guild)
            if self.system.bot.user.id != BOT_ID:
                raise ValueError('Se requiere EssChino Studio Bot para proteger los paneles.')
            channels = {channel.id: channel for channel in await guild.fetch_channels()}
            targets = []
            for cid in sorted(self.target_ids()):
                channel = channels.get(cid)
                if not isinstance(channel, discord.TextChannel) or channel.guild.id != GUILD_ID:
                    raise ValueError('Falta un canal informativo registrado; se requiere revisión.')
                targets.append(channel)
            categories = []
            for key in ('info', 'help', 'tempvoice', 'closed'):
                cid = self.system.store.get('category:' + key)
                if cid:
                    category = channels.get(cid)
                    if not isinstance(category, discord.CategoryChannel) or category.guild.id != GUILD_ID:
                        raise ValueError('No se confirmó la categoría informativa: ' + key)
                    categories.append(category)
            async def apply():
                for channel in categories + targets:
                    await channel.edit(overwrites=lock_overwrites(guild, channel.overwrites),
                        reason='Canales informativos de solo lectura solicitados por el propietario')
                async with self.reaction_lock:
                    for channel in targets:
                        await self.clear_history(channel)
                        # Existing threads inherit the parent restrictions, including reactions.
                        threads = {t.id: t for t in guild.threads if t.parent_id == channel.id}
                        async for thread in channel.archived_threads(limit=None):
                            threads[thread.id] = thread
                        if channel.type == discord.ChannelType.text:
                            async for thread in channel.archived_threads(limit=None, private=True):
                                threads[thread.id] = thread
                        for thread in threads.values():
                            await self.clear_history(thread)
            await self.system.track('READONLY_SETUP', 'Restringir publicación y reacciones en paneles',
                                    apply, READONLY_VERSION)
            await self.system.call('put', 'readonly_release', READONLY_VERSION)
            log.info('VICE_READONLY_READY guild=%s channels=%s categories=%s', GUILD_ID, len(targets), len(categories))
