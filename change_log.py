"""Durable change history; read-only server snapshots and manual restoration instructions."""
import asyncio
from contextlib import closing
import io
import json
import logging
import os
from pathlib import Path
import sqlite3
import time

import discord
from discord import app_commands

log=logging.getLogger('LaVenganzaRP.changes')
RELEASE='minigames-v1'
SUMMARY='Añade minijuegos desde un panel en General: 50 imágenes recreadas de lugares de GTA V, 25 preguntas de roleplay y 25 acertijos, con pistas y respuestas privadas. Cada pregunta correcta paga 25 monedas al saldo de la tienda una vez por jugador, con acierto, saldo y recibo en una misma transacción. Incluye progreso y ranking persistentes. No cambia canales, roles ni permisos.'
RESTORE=('Para retirar los minijuegos, desplegar 1838de442938bcf1cffbc2a14e66067e05d19b02 conservando la SQLite actual. No restaurar una base antigua, retirar monedas pagadas ni borrar lv_game_* o movimientos minigame:*. Los controles del juego dejarán de estar atendidos al retirar el código; no borrar mensajes históricos de General para revertir. Ver MINIJUEGOS.md. '
         'Conservar reclutamiento, tickets, fotos, podios, archivos, votos, ajustes, compras, saldos y AutoMod. La administración sigue asignando el rol después de aceptar una solicitud de staff. '
         'Los accesos temporales de entrevista siguen a cargo del sistema de reclutamiento; no retirar ni sobrescribir sus registros lv_recruit_voice. '
         'No reiniciar daily_server_up_slot ni duplicar anuncios o premios. Nunca modificar Owner, Programador, Admin o Súper Admin ni los permisos de escribir de Ciudadanos.')


class Journal:
    def __init__(self,path):
        self.path=path

    def db(self):
        return sqlite3.connect(self.path,timeout=10)

    def initialize(self):
        with closing(self.db()) as db,db:
            db.execute('''CREATE TABLE IF NOT EXISTS bot_changes(
                id INTEGER PRIMARY KEY, change_key TEXT UNIQUE NOT NULL, created INTEGER NOT NULL,
                finished INTEGER, title TEXT NOT NULL, status TEXT NOT NULL, summary TEXT NOT NULL,
                restore TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL DEFAULT '{}',
                message_id TEXT)''')

    def begin(self,key,title,summary,restore,before):
        with closing(self.db()) as db,db:
            db.execute("INSERT OR IGNORE INTO bot_changes(change_key,created,title,status,summary,restore,before_json) VALUES (?,?,?,'iniciado',?,?,?)",
                       (key,int(time.time()),title,summary,restore,json.dumps(before,ensure_ascii=False)))
            return db.execute('SELECT id FROM bot_changes WHERE change_key=?',(key,)).fetchone()[0]

    def finish(self,rid,status,after):
        with closing(self.db()) as db,db:
            db.execute('UPDATE bot_changes SET status=?,finished=?,after_json=? WHERE id=?',
                       (status,int(time.time()),json.dumps(after,ensure_ascii=False),rid))

    def rows(self,limit=10,offset=0,pending=False):
        with closing(self.db()) as db:
            db.row_factory=sqlite3.Row
            where="WHERE message_id IS NULL AND status!='iniciado'" if pending else ''
            return [dict(r) for r in db.execute(f'SELECT * FROM bot_changes {where} ORDER BY id DESC LIMIT ? OFFSET ?',(limit,offset))]

    def get(self,rid):
        with closing(self.db()) as db:
            db.row_factory=sqlite3.Row
            row=db.execute('SELECT * FROM bot_changes WHERE id=?',(rid,)).fetchone()
            return dict(row) if row else None

    def mark_sent(self,rid,message):
        with closing(self.db()) as db,db:
            db.execute('UPDATE bot_changes SET message_id=? WHERE id=?',(str(message),rid))

    def latest_state(self):
        with closing(self.db()) as db:
            row=db.execute("SELECT after_json FROM bot_changes WHERE change_key LIKE 'release:%' AND status='completado' ORDER BY id DESC LIMIT 1").fetchone()
            return json.loads(row[0]) if row else {}


async def server_snapshot(guild):
    channels=await guild.fetch_channels()
    roles=await guild.fetch_roles()
    return dict(roles=[dict(id=str(r.id),name=r.name,position=r.position,permissions=str(r.permissions.value),
                           color=r.color.value,hoist=r.hoist) for r in roles],
                channels=[dict(id=str(c.id),name=c.name,parent=str(c.category_id) if c.category_id else None,
                    position=c.position,type=str(c.type),topic=getattr(c,'topic',None),
                    overwrites=[dict(id=str(o.id),type=o.type,allow=str(o.allow),deny=str(o.deny))
                                for o in c._overwrites]) for c in channels])


def change_embed(row):
    embed=discord.Embed(title=f"🧾 Cambio #{row['id']} · {row['title']}"[:256],color=0xBE2335,
        description=row['summary'][:3000])
    embed.add_field(name='Fecha y estado',value=f"<t:{row['created']}:F> · {row['status']}",inline=False)
    embed.add_field(name='Cómo restaurar',value=row['restore'][:1024],inline=False)
    embed.set_footer(text=f"/cambios detalle registro:{row['id']} · Copias antes/después · Acceso privado")
    return embed


