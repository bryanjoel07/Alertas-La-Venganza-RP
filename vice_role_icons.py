"""Apply the owner's exact prepared role badges, with per-role durable receipts.

Only display_icon is edited. Membership, permissions, names, ordering and role
creation/deletion are outside this service. Managed/high roles are prepared for
the owner's Discord session, never changed through the bot token.
"""
import asyncio
import hashlib
import io
import json
import logging
from pathlib import Path
import re

import discord
from PIL import Image

from vice_design import BOT_ID, GUILD_ID, OWNER_ID

log = logging.getLogger('ViceDistrict.role_icons')
VERSION = 'vice-role-icons-v1'
ASSETS = Path(__file__).parent / 'assets' / 'vice-district' / 'role-icons-v1'
MAX_ICON_BYTES = 256 * 1024
OWNER_UI_KEYS = frozenset({'founder', 'bot', 'booster'})
TAG_PREPARATION_KEY = 'owner_ui:vice-server-tag-v1'


def icon_hash(role):
    icon = getattr(role, 'icon', None)
    return getattr(icon, 'key', None) if icon is not None else None


def role_state(role):
    icon = getattr(role, 'icon', None)
    colour = getattr(role, 'colour', getattr(role, 'color', None))
    secondary = getattr(role, 'secondary_colour', None)
    tertiary = getattr(role, 'tertiary_colour', None)
    return dict(id=str(role.id), name=role.name, position=role.position,
                permissions=str(role.permissions.value), color=getattr(colour, 'value', None),
                secondary_color=getattr(secondary, 'value', None),
                tertiary_color=getattr(tertiary, 'value', None), hoist=role.hoist,
                mentionable=role.mentionable, managed=role.managed,
                icon_hash=icon_hash(role), unicode_emoji=getattr(role, 'unicode_emoji', None),
                icon_url=str(getattr(icon, 'url', '')) if icon is not None else None)


