"""Read-only player profile channel and command routing."""
import logging
import unicodedata

import discord
from discord import app_commands

log = logging.getLogger('LaVenganzaRP.perfiles')
NAME = '👤┊𝐏𝐞𝐫𝐟𝐢𝐥𝐞𝐬'
MARKER = 'La Venganza RP · Perfiles · Usa /perfil para ver tu tarjeta y saldo.'


def normalized(name):
    return ''.join(c for c in unicodedata.normalize('NFKC', name).casefold() if c.isalnum())


def profile_overwrites(guild, inherited):
    overwrites = {target: discord.PermissionOverwrite.from_pair(*value.pair())
                  for target, value in inherited.items()}
    overwrites.setdefault(guild.default_role, discord.PermissionOverwrite())
    for target, value in overwrites.items():
        if target.id == guild.me.id or getattr(target, 'permissions', discord.Permissions.none()).administrator:
            continue
        value.send_messages = False
        value.send_messages_in_threads = False
        value.create_public_threads = False
        value.create_private_threads = False
        value.add_reactions = False
        value.use_application_commands = True
    overwrites[guild.default_role].view_channel = True
    overwrites[guild.me] = discord.PermissionOverwrite(
        view_channel=True, send_messages=True, read_message_history=True,
        embed_links=True, attach_files=True, use_application_commands=True)
    return overwrites


async def ensure_profiles(economy, guild):
    category = economy.delivery.category(guild)
    saved = economy.store.config('profiles_channel')
    channel = guild.get_channel(int(saved)) if saved else None
    if channel is None:
        candidates = [c for c in await guild.fetch_channels()
                      if isinstance(c, discord.TextChannel) and c.category_id == category.id
                      and (c.topic == MARKER or normalized(c.name) == 'perfiles')]
        if len(candidates) > 1:
            raise ValueError('Hay varios canales Perfiles en La Venganza; no crearé otro.')
        channel = candidates[0] if candidates else None
    if channel is None:
        channel = await guild.create_text_channel(
            NAME, category=category, topic=MARKER,
            overwrites=profile_overwrites(guild, category.overwrites),
            reason='Canal de perfiles y saldo solicitado por el administrador')
    if not isinstance(channel, discord.TextChannel) or channel.category_id != category.id:
        raise ValueError('Perfiles debe ser un canal de texto de La Venganza.')
    permissions = profile_overwrites(guild, channel.overwrites)
    if channel.overwrites != permissions:
        await channel.edit(overwrites=permissions, reason='Solo comandos de perfil para jugadores')
    if saved != str(channel.id):
        economy.store.runtime_config('profiles_channel', channel.id)
        public = channel.permissions_for(guild.default_role)
        log.info('Canal Perfiles listo: %s (%s), categoría=%s (%s), mensajes_jugadores=%s comandos=%s',
                 channel.name, channel.id, category.name, category.id,
                 public.send_messages, public.use_application_commands)
    if not economy.store.config('profiles_guide'):
        message = await channel.send(embed=discord.Embed(
            title='🔴 LA VENGANZA RP | PERFILES', color=0xD60000,
            description='Usa **/perfil** para ver tu tarjeta, saldo de monedas, cosméticos y podios.\n'
                        'Usa **/perfil jugador:** para consultar otro jugador.\n\n'
                        'Este canal es solo para perfiles: no permite mensajes normales.\n'
                        'El botón **Actualizar** refresca tu saldo y tus cosméticos.'),
            allowed_mentions=discord.AllowedMentions.none())
        economy.store.runtime_config('profiles_guide', message.id)
    me = channel.permissions_for(guild.me)
    public = channel.permissions_for(guild.default_role)
    log.debug('Perfiles permisos: mensajes=%s comandos=%s bot=%s',
              public.send_messages, public.use_application_commands, me.send_messages)


class ProfileTree(app_commands.CommandTree):
    async def interaction_check(self, interaction):
        economy = self.client.economy
        channel_id = economy.store.config('profiles_channel') if economy.ready else ''
        if channel_id and str(interaction.channel_id) == channel_id and interaction.command.name != 'perfil':
            await interaction.response.send_message('👤 Aquí solo se utiliza **/perfil**. Usa los demás comandos en sus canales.', ephemeral=True)
            return False
        return True
