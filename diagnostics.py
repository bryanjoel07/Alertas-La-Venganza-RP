"""Diagnóstico privado: lectura de SQLite y métricas conocidas; no usa secretos."""
from contextlib import closing
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import sqlite3
import time

import discord


def read_database(path):
    source = Path(path).resolve()
    if not source.is_file():
        return dict(ok=False, reason='El archivo de la base no existe.')
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            db.execute('PRAGMA query_only=ON')
            checks = db.execute('PRAGMA quick_check(1)').fetchall()
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = {'settings', 'events', 'registrations', 'meetings'} - tables
            settings = dict(db.execute("SELECT key,value FROM settings WHERE key IN ('last_state','maintenance_active')")) if 'settings' in tables else {}
            counts = {}
            for table in ('events', 'registrations', 'meetings', 'meeting_voice_visits'):
                if table in tables:
                    counts[table] = db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        return dict(ok=checks == [('ok',)] and not missing, integrity=checks == [('ok',)], incomplete=bool(missing), size_bytes=source.stat().st_size, mounted=os.path.ismount(source.parent), settings=settings, counts=counts)
    except (OSError, sqlite3.Error):
        return dict(ok=False, reason='No se pudo leer la base o está ocupada. Consulta Railway.')


def task_state(task):
    if task is None:
        return '⚪ No iniciada'
    if task.cancelled():
        return '🔴 Cancelada'
    if not task.done():
        return '🟢 Activa'
    return '🔴 Terminada con error' if task.exception() is not None else '⚪ Terminada'


def at(value):
    return f'<t:{int(value)}:R>' if value is not None else 'Sin lectura en este proceso'


def status_embed(bot, path, database, backup, automation=None):
    connected = bot.is_ready()
    elapsed = max(0, int(time.monotonic() - bot.started_monotonic))
    hours, rest = divmod(elapsed, 3600)
    minutes, seconds = divmod(rest, 60)
    latency = f'{bot.latency * 1000:.0f} ms' if math.isfinite(bot.latency) else 'Sin medición'
    embed = discord.Embed(title='⚙️ ESTADO DEL BOT | LA VENGANZA RP', description=f"Discord: {'🟢 Conectado' if connected else '🔴 Sin conexión'} · {latency}\nProceso activo: **{hours} h {minutes} m {seconds} s**", color=0xD60000, timestamp=datetime.now(timezone.utc))
    settings = database.get('settings', {})
    states = {'up': '🟢 Disponible', 'down': '🔴 Caído'}
    maintenance = {'1': '🛠️ Activo', '0': 'Inactivo'}.get(settings.get('maintenance_active', '0' if 'settings' in database else ''), 'No registrado')
    monitor = f"Confirmado: {states.get(settings.get('last_state'), 'Sin estado confirmado')}\nMantenimiento: {maintenance}\nÚltima lectura: {at(bot.monitor_last_read)}\nÚltimo error: {at(bot.monitor_last_error)}"
    tracker = bot.tracker
    sources = getattr(bot,'monitor_sources',None)
    if sources:
        labels = {'up':'en línea','down':'caído','stale':'sin actualizar','unreachable':'sin respuesta','unknown':'sin datos',
                  'partial':'parcial','unconfigured':'sin configurar','unavailable':'no disponible'}
        monitor += f"\nFiveM: {labels.get(sources[0],'sin datos')} · Connect: {labels.get(sources[1],'sin datos')}"
    if tracker and tracker.pending in ('up', 'down'):
        wait = max(0, int(time.monotonic() - tracker.since)) if tracker.since is not None else 0
        monitor += f"\nCambio en confirmación: {states[tracker.pending]} · {wait}/90 s"
    embed.add_field(name='📡 Monitor FiveM', value=monitor, inline=False)
    tasks = f"Monitor: {task_state(bot.monitor_task)}\nReuniones: {task_state(bot.meetings.task)}\nEventos: {task_state(bot.event_features.task)}\nÚltimo ciclo de reuniones: {at(bot.meetings.last_check_at)}\nÚltimo ciclo de eventos: {at(bot.event_features.last_check_at)}"
    embed.add_field(name='🔄 Tareas automáticas', value=tasks, inline=False)
    location = discord.utils.escape_markdown(str(path)).replace('@', '@\u200b')[:350]
    if 'reason' in database:
        db_text = f"Ruta: {location}\n❌ {database['reason']}"
    else:
        counts = database['counts']
        db_text = f"Ruta: {location}\nLectura/esquema: {'✅ Correctos' if database['ok'] else '❌ Revisar'}\nSQLite quick_check: {'ok' if database['integrity'] else 'error'}\nArchivo base: {database['size_bytes'] / 1048576:.2f} MB\nMontaje detectado en directorio: {'Sí' if database['mounted'] else 'No confirmado'}\nEventos: {counts.get('events', 0)} · Inscripciones: {counts.get('registrations', 0)}\nReuniones: {counts.get('meetings', 0)} · Presencias de voz: {counts.get('meeting_voice_visits', 0)}"
    embed.add_field(name='💾 SQLite activa', value=db_text, inline=False)
    if not backup['known']:
        backup_text = '⚪ ' + backup['reason'] + '\nEl volumen no sustituye un respaldo externo.'
    else:
        drive = {'verified': '✅ Última subida verificada', 'pending': '⏳ Subida pendiente', 'failed': '❌ Última subida falló', 'not_requested': '⚪ No se solicitó subida'}[backup['drive_state']]
        backup_text = f"Creado: <t:{backup['created_at']}:f>\nIntegridad comprobada al crear: ✅\nCopia local: {'disponible' if backup['local_available'] else 'no encontrada o tamaño diferente'}\nGoogle Drive: {drive}\nNo se comprueba en vivo que Drive conserve el archivo."
    if backup.get('known'):
        restore = {'verified': '✅ Verificada desde Drive', 'failed': '❌ Falló la prueba', 'not_tested': '⚪ Sin prueba registrada'}.get(backup.get('restore_state', 'not_tested'), '⚪ Sin prueba registrada')
        backup_text += f"\nRecuperación: {restore}"
    embed.add_field(name='🗂️ Último respaldo registrado', value=backup_text, inline=False)
    if automation is not None:
        phase = {'not_run': 'Sin ejecución', 'running': 'En curso', 'complete': 'Completado', 'failed': 'Falló', 'interrupted': 'Interrumpido'}.get(automation['phase'], 'Desconocido')
        daily = f"Diario: {'Activado' if automation['enabled'] else 'Desactivado'} · {automation['time_pr']} Puerto Rico\nÚltima operación: {phase}\nEtapa: {automation.get('stage') or 'Sin iniciar'}\nOperación en curso: {'Sí' if automation['busy'] else 'No'}\nÚltima revisión: {at(automation['last_check_at'])}"
        daily += "\nTarea diaria: " + ('Activa' if automation.get('scheduler_active') else 'No iniciada o detenida')
        if automation.get('config_error'):
            daily += '\n⚠️ Configuración inválida: revisa RESPALDOS_DRIVE.md.'
        if automation.get('last_success_at'):
            stamp = int(datetime.fromisoformat(automation['last_success_at']).timestamp())
            daily += f'\nÚltima copia con recuperación verificada: <t:{stamp}:f>'
        embed.add_field(name='☁️ Automatización de respaldos', value=daily, inline=False)
    embed.set_footer(text='Solo administradores · No muestra tokens ni webhooks · Un montaje no verifica una restauración externa')
    return embed
