"""Refresh existing identity guidance once, preserving native panel controls."""
import logging

import discord

from vice_design import BOT_ID, GUILD_ID, panel_copy

VERSION = 'vice-identity-guidance-v5-server-tag'
KEYS = ('welcome', 'roles', 'announcements', 'events')
log = logging.getLogger('ViceDistrict.identity_panels')


async def refresh_identity_panels(system):
    guild = system.bot.get_guild(GUILD_ID)
    system.validate_guild(guild)
    if system.bot.user.id != BOT_ID:
        raise ValueError('Bot de identidad incorrecto.')
    for key in KEYS:
        receipt = VERSION + ':' + key
        if system.store.get(receipt):
            continue
        channel = await guild.fetch_channel(system.channel_id(key))
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != GUILD_ID:
            raise ValueError('Canal de identidad incorrecto.')
        message = await system.find_panel(channel, key)
        marker = 'VIce District • panel:' + key
        if (message is None or message.author.id != BOT_ID or len(message.embeds) != 1
                or message.embeds[0].footer.text != marker):
            raise ValueError('Falta el panel original de identidad: ' + key)
        title, body, color = panel_copy(key, system.channel_id)
        current = message.embeds[0]
        if current.title != title or current.description != body or current.colour.value != color:
            before = dict(guild=str(GUILD_ID), channel=str(channel.id), message=str(message.id),
                embeds=[e.to_dict() for e in message.embeds],
                components=[c.to_dict() for c in message.components],
                attachments=[a.to_dict() for a in message.attachments])
            updated = discord.Embed.from_dict(current.to_dict())
            updated.title, updated.description, updated.colour = title, body, discord.Colour(color)

            async def snapshot():
                return before

            async def apply():
                # Omitting view/attachments preserves the original welcome image
                # and buttons. This cannot publish or replace a missing panel.
                await message.edit(embed=updated, allowed_mentions=discord.AllowedMentions.none())

            await system.track('IDENTITY_GUIDANCE', 'Actualizar guía de roles existentes',
                               apply, receipt, snapshot=snapshot)
        await system.call('put', receipt, True)
        log.info('VICE_IDENTITY_GUIDANCE_READY panel=%s', key)