class ChangeLog:
    def __init__(self,bot,path,guild_id):
        self.bot,self.guild_id=bot,guild_id
        self.journal=Journal(path)
        self.lock=asyncio.Lock()
        self.release_recorded=False
        self.group=app_commands.Group(name='cambios',description='Historial y copias de cambios del bot',
                                     default_permissions=discord.Permissions(administrator=True))
        self.register()

    def authorize(self,i):
        if i.guild_id!=self.guild_id or not i.user.guild_permissions.administrator:
            raise app_commands.CheckFailure('Solo administradores del servidor pueden consultar estas copias.')

    def register(self):
        @self.group.command(name='historial',description='Ver qué cambió y cuándo')
        async def history(i:discord.Interaction,pagina:app_commands.Range[int,1,1000000]=1):
            self.authorize(i)
            await i.response.defer(ephemeral=True)
            rows=await asyncio.to_thread(self.journal.rows,10,(pagina-1)*10)
            lines=[f"**#{r['id']} · {r['title']}**\n<t:{r['created']}:f> · {r['status']}\n{r['summary'][:180]}" for r in rows]
            await i.followup.send(embed=discord.Embed(title='🧾 Historial de cambios',description=('\n\n'.join(lines) or 'No hay cambios en esta página.')[:4000],color=0xBE2335),ephemeral=True,
                                  allowed_mentions=discord.AllowedMentions.none())

        @self.group.command(name='detalle',description='Ver restauración y descargar las copias antes/después')
        async def detail(i:discord.Interaction,registro:app_commands.Range[int,1,1000000000]):
            self.authorize(i)
            await i.response.defer(ephemeral=True)
            row=await asyncio.to_thread(self.journal.get,registro)
            if not row:
                return await i.followup.send('Ese registro no existe.',ephemeral=True)
            export=dict(row)
            export['before']=json.loads(export.pop('before_json'))
            export['after']=json.loads(export.pop('after_json'))
            payload=json.dumps(export,ensure_ascii=False,indent=2).encode()
            await i.followup.send(embed=change_embed(row),file=discord.File(io.BytesIO(payload),filename=f'cambio-{registro}.json'),
                                  ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

        @self.group.error
        async def error(i,exc):
            if isinstance(exc,app_commands.CheckFailure):
                await i.response.send_message(str(exc),ephemeral=True)
            else:
                log.error('Change log command failed',exc_info=exc)
                sender=i.followup.send if i.response.is_done() else i.response.send_message
                await sender('No se pudo consultar el registro. Inténtalo de nuevo.',ephemeral=True)

    async def tracked(self,env,title,operation,request_id=None,snapshot=None):
        request=request_id or os.getenv(env,'').strip()
        if not request:
            return await operation()
        guild=self.bot.get_guild(self.guild_id)
        async def state():
            return await snapshot() if snapshot else await server_snapshot(guild)
        before=await state()
        rid=await asyncio.to_thread(self.journal.begin,f'operation:{env}:{request}',title,
            f'Operación administrativa del bot. Solicitud: {request}.',RESTORE,before)
        try:
            result=await operation()
            after=await state()
        except Exception as error:
            await asyncio.to_thread(self.journal.finish,rid,'fallido',dict(error_type=type(error).__name__,state=await state()))
            raise
        await asyncio.to_thread(self.journal.finish,rid,'completado',after)
        return result

    async def ready(self):
        async with self.lock:
            guild=self.bot.get_guild(self.guild_id)
            if not self.release_recorded:
                version=os.getenv('RAILWAY_GIT_COMMIT_SHA') or RELEASE
                before=await asyncio.to_thread(self.journal.latest_state)
                rid=await asyncio.to_thread(self.journal.begin,'release:'+version,'Versión '+version[:12],
                    SUMMARY,RESTORE,before)
                existing=await asyncio.to_thread(self.journal.get,rid)
                if existing['status']!='completado':
                    await asyncio.to_thread(self.journal.finish,rid,'completado',await server_snapshot(guild))
                self.release_recorded=True
            await self.publish(guild)

    async def publish(self,guild):
        if os.getenv('CHANGE_LOG_DISCORD_PUBLISH','0')!='1':
            return
        saved=self.bot.economy.store.config('audit_channel')
        if not saved:
            return
        channel=await self.bot.fetch_channel(int(saved))
        if channel.guild.id!=self.guild_id or channel.permissions_for(guild.default_role).view_channel:
            raise ValueError('El registro de cambios requiere el canal privado existente')
        for row in await asyncio.to_thread(self.journal.rows,20,0,True):
            # Reconcile a sent response that was interrupted before the durable receipt.
            marker=f"/cambios detalle registro:{row['id']} · Copias antes/después · Acceso privado"
            found=None
            async for message in channel.history(limit=100):
                if message.author.id==self.bot.user.id and any(e.footer.text==marker for e in message.embeds):
                    found=message.id
                    break
            if found is None:
                message=await channel.send(embed=change_embed(row),allowed_mentions=discord.AllowedMentions.none())
                found=message.id
            await asyncio.to_thread(self.journal.mark_sent,row['id'],found)
            log.info('CHANGE_LOG published id=%s channel=%s message=%s',row['id'],channel.id,found)
        log.info('CHANGE_LOG ready release=%s',RELEASE)
