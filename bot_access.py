"""Application access by trusted role IDs, independent of Discord role edits."""
import json
import logging

import discord
from discord import app_commands

GUILD_ID = 1244988345327550565
ADMIN_ROLES = frozenset({1245008186440683530, 1300627506801541230,
    1300619682486947931, 1245010156576833536, 1567253212937846935})
STAFF_ROLES = ADMIN_ROLES | {1300627732954349619, 1300631163362218054}
MEETING_ROLES = ADMIN_ROLES - {1567253212937846935}

# All configured administrative ranks currently have this permission. This is
# only Discord's command discovery hint; authorization always checks the IDs
# below. Requiring Administrator here would hide commands from Admin/Super Admin.
ADMIN_DISCOVERY = discord.Permissions(moderate_members=True)

ADMIN_ROOTS = {'ajustes', 'cambios', 'respaldo', 'mantenimiento'}
ADMIN_COMMANDS = {
    'estado-bot', 'testalert', 'simular-ciclo', 'historial-caidas',
    'evento crear', 'evento cerrar', 'evento finalizar', 'evento participantes',
    'evento editar', 'evento premios', 'evento banner',
    'ticket configuracion', 'ticket departamento', 'ticket recuperar',
    'feedback panel', 'feedback resumen', 'feedback retirar', 'staff abrir',
    'minijuegos panel', 'streamer configurar', 'streamer registrar',
    'streamer pendientes', 'streamer revisar', 'sugerencias eliminar',
}
CASE_STAFF_COMMANDS = {
    'ticket gestion', 'ticket buscar', 'ticket acceso', 'ticket nota', 'ticket notas',
    'ticket estado', 'ticket transferir', 'ticket participante', 'ticket historial',
    'ticket compra', 'ticket devolver',
}
STAFF_COMMANDS = {'staff pendientes', 'staff historial'}
MEMBER_COMMANDS = {
    'retos', 'probar', 'guia', 'saldo', 'tienda', 'comprar', 'regalar', 'inventario',
    'equipar', 'quitar', 'trofeo', 'movimientos', 'deseos', 'sala', 'perfil', 'regla',
    'jugar', 'ticket mis', 'ticket cerrados', 'ticket transcripcion', 'ticket archivo',
    'feedback ver', 'errores reportar', 'errores mis', 'errores estado',
    'sugerencias proponer', 'sugerencias mis', 'sugerencias ver',
    'foto subir', 'foto retirar', 'foto semana', 'staff solicitar',
    'staff mi_solicitud', 'staff ver', 'minijuegos progreso', 'minijuegos ranking',
    'streamer solicitar', 'streamer verificar', 'streamer estado',
    'evento historial', 'evento ranking',
}


def role_ids(member):
    return {role.id for role in getattr(member, 'roles', ())}


def is_bot_admin(member):
    return not getattr(member, 'bot', False) and bool(
        getattr(getattr(member, 'guild_permissions', None), 'administrator', False)
        or role_ids(member) & ADMIN_ROLES)


def is_bot_staff(member):
    return not getattr(member, 'bot', False) and bool(is_bot_admin(member) or role_ids(member) & STAFF_ROLES)


async def admin_check(interaction):
    if interaction.guild_id != GUILD_ID or not is_bot_admin(interaction.user):
        raise app_commands.CheckFailure('Esta función requiere un rol de administración de La Venganza RP.')
    return True


def command_level(name):
    root = name.split(' ', 1)[0]
    if root in ADMIN_ROOTS or name in ADMIN_COMMANDS:
        return 'admin'
    if root == 'economia' or name == 'foto premio':
        return 'economy'
    if root == 'reunion':
        return 'meeting'
    if name in CASE_STAFF_COMMANDS:
        return 'case_staff'
    if name in STAFF_COMMANDS:
        return 'staff'
    if name in MEMBER_COMMANDS:
        return 'member'
    raise ValueError(f'Comando sin política de acceso: {name}')


def delegated_economy(interaction, store=None):
    role = (store if store is not None else interaction.client.economy.store).config('admin_role')
    # A public identity must never become a financial administrator by config.
    return bool(role and str(role) not in {str(GUILD_ID), '1245009164070158409'}
        and any(str(value) == str(role) for value in role_ids(interaction.user)))


def delegated_case_staff(interaction):
    from tickets import route_roles
    from tickets_store import DEPARTMENTS
    ids = role_ids(interaction.user)
    return any(ids & route_roles(interaction.client.tickets.store, department) for department in DEPARTMENTS)


async def command_access(interaction):
    member = interaction.user
    if (interaction.guild_id != GUILD_ID or not isinstance(member, discord.Member)
            or member.guild.id != GUILD_ID or member.bot):
        raise app_commands.CheckFailure('Usa los comandos con tu cuenta dentro de La Venganza RP.')
    level = command_level(interaction.command.qualified_name)
    allowed = level == 'member'
    if level in ('admin', 'economy'):
        allowed = is_bot_admin(member) or (level == 'economy' and delegated_economy(interaction))
    elif level in ('staff', 'case_staff'):
        allowed = is_bot_staff(member) or (level == 'case_staff' and delegated_case_staff(interaction))
    elif level == 'meeting':
        # Keep the existing private meeting policy: a generic Administrator
        # account does not gain access to staff meeting data through this gate.
        allowed = bool(role_ids(member) & MEETING_ROLES)
    if not allowed:
        raise app_commands.CheckFailure('Tu rol no está autorizado para esta función del bot.')
    # Ownership, channel visibility, department and reserved-case checks remain
    # inside each handler, including their buttons and confirmation forms.
    return True


def install_command_access(tree, guild):
    commands = [command for command in tree.walk_commands(guild=guild)
        if isinstance(command, app_commands.Command)]
    inventory = {command.qualified_name: command_level(command.qualified_name) for command in commands}
    for root in tree.get_commands(guild=guild):
        children = list(root.walk_commands()) if isinstance(root, app_commands.Group) else [root]
        levels = [inventory[command.qualified_name] for command in children if isinstance(command, app_commands.Command)]
        if levels and all(level in {'admin', 'economy', 'meeting'} for level in levels):
            root.default_permissions = discord.Permissions(ADMIN_DISCOVERY.value)
    tree.bot_access_enabled = True
    logging.getLogger('LaVenganzaRP.access').info('BOT_COMMAND_ACCESS commands=%s policy=%s',
        len(inventory), json.dumps({level:sum(value == level for value in inventory.values())
            for level in sorted(set(inventory.values()))}, sort_keys=True))
    return inventory
