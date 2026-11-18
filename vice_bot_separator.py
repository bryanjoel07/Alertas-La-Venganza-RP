"""One-time cosmetic bot section; final placement is made in the owner's UI."""
import logging

import discord

from vice_design import BOT_ID, GUILD_ID
from vice_role_icons import role_state

log = logging.getLogger('ViceDistrict.bot_separator')
NAME = '━━ 🤖 BOTS ━━'
KEY = 'vice-bot-separator-v1'
REASON = 'Separación de bots solicitada por el propietario • ' + KEY


class BotSeparator:
    def __init__(self, system):
        self.system = system

    async def ready(self):
        # Never recreate a role the owner subsequently deletes or move an
        # already installed separator back below the bot after its UI placement.
        receipt = self.system.store.get(KEY)
        if (receipt and receipt.get('state') == 'owner_ui_position_pending'
                and receipt.get('role', {}).get('position', 0) > 1):
            return
        context = await self.system.role_icons.context()
        if not context['unlocked']:
            return
        rows = self.system.role_icons.preflight_assets()
        image = next(row['data'] for row in rows if row['key'] == 'bot')
        latest = None

        async def snapshot():
            nonlocal latest
            latest = await self.system.role_icons.context()
            return {'guild': str(GUILD_ID), 'roles': [role_state(r) for r in latest['roles'].values()],
                    'receipt': self.system.store.get(KEY)}

        async def apply():
            guild, roles = latest['guild'], latest['roles']
            if not latest['unlocked']:
                return
            current = self.system.store.get(KEY)
            role = roles.get(int((current or {}).get('role_id') or 0))
            if (current and current.get('state') == 'owner_ui_position_pending'
                    and (role is None or role.position != 1)):
                return
            if role is None and current and current.get('attempted'):
                recovered = []
                async for entry in guild.audit_logs(limit=100, action=discord.AuditLogAction.role_create,
                                                     user=discord.Object(id=BOT_ID)):
                    if entry.reason == REASON and getattr(entry.user, 'id', None) == BOT_ID:
                        candidate = roles.get(getattr(entry.target, 'id', 0))
                        if candidate and candidate.name == NAME and candidate.permissions.value == 0:
                            recovered.append(candidate)
                if len(recovered) != 1:
                    raise ValueError('No se confirmó una creación previa única; no se duplicará el separador.')
                role = recovered[0]
            if role is None:
                if any(r.name == NAME for r in roles.values()):
                    raise ValueError('Ya existe un separador de bots sin recibo verificable.')
                if current and current.get('role_id'):
                    return  # Owner deleted the created role; do not recreate it.
                await self.system.call('put', KEY, dict(state='creating', attempted=True))
                role = await guild.create_role(name=NAME, color=discord.Color(0x33E5E9),
                    permissions=discord.Permissions.none(), hoist=False, mentionable=False,
                    display_icon=image, reason=REASON)
                await self.system.call('put', KEY, dict(state='created', role_id=str(role.id),
                    before_position=role_state(role)))
            if role.guild.id != GUILD_ID or role.permissions.value or role.managed:
                raise ValueError('El separador no cumple el alcance cosmético.')
            # Place within editable hierarchy so the owner can make one short
            # native drag above the bot. No attempt to bypass bot hierarchy.
            # Role.edit(position=...) expands a cached role range. A freshly
            # created role can be omitted by that stale range; send only its ID.
            position = max(1, latest['top_role'].position - 1)
            await guild.edit_role_positions(positions={role: position}, reason=REASON)
            fresh = await guild.fetch_roles()
            applied = next(r for r in fresh if r.id == role.id)
            if applied.position != position:
                raise ValueError('No se confirmó la posición del separador de bots.')
            await self.system.call('put', KEY, dict(state='owner_ui_position_pending',
                role_id=str(role.id), role=role_state(applied),
                hierarchy=[{'id': str(r.id), 'position': r.position} for r in fresh],
                desired='Below Founder, immediately above EssChino Studio Bot'))
            log.info('VICE_BOT_SEPARATOR_READY role=%s owner_ui_position_pending=True', role.id)

        await self.system.track('ROLE_CREATE', 'Crear separación visual de bots', apply,
                                KEY, snapshot=snapshot)
