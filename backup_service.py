"""Respaldo diario persistente, operaciones manuales y avisos privados de fallo."""
from settings_catalog import value as setting
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
import threading
import uuid
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from bot_access import is_bot_admin

from backup import snapshot
from backup_meta import atomic_json, record_backup, status_path
from drive_backups import BackupFailure, DriveBackupClient, recovery_probe

log = logging.getLogger('LaVenganzaRP.respaldos')
PR = ZoneInfo('America/Puerto_Rico')


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class BackupService:
    def __init__(self, bot, path, guild_id):
        self.bot, self.path, self.guild_id = bot, Path(path).resolve(), guild_id
        self.enabled = os.getenv('AUTO_BACKUP_ENABLED', '0').lower() in ('1', 'true')
        self.time_pr = os.getenv('BACKUP_TIME_PR', '03:00')
        self.folder_id = os.getenv('GOOGLE_DRIVE_BACKUP_FOLDER_ID', '')
        self.directory = Path(os.getenv('BACKUP_DIR', str(self.path.parent / 'backups')))
        self.state_path = Path(os.getenv('BACKUP_STATE_PATH', str(self.path.parent / 'backup-schedule.json')))
        self.config_error = None
        try:
            if not self.directory.is_absolute() or not self.state_path.is_absolute():
                raise ValueError()
            if self.state_path.resolve() in (self.path, status_path(self.path).resolve()):
                raise ValueError()
            when = datetime.strptime(self.time_pr, '%H:%M')
            self.hour, self.minute = when.hour, when.minute
            self.alert_channel_id = int(os.getenv('BACKUP_ALERT_CHANNEL_ID', '1515887549678223380'))
        except ValueError:
            self.config_error = 'Revisa BACKUP_TIME_PR (HH:MM), rutas absolutas y el ID del canal de avisos.'
            self.hour, self.minute = 3, 0
            self.alert_channel_id = 1515887549678223380
        self.lock = asyncio.Lock()
        self.state_lock = threading.RLock()
        self.state = {'source': str(self.path)}
        self.loaded = False
        self.task = None
        self.manual_task = None
        self.last_check_at = None
        self.notice_operations = set()
        self.group = app_commands.Group(name='respaldo', description='Crear respaldos de Drive y probar su recuperación', guild_only=True, default_permissions=discord.Permissions(administrator=True))
        self.commands()

    def _load(self):
        if not self.state_path.exists():
            return {'source': str(self.path)}
        try:
            if self.state_path.stat().st_size > 1048576:
                raise ValueError()
            value = json.loads(self.state_path.read_text())
            if value['source'] != str(self.path):
                raise ValueError()
            if value.get('phase', 'not_run') not in ('not_run', 'running', 'complete', 'failed', 'interrupted'):
                raise ValueError()
            for key in ('last_success_at', 'last_recovery_at'):
                if value.get(key) and datetime.fromisoformat(value[key]).tzinfo is None:
                    raise ValueError()
            return value
        except Exception:
            raise BackupFailure('configuration', 'No se pudo validar el registro de programación. No se sobrescribirá; revisa BACKUP_STATE_PATH.') from None

    def _copy(self):
        with self.state_lock:
            return deepcopy(self.state)

    def _change(self, **values):
        with self.state_lock:
            self.state.update(deepcopy(values))
            try:
                atomic_json(self.state_path, self.state)
            except Exception:
                raise BackupFailure('storage', 'No se pudo guardar el registro persistente del respaldo.') from None

    async def start(self):
        if not self.loaded:
            try:
                self.state = await asyncio.to_thread(self._load)
                if self.state.get('phase') == 'running':
                    await asyncio.to_thread(self._change, phase='interrupted', error_stage='interrupted', error_message='El proceso se reinició antes de confirmar el respaldo.')
            except BackupFailure as error:
                self.config_error = str(error)
            self.loaded = True
        if self.enabled and not self.config_error and (self.task is None or self.task.done()):
            self.task = asyncio.create_task(self.loop(), name='daily-drive-backup')

    def slot(self, now):
        local = now.astimezone(PR)
        hour,minute=map(int,setting(self.path,'backups','time',f'{self.hour:02}:{self.minute:02}').split(':'))
        cutoff = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return (local.date() if local >= cutoff else local.date() - timedelta(days=1)).isoformat()

    def _manifest(self, manifest):
        atomic_json(str(manifest['file']) + '.manifest.json', manifest)
        record_backup(self.path, manifest)

    def _probe_manifest(self):
        state = self._copy()
        candidates = [state.get('last_uploaded'), state.get('last_success')]
        try:
            candidates.append(json.loads(status_path(self.path).read_text()))
        except Exception:
            pass
        valid = []
        for candidate in candidates:
            try:
                if candidate['source'] != str(self.path) or candidate.get('drive_state') != 'verified' or not candidate.get('drive_file_id') or Path(candidate['file']).resolve() == self.path:
                    continue
                created = datetime.fromisoformat(candidate['created_at'])
                if created.tzinfo is None:
                    continue
                valid.append((created.timestamp(), candidate))
            except (KeyError, TypeError, ValueError):
                continue
        if not valid:
            raise BackupFailure('configuration', 'No hay una copia verificada de Drive para esta base. Usa /respaldo crear primero.')
        return deepcopy(max(valid, key=lambda item: item[0])[1])

    def _pipeline(self, probe_only=False):
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.path.is_file():
            raise BackupFailure('snapshot', 'La base activa no existe. No se creará una vacía.')
        required = self.path.stat().st_size * 3 + 16 * 1024 * 1024
        wal = Path(str(self.path) + '-wal')
        if wal.is_file():
            required += wal.stat().st_size * 3
        if shutil.disk_usage(self.directory).free < required:
            raise BackupFailure('storage', 'No hay espacio suficiente para crear y verificar la copia sin comprometer la base activa.')
        manifest = self._probe_manifest() if probe_only else None
        try:
            if not probe_only:
                self._change(stage='snapshot')
                filename = f"lavenganza-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}.sqlite3"
                manifest = snapshot(self.path, self.directory / filename)
                manifest.update(drive_state='pending', restore_state='not_tested')
                self._manifest(manifest)
            self._change(stage='authentication')
            with DriveBackupClient() as drive:
                if not probe_only:
                    folder = drive.folder(self.folder_id or self._copy().get('folder_id'))
                    self._change(folder_id=folder, stage='upload')
                    manifest['drive_file_id'] = drive.upload(manifest['file'], folder)
                    manifest['drive_state'] = 'verified'
                    self._change(last_uploaded=manifest)
                    self._manifest(manifest)
                self._change(stage='recovery')
                with tempfile.TemporaryDirectory(prefix='drive-probe-', dir=self.directory) as folder:
                    downloaded = Path(folder) / 'descargada.sqlite3'
                    drive.download(manifest['drive_file_id'], downloaded, manifest)
                    recovery_probe(downloaded, manifest, folder)
                manifest.update(restore_state='verified', restore_checked_at=now_iso())
                self._manifest(manifest)
                return manifest
        except Exception as original:
            error = original if isinstance(original, BackupFailure) else BackupFailure(self._copy().get('stage', 'backup'), 'No se pudo completar el respaldo. Revisa autenticación, espacio y permisos.')
            if manifest is not None:
                if manifest.get('drive_state') != 'verified':
                    manifest['drive_state'] = 'failed'
                if self._copy().get('stage') == 'recovery':
                    manifest['restore_state'] = 'failed'
                try:
                    self._manifest(manifest)
                except Exception:
                    log.error('No se pudo guardar la constancia del fallo de respaldo')
            raise error from None

    async def execute(self, slot=None, probe_only=False):
        if self.config_error:
            raise BackupFailure('configuration', self.config_error)
        if self.lock.locked():
            raise BackupFailure('busy', 'Ya hay una operación de respaldo en curso. Consulta /estado-bot.')
        async with self.lock:
            operation = uuid.uuid4().hex
            update = dict(operation=operation, phase='running', stage='starting', kind='probe' if probe_only else 'backup', last_attempt_at=now_iso(), error_stage=None, error_message=None)
            if slot is not None:
                update['last_slot'] = slot
            try:
                await asyncio.to_thread(self._change, **update)
                result = await asyncio.to_thread(self._pipeline, probe_only)
                final = dict(phase='complete', stage='complete', last_recovery_at=result['restore_checked_at'], notice_state='clear')
                final.update(last_success=result, last_success_at=result['created_at'])
                await asyncio.to_thread(self._change, **final)
                log.info('Respaldo %s completado con descarga y recuperación verificadas', 'diario' if slot else 'manual/prueba')
                return result
            except asyncio.CancelledError:
                # Una entrega interrumpida se revisa al siguiente arranque; no se repite a ciegas.
                raise
            except Exception as original:
                error = original if isinstance(original, BackupFailure) else BackupFailure('storage', 'No se pudo completar el registro del respaldo.')
                try:
                    await asyncio.to_thread(self._change, phase='failed', error_stage=error.stage, error_message=str(error), last_failure_at=now_iso())
                except BackupFailure:
                    log.error('No se pudo persistir el fallo del respaldo')
                log.error('Fallo de respaldo: etapa=%s', error.stage)
                await self.failure_notice(operation, error)
                raise error from None

    async def failure_notice(self, operation, error):
        state = await asyncio.to_thread(self._copy)
        if operation in self.notice_operations or (state.get('notice_operation') == operation and state.get('notice_state') in ('claimed', 'sent')):
            return
        self.notice_operations.add(operation)
        try:
            await asyncio.to_thread(self._change, notice_operation=operation, notice_state='claimed')
        except BackupFailure:
            log.error('No se pudo persistir el aviso; se intentará enviarlo una vez en este proceso')
        try:
            channel = self.bot.get_channel(self.alert_channel_id) or await self.bot.fetch_channel(self.alert_channel_id)
            if channel.guild.id != self.guild_id:
                raise BackupFailure('configuration', 'El canal de avisos pertenece a otro servidor.')
            embed = discord.Embed(title='🚨 RESPALDO NO CONFIRMADO | LA VENGANZA RP', description=f"Etapa: **{error.stage}**\n{error}\n\nUsa `/estado-bot` para revisar el estado y `/respaldo crear` para un nuevo intento. La base activa no fue reemplazada.", color=0xD60000)
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            try:
                await asyncio.to_thread(self._change, notice_state='sent')
            except BackupFailure:
                log.error('Aviso enviado; no se pudo guardar su confirmación persistente')
        except Exception:
            log.error('No se pudo confirmar el aviso de respaldo. Revisa permisos del canal Staff y /estado-bot.')

    async def tick(self, now=None):
        if not self.enabled or self.config_error:
            return
        if not await asyncio.to_thread(setting,self.path,'backups','automatic',self.enabled):return
        self.last_check_at = int(datetime.now(timezone.utc).timestamp())
        if self.lock.locked() or (self.manual_task is not None and not self.manual_task.done()):
            return
        state = await asyncio.to_thread(self._copy)
        if state.get('phase') == 'interrupted':
            await self.failure_notice(state.get('operation', 'interrupted'), BackupFailure('interrupted', 'El proceso se reinició antes de confirmar el respaldo. No se reenvía una entrega incierta.'))
        slot = self.slot(now or datetime.now(timezone.utc))
        if state.get('last_slot') == slot:
            return
        await self.execute(slot=slot)

    async def loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self.tick()
            except Exception:
                log.error('El respaldo diario no pudo completarse. Consulta /estado-bot.')
            await asyncio.sleep(60)

    async def describe(self):
        state = await asyncio.to_thread(self._copy)
        return dict(enabled=self.enabled and setting(self.path,'backups','automatic',self.enabled), time_pr=setting(self.path,'backups','time',self.time_pr), config_error=self.config_error, phase=state.get('phase', 'not_run'), stage=state.get('stage'), last_success_at=state.get('last_success_at'), last_recovery_at=state.get('last_recovery_at'), error_stage=state.get('error_stage'), busy=self.lock.locked() or (self.manual_task is not None and not self.manual_task.done()), last_check_at=self.last_check_at, scheduler_active=self.task is not None and not self.task.done())

    async def admin(self, interaction):
        if interaction.guild_id != self.guild_id or not isinstance(interaction.user, discord.Member) or not is_bot_admin(interaction.user):
            raise app_commands.CheckFailure('Solo administradores autorizados pueden gestionar respaldos.')
        return True

    def launch(self, interaction, probe_only=False):
        if self.config_error:
            raise BackupFailure('configuration', self.config_error)
        if self.lock.locked() or (self.manual_task is not None and not self.manual_task.done()):
            raise BackupFailure('busy', 'Ya hay una operación de respaldo en curso.')
        self.manual_task = asyncio.create_task(self._manual(interaction, probe_only), name='manual-drive-backup')

    async def _manual(self, interaction, probe_only):
        try:
            await self.execute(probe_only=probe_only)
            message = '✅ Copia de Drive descargada y restaurada en un archivo temporal. Integridad, esquema y conteos correctos.' if probe_only else '✅ Respaldo subido a Drive y recuperación de prueba verificada. La base activa no se reemplazó.'
        except BackupFailure as error:
            message = f'❌ No se confirmó la operación ({error.stage}). Consulta /estado-bot y la guía RESPALDOS_DRIVE.md.'
        try:
            await interaction.followup.send(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.info('La interacción de respaldo expiró; el resultado sigue disponible en /estado-bot')

    def commands(self):
        @self.group.command(name='crear', description='Crea una copia en Drive y prueba su recuperación sin tocar la base activa')
        @app_commands.check(self.admin)
        async def create(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                self.launch(interaction)
            except BackupFailure as error:
                await interaction.followup.send(f'❌ {error}', ephemeral=True)
                return
            await interaction.followup.send('⏳ Respaldo iniciado. Recibirás el resultado aquí; también puedes consultar /estado-bot.', ephemeral=True)

        @self.group.command(name='probar', description='Descarga de Drive una copia registrada y prueba su restauración aislada')
        @app_commands.check(self.admin)
        async def probe(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                self.launch(interaction, probe_only=True)
            except BackupFailure as error:
                await interaction.followup.send(f'❌ {error}', ephemeral=True)
                return
            await interaction.followup.send('⏳ Prueba de recuperación iniciada. La base activa no se reemplazará.', ephemeral=True)