class RoleIcons:
    def __init__(self, system, *, asset_dir=None):
        self.system = system
        self.asset_dir = Path(asset_dir) if asset_dir is not None else ASSETS
        self.lock = asyncio.Lock()

    def preflight_assets(self):
        """Validate the complete pack before any Discord mutation or UI handoff."""
        root = self.asset_dir.resolve()
        manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8-sig'))
        if (str(manifest.get('guild_id')) != str(GUILD_ID) or manifest.get('version') != VERSION
                or manifest.get('capability') != 'ROLE_ICONS'):
            raise ValueError('El manifiesto de iconos no pertenece a este servidor o versión.')
        rows = manifest.get('roles')
        if not isinstance(rows, list) or not rows:
            raise ValueError('El manifiesto de iconos está vacío.')
        seen_ids, seen_keys, prepared = set(), set(), []
        for row in rows:
            key, rid, name = row.get('key'), int(row.get('id', 0)), row.get('name')
            if (not isinstance(key, str) or not re.fullmatch(r'[a-z0-9_]+', key)
                    or rid <= 0 or rid == GUILD_ID or rid in seen_ids or key in seen_keys
                    or not isinstance(name, str) or not name):
                raise ValueError('El manifiesto contiene un rol inválido o duplicado.')
            application = 'owner_session' if key in OWNER_UI_KEYS else 'bot_when_unlocked'
            if row.get('application') != application:
                raise ValueError('El método de aplicación del icono no corresponde al rol.')
            if row.get('path') != 'png/' + key + '.png':
                raise ValueError('La imagen no corresponde a la ruta exacta del rol.')
            path = (root / row['path']).resolve()
            if not path.is_relative_to(root):
                raise ValueError('La imagen está fuera del paquete autorizado.')
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if (digest != row.get('sha256') or len(data) != row.get('bytes')
                    or not 0 < len(data) <= MAX_ICON_BYTES
                    or row.get('width') != 64 or row.get('height') != 64):
                raise ValueError('No coincide la integridad o el tamaño del icono: ' + key)
            try:
                with Image.open(io.BytesIO(data)) as im:
                    if im.format != 'PNG' or im.size != (64, 64) or getattr(im, 'n_frames', 1) != 1:
                        raise ValueError('Se requiere un PNG estático de 64 × 64: ' + key)
                    im.load()
            except (OSError, Image.DecompressionBombError) as error:
                raise ValueError('El icono no es una imagen PNG válida: ' + key) from error
            seen_ids.add(rid)
            seen_keys.add(key)
            prepared.append(dict(row, id=rid, data=data))
        return prepared

    async def context(self):
        if getattr(self.system.bot.user, 'id', None) != BOT_ID:
            raise ValueError('Se requiere EssChino Studio Bot para aplicar estos iconos.')
        guild = await self.system.bot.fetch_guild(GUILD_ID)
        self.system.validate_guild(guild)
        if guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
            raise ValueError('El servidor o propietario no coincide con los iconos autorizados.')
        roles = {role.id: role for role in await guild.fetch_roles()}
        member = await guild.fetch_member(BOT_ID)
        if member.id != BOT_ID or member.guild.id != GUILD_ID:
            raise ValueError('No se confirmó el miembro del bot en el servidor.')
        bot_ids = set(member._roles) | {GUILD_ID}
        bot_roles = [role for role in roles.values() if role.id in bot_ids]
        if not bot_roles:
            raise ValueError('No se confirmó la jerarquía del bot.')
        bits = 0
        for role in bot_roles:
            bits |= role.permissions.value
        permissions = discord.Permissions(bits)
        if not (permissions.manage_roles or permissions.administrator):
            raise ValueError('El bot no puede administrar los iconos de los roles.')
        return dict(guild=guild, roles=roles, top_role=max(bot_roles),
                    unlocked='ROLE_ICONS' in guild.features)

    @staticmethod
    def receipt_key(row):
        return f'role_icon:{VERSION}:{row["id"]}:{row["sha256"]}'

    @staticmethod
    def reason(row):
        return f'Iconos de VIce District solicitados por el propietario • {VERSION}:{row["id"]}:{row["sha256"][:12]}'

    @staticmethod
    def snapshot_state(context, role_id):
        role = context['roles'].get(role_id)
        return dict(guild=str(context['guild'].id), owner=str(context['guild'].owner_id),
                    bot=str(BOT_ID), features=list(context['guild'].features),
                    bot_top_role=str(context['top_role'].id),
                    role=role_state(role) if role is not None else None)

    @staticmethod
    def same_icon(role, icon, unicode):
        return icon_hash(role) == icon and getattr(role, 'unicode_emoji', None) == unicode

    async def recovered_icon(self, context, row, role):
        """Resolve an interrupted response only from this bot's exact audit entry."""
        if not icon_hash(role) or getattr(role, 'unicode_emoji', None):
            return False
        guild = context['guild']
        try:
            async for entry in guild.audit_logs(limit=100, action=discord.AuditLogAction.role_update,
                                                 user=discord.Object(id=BOT_ID)):
                if (getattr(entry.user, 'id', None) != BOT_ID or entry.reason != self.reason(row)
                        or getattr(entry.target, 'id', None) != role.id):
                    continue
                after = getattr(entry.after, 'icon', None)
                after_hash = getattr(after, 'key', None) if after is not None else None
                if after_hash == icon_hash(role):
                    return True
        except (discord.HTTPException, AttributeError):
            log.warning('VICE_ROLE_ICON_RECOVERY_UNAVAILABLE role=%s', role.id)
        return False

    async def owner_ui(self, context, row):
        role = context['roles'].get(row['id'])
        if role is None:
            return 'absent'
        if role.name != row['name']:
            return 'changed'
        key = self.receipt_key(row)
        if self.system.store.get(key) is None:
            await self.system.call('put', key, dict(state='owner_ui_pending', version=VERSION,
                key=row['key'], role=str(role.id), sha256=row['sha256'], path=row['path'],
                before=self.snapshot_state(context, role.id)))
        log.info('VICE_ROLE_ICON_OWNER_UI_PREPARED key=%s role=%s', row['key'], role.id)
        return 'owner_ui'

    async def prepare_owner_tag(self, context):
        """Record the owner's observed UI before-state; never change tag settings."""
        if self.system.store.get(TAG_PREPARATION_KEY) is not None:
            return
        before = dict(source='owner-session UI observation', enabled=False, text='',
                      placeholder='WUMP', badge='Sword', primary_color='#FF1C90',
                      secondary_color='#FF7FC0', server_profile_public=False)
        async def snapshot():
            return dict(guild=str(GUILD_ID), owner=str(OWNER_ID), bot=str(BOT_ID),
                        features=list(context['guild'].features), observed_before=before,
                        preparation=self.system.store.get(TAG_PREPARATION_KEY))
        async def prepare():
            await self.system.call('put', TAG_PREPARATION_KEY,
                dict(state='owner_ui_pending', desired_text='VICE', before=before))
        await self.system.track('OWNER_UI_PREPARATION', 'Preparar etiqueta VICE en la sesión del propietario',
                                prepare, 'vice-server-tag-v1', snapshot=snapshot)
        log.info('VICE_SERVER_TAG_OWNER_UI_PREPARED guild=%s desired=VICE', GUILD_ID)

    async def apply_one(self, row):
        key = self.receipt_key(row)
        latest = None

        async def snapshot():
            nonlocal latest
            latest = await self.context()
            return self.snapshot_state(latest, row['id'])

        async def apply():
            # ChangeLog has just persisted snapshot(), including a fresh REST
            # guild/owner/bot/hierarchy/role check, before calling this operation.
            context = latest
            role = context['roles'].get(row['id'])
            if not context['unlocked']:
                return 'locked'
            if role is None:
                return 'absent'
            if role.name != row['name']:
                return 'changed'
            if role.guild.id != GUILD_ID or role.id == GUILD_ID or role.managed or not role < context['top_role']:
                return 'not_editable'
            receipt = self.system.store.get(key)
            if receipt and receipt.get('state') == 'applied':
                return 'already' if self.same_icon(role, receipt.get('icon_hash'), None) else 'changed'
            if receipt and receipt.get('state') in {'preserved_changed', 'owner_ui_pending'}:
                return 'changed'
            if receipt is None:
                receipt = dict(state='pending', version=VERSION, key=row['key'], role=str(role.id),
                    sha256=row['sha256'], before=self.snapshot_state(context, role.id), attempted=False)
                await self.system.call('put', key, receipt)
            before = receipt.get('before', {}).get('role') or {}
            if not self.same_icon(role, before.get('icon_hash'), before.get('unicode_emoji')):
                if receipt.get('attempted') and await self.recovered_icon(context, row, role):
                    await self.system.call('put', key, dict(receipt, state='applied',
                        icon_hash=icon_hash(role), recovered=True))
                    return 'already'
                await self.system.call('put', key, dict(receipt, state='preserved_changed',
                    observed_icon_hash=icon_hash(role), observed_unicode_emoji=getattr(role, 'unicode_emoji', None)))
                return 'changed'
            receipt = dict(receipt, attempted=True)
            await self.system.call('put', key, receipt)
            try:
                updated = await role.edit(display_icon=row['data'], reason=self.reason(row))
            except discord.HTTPException as error:
                if 400 <= error.status < 500 and error.status != 429:
                    await self.system.call('put', key, dict(receipt, attempted=False))
                raise
            if (updated is None or updated.id != role.id or updated.guild.id != GUILD_ID
                    or not icon_hash(updated) or getattr(updated, 'unicode_emoji', None)):
                raise ValueError('Discord no confirmó el icono aplicado al rol exacto.')
            await self.system.call('put', key, dict(receipt, state='applied', icon_hash=icon_hash(updated)))
            return 'applied'

        return await self.system.track('ROLE_ICON', 'Aplicar icono de rol de VIce District',
            apply, f'{VERSION}:{row["id"]}:{row["sha256"]}', snapshot=snapshot)

    async def ready(self):
        async with self.lock:
            rows = await asyncio.to_thread(self.preflight_assets)
            context = await self.context()
            summary = dict(total=len(rows), applied=0, already=0, owner_ui=0, absent=0,
                           changed=0, not_editable=0, failed=0, locked=0)
            if not context['unlocked']:
                summary['locked'] = len(rows)
                log.info('VICE_ROLE_ICONS_LOCKED guild=%s feature=ROLE_ICONS total=%s', GUILD_ID, len(rows))
                return summary
            # Persist all three owner-session before-states before the first bot
            # edit. The owner can then apply these without granting new powers.
            for row in rows:
                if row['key'] in OWNER_UI_KEYS:
                    status = await self.owner_ui(context, row)
                    summary[status] += 1
            await self.prepare_owner_tag(context)
            for row in rows:
                if row['key'] in OWNER_UI_KEYS:
                    continue
                role = context['roles'].get(row['id'])
                receipt = self.system.store.get(self.receipt_key(row))
                # Completed receipts are permanent: a later owner icon change
                # is respected, even if it is removal of the icon altogether.
                if receipt and receipt.get('state') in {'applied', 'preserved_changed'}:
                    if role is None:
                        status = 'absent'
                    elif receipt.get('state') == 'applied' and self.same_icon(role, receipt.get('icon_hash'), None):
                        status = 'already'
                    else:
                        status = 'changed'
                    summary[status] += 1
                    continue
                try:
                    status = await self.apply_one(row)
                    summary[status] += 1
                    log.info('VICE_ROLE_ICON_RESULT key=%s role=%s status=%s', row['key'], row['id'], status)
                except Exception:
                    summary['failed'] += 1
                    log.exception('VICE_ROLE_ICON_FAILED key=%s role=%s', row['key'], row['id'])
            await self.system.call('put', 'role_icons:last_summary:' + VERSION, summary)
            log.info('VICE_ROLE_ICONS_READY guild=%s total=%s applied=%s already=%s owner_ui=%s absent=%s changed=%s not_editable=%s failed=%s',
                     GUILD_ID, summary['total'], summary['applied'], summary['already'], summary['owner_ui'],
                     summary['absent'], summary['changed'], summary['not_editable'], summary['failed'])
            return summary
