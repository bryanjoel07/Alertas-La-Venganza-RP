"""EssChino Studio: only the five requested store categories and ticket workflows."""
import asyncio
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import sqlite3

from aiohttp import web
import discord
from discord import app_commands

from esschino import EssChino, ASSETS, PROTECTED_CHANNEL, CHANNELS, valid_shop_url
from store_community import StoreCommunity, IdeaModal, ReviewModal
from studio_journal import ChangeLog
from welcome_cards import WelcomeCards
from vice_district import ViceDistrict
from vice_design import GUILD_ID as VICE_GUILD_ID

log = logging.getLogger('EssChinoStudio')
GUILD_ID = 1514871828189941881
BOT_ID = 1571639486591402174
GUILD = discord.Object(id=GUILD_ID)
RELEASE = 'esschino-studio-store-domain-pending-v5'


class StoreBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = False
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.path = os.getenv('DB_PATH', '/data/esschino.sqlite3')
        self.tree = app_commands.CommandTree(self)
        self.changes = ChangeLog(self, self.path, GUILD_ID)
        self.esschino = EssChino(self, self.path)
        self.community = StoreCommunity(self.esschino, self.path)
        self.esschino.community = self.community
        self.welcome = WelcomeCards(self.esschino, self.path)
        self.esschino.welcome = self.welcome
        self.ready_lock = asyncio.Lock()
        self.configured_event = asyncio.Event()
        self.configured = False
        self.http_runner = None
        self.register_commands()
        self.vice = ViceDistrict(self, Path(self.path).with_name('vice-district.sqlite3'))

    def authorize(self, i, admin=False):
        if i.guild_id != GUILD_ID or not isinstance(i.user, discord.Member) or i.user.bot:
            raise ValueError('Usa este bot dentro del servidor EssChino Studio.')
        if admin and not i.user.guild_permissions.administrator:
            raise ValueError('Esta función requiere Administración de EssChino Studio.')

    async def setup_hook(self):
        if self.user.id != BOT_ID:
            raise ValueError('Solo el bot nuevo de EssChino Studio puede ejecutar este proyecto.')
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA synchronous=FULL')
        await asyncio.to_thread(self.changes.journal.initialize)
        await self.esschino.start()
        await self.community.start()
        await self.welcome.start()
        await self.vice.start()
        app = await self.application_info()
        # Use message-content access only when Discord already grants it. The
        # setup, forms, purchases, voting and commands work without privileged intents.
        flags = app.flags
        content = flags.gateway_message_content or flags.gateway_message_content_limited
        if content:
            self._connection._intents.message_content = True
        members = flags.gateway_guild_members or flags.gateway_guild_members_limited
        if members:
            self._connection._intents.members = True
        log.info('STUDIO intents message_content=%s members=%s', bool(content), bool(members))
        application = web.Application()
        async def health(request):
            return web.json_response(dict(service='EssChino Studio Bot', connected=self.is_ready(),
                configured=self.configured, vice_configured=self.vice.configured))
        application.router.add_get('/health', health)
        self.http_runner = web.AppRunner(application)
        await self.http_runner.setup()
        await web.TCPSite(self.http_runner, '0.0.0.0', int(os.getenv('PORT', '8080'))).start()

    async def on_ready(self):
        try:
            await self.vice.ready()
        except Exception:
            log.exception('VICE_SETUP failed')
        async with self.ready_lock:
            if self.configured:
                return
            try:
                await self.esschino.ready()
                if not self.esschino.store.get('setup_complete'):
                    raise ValueError('La instalación todavía no está completa; revisa los permisos del bot en EssChino Studio.')
                guild = self.get_guild(GUILD_ID)
                await self.esschino.languages.ready(guild, [row[0] for row in CHANNELS])
                await self.welcome.install(guild)
                await self.esschino.launch.ready(guild)
                if not self.intents.members:
                    raise ValueError('Discord todavía no habilitó la recepción de entradas de miembros para el nuevo bot.')
                async def command_state():
                    return {'guild_id': GUILD_ID, 'commands': [c.to_dict() for c in await self.tree.fetch_commands(guild=GUILD)]}
                commands = await self.changes.tracked('STUDIO_COMMANDS', 'Registrar únicamente comandos de tienda',
                    lambda: self.tree.sync(guild=GUILD), request_id=RELEASE, snapshot=command_state)
                log.info('STUDIO commands_synced guild=%s commands=%s', GUILD_ID, [c.name for c in commands])
                digest = hashlib.sha256((ASSETS / 'logo.jpg').read_bytes()).hexdigest()
                if self.esschino.store.get('bot_avatar') != digest:
                    async def avatar():
                        await self.user.edit(avatar=(ASSETS / 'logo.jpg').read_bytes())
                        await self.esschino.call('put', 'bot_avatar', digest)
                    await self.esschino.tracked('bot-avatar-v1', 'Aplicar logo al nuevo bot de tienda', avatar)
                self.configured = True
                self.configured_event.set()
                log.info('STUDIO_READY bot=%s guild=%s release=%s independent=True store_only=True', self.user.id, guild.id, RELEASE)
            except Exception:
                log.exception('STUDIO_SETUP failed')

    async def on_message(self, message):
        if message.guild and message.guild.id == GUILD_ID:
            try:
                await self.esschino.observe(message)
            except Exception:
                log.exception('STUDIO ticket_archive_failed channel=%s', message.channel.id)

    async def on_member_join(self, member):
        if member.guild.id == VICE_GUILD_ID:
            try:
                await self.vice.member_join(member)
            except discord.NotFound:
                pass
            except Exception:
                log.exception('VICE_WELCOME failed member=%s', member.id)
            return
        if member.guild.id != GUILD_ID or member.bot:
            return
        await self.configured_event.wait()
        try:
            # A queued welcome must not announce someone who left while setup
            # was finishing; use their current name and profile photo as well.
            current = await member.guild.fetch_member(member.id)
            await self.welcome.joined(current)
        except discord.NotFound:
            return
        except Exception:
            log.exception('WELCOME_CARD member_join_failed member=%s', member.id)

    async def on_raw_member_remove(self, payload):
        if payload.guild_id != VICE_GUILD_ID:
            return
        try:
            await self.vice.member_remove(payload.user, guild=self.get_guild(payload.guild_id))
        except Exception:
            log.exception('VICE_GOODBYE failed member=%s', payload.user.id)

    async def on_voice_state_update(self, member, before, after):
        if member.guild.id != VICE_GUILD_ID:
            return
        try:
            await self.vice.voice.voice_state_update(member, before, after)
        except Exception:
            log.exception('VICE_VOICE_STATE failed member=%s', member.id)

    async def close(self):
        await self.vice.close()
        if self.welcome.task:
            self.welcome.task.cancel()
            await asyncio.gather(self.welcome.task, return_exceptions=True)
        if self.http_runner:
            await self.http_runner.cleanup()
        await super().close()

    def register_commands(self):
        @self.tree.command(name='ayuda', description='Canales y funciones de EssChino Studio', guild=GUILD)
        async def help(i: discord.Interaction):
            self.authorize(i)
            c = self.esschino.channel_id
            await i.response.send_message(embed=self.esschino.embed('🧭 EssChino Studio',
                f'🛍️ **Tienda:** <#{c("shop")}>\n📦 **Catálogo:** <#{c("catalog")}>\n'
                f'🎫 **Pedidos y soporte:** <#{c("support")}>\n📚 **Guías:** <#{c("install")}>\n'
                f'💡 **Sugerencias:** <#{c("suggestions")}>\n⭐ **Reseñas:** <#{c("reviews")}>\n\n'
                'Los tickets son privados. No publiques claves de licencia, contraseñas ni datos de pago.'), ephemeral=True)

        @self.tree.command(name='tienda', description='Acceder a la tienda oficial de Tebex', guild=GUILD)
        async def shop(i: discord.Interaction):
            self.authorize(i)
            url = self.esschino.store.get('shop_url')
            pending = self.esschino.panel_values()['pending_shop_url']
            if url:
                text = f'🛍️ Tienda oficial: {url}'
            elif pending:
                text = (f'⏳ La tienda está pendiente de activación en Tebex: `{pending}`. '
                    f'Compras desde Discord todavía no habilitadas. Consultas: <#{self.esschino.channel_id("support")}>.')
            else:
                text = (f'🛍️ Community Sanctions System ya está a la venta en Tebex. '
                    f'Consulta <#{self.esschino.channel_id("shop")}> o solicita el enlace de compra '
                    f'en <#{self.esschino.channel_id("support")}>.')
            await i.response.send_message(text, ephemeral=True)

        @self.tree.command(name='soporte', description='Abrir una consulta privada de compras o scripts', guild=GUILD)
        async def support(i: discord.Interaction):
            self.authorize(i)
            await i.response.send_message(f'🎫 Abre tu ticket en <#{self.esschino.channel_id("support")}>.', ephemeral=True)

        @self.tree.command(name='mis-tickets', description='Ver tus consultas privadas abiertas y cerradas', guild=GUILD)
        async def my_tickets(i: discord.Interaction):
            self.authorize(i)
            await i.response.defer(ephemeral=True)
            rows = await self.esschino.call('tickets', i.user.id)
            lines = [f'{"🟢" if r["state"] == "open" else "🔒"} <#{r["channel"]}> · {r["kind"]}' for r in rows[-25:]]
            await i.followup.send('\n'.join(lines) or 'Todavía no tienes tickets en EssChino Studio.', ephemeral=True)

        @self.tree.command(name='sugerir', description='Proponer una mejora para los scripts o la tienda', guild=GUILD)
        async def suggest(i: discord.Interaction):
            self.authorize(i)
            await i.response.send_modal(IdeaModal(self.community))

        @self.tree.command(name='resena', description='Publicar o actualizar tu reseña como cliente verificado', guild=GUILD)
        async def review(i: discord.Interaction):
            self.community.customer(i)
            await i.response.send_modal(ReviewModal(self.community))

        group = app_commands.Group(name='studio', description='Gestión privada de la tienda EssChino Studio',
                                   default_permissions=discord.Permissions(administrator=True))

        @group.command(name='tienda', description='Conectar el enlace oficial de la tienda Tebex')
        async def configure_shop(i: discord.Interaction, enlace: str):
            self.authorize(i, admin=True)
            url = valid_shop_url(enlace)
            await i.response.defer(ephemeral=True)
            async def apply():
                await self.esschino.call('put', 'shop_url', url)
            await self.esschino.tracked(f'shop-command:{i.id}', 'Conectar la tienda oficial de Tebex', apply)
            await self.esschino.launch.ready(i.guild)
            await i.followup.send('Enlace oficial conectado al panel de compra.', ephemeral=True)

        @group.command(name='publicar', description='Publicar contenido oficial en uno de los canales de la tienda')
        @app_commands.choices(destino=[app_commands.Choice(name=name, value=value) for name,value in [
            ('Anuncios','announcements'), ('Catálogo de scripts','catalog'), ('Demostraciones','demos'),
            ('Ofertas','offers'), ('Actualizaciones','changelog'), ('Guías de instalación','install'),
            ('Preguntas frecuentes','faq'), ('Normas','rules')]])
        async def publish(i: discord.Interaction, destino: app_commands.Choice[str], titulo: str,
                          texto: str, enlace: str | None = None, notificar: bool = False):
            self.authorize(i, admin=True)
            if not (1 <= len(titulo) <= 256 and 1 <= len(texto) <= 3800):
                raise ValueError('Título: hasta 256 caracteres. Texto: hasta 3800 caracteres.')
            if enlace:
                enlace = valid_shop_url(enlace)
            await i.response.defer(ephemeral=True)
            channel = i.guild.get_channel(self.esschino.channel_id(destino.value))
            embed = self.esschino.embed(titulo, texto + (f'\n\n[Más información]({enlace})' if enlace else ''))
            role = self.esschino.role(i.guild, 'updates' if destino.value == 'changelog' else 'news') if notificar else None
            async def apply():
                return await channel.send(content=role.mention if role else None, embed=embed,
                    allowed_mentions=discord.AllowedMentions(roles=[role] if role else [], users=False, everyone=False))
            message = await self.esschino.tracked(f'publish:{i.id}', 'Publicar contenido oficial en ' + destino.value, apply)
            await i.followup.send(f'Publicado: {message.jump_url}', ephemeral=True)

        @group.command(name='cliente', description='Registrar un pedido que comprobaste en Tebex y asignar Cliente')
        async def customer(i: discord.Interaction, miembro: discord.Member, referencia: str):
            self.authorize(i, admin=True)
            if miembro.bot:
                raise ValueError('El rol Cliente corresponde a personas con una compra real.')
            await i.response.defer(ephemeral=True)
            async def apply():
                await self.esschino.call('purchase', referencia, miembro.id, i.user.id)
                await miembro.add_roles(self.esschino.role(i.guild, 'customer'), reason='Pedido comprobado manualmente en Tebex por administración')
            await self.esschino.tracked(f'verify-command:{i.id}', 'Registrar cliente verificado manualmente', apply,
                                       members=(miembro.id, i.user.id))
            await self.esschino.audit(i.guild, f'💎 Cliente verificado manualmente: <@{miembro.id}> · revisó <@{i.user.id}>.')
            await i.followup.send('Pedido registrado y rol Cliente asignado. La comprobación del pago es manual en Tebex.', ephemeral=True)

        @group.command(name='tickets', description='Consultar los casos privados de soporte')
        @app_commands.choices(estado=[app_commands.Choice(name='Abiertos', value='open'), app_commands.Choice(name='Cerrados', value='closed')])
        async def tickets(i: discord.Interaction, estado: app_commands.Choice[str]):
            self.authorize(i, admin=True)
            await i.response.defer(ephemeral=True)
            rows = [r for r in await self.esschino.call('tickets') if r['state'] == estado.value]
            lines = [f'<#{r["channel"]}> · <@{r["owner"]}> · {r["kind"]}' for r in rows[-30:]]
            await i.followup.send('\n'.join(lines) or 'No hay tickets en ese estado.', ephemeral=True)

        @group.command(name='historial', description='Consultar las últimas operaciones administrativas del bot')
        async def history(i: discord.Interaction):
            self.authorize(i, admin=True)
            await i.response.defer(ephemeral=True)
            rows = await asyncio.to_thread(self.changes.journal.rows, 10)
            await i.followup.send('\n'.join(f'**#{r["id"]}** · {r["title"]} · {r["status"]}' for r in rows) or 'Sin operaciones todavía.', ephemeral=True)

        @group.command(name='copia', description='Descargar el estado anterior y posterior de una operación')
        async def copy(i: discord.Interaction, registro: app_commands.Range[int, 1, 10000000]):
            self.authorize(i, admin=True)
            await i.response.defer(ephemeral=True)
            row = await asyncio.to_thread(self.changes.journal.get, registro)
            if not row:
                raise ValueError('No existe ese registro.')
            payload = json.dumps(row, ensure_ascii=False, indent=2).encode()
            if len(payload) > i.guild.filesize_limit:
                raise ValueError('La copia supera el límite de Discord; conserva el archivo privado del volumen de Railway.')
            await i.followup.send(file=discord.File(io.BytesIO(payload), filename=f'esschino-cambio-{registro}.json'), ephemeral=True)

        @group.command(name='estado', description='Estado del bot, los paneles y el almacenamiento de EssChino Studio')
        async def status(i: discord.Interaction):
            self.authorize(i, admin=True)
            await i.response.send_message(f'🟢 Bot independiente conectado.\n'
                f'**Configurado:** {self.configured}\n**Tienda enlazada:** {bool(self.esschino.store.get("shop_url"))}\n'
                f'**Datos:** volumen privado de EssChino Studio.\n**Versión:** {RELEASE}', ephemeral=True)

        self.tree.add_command(group, guild=GUILD)

        @self.tree.error
        async def error(i, error):
            cause = getattr(error, 'original', error)
            text = str(cause) if isinstance(cause, ValueError) else 'No se pudo completar la acción. Contacta con el equipo.'
            if not isinstance(cause, ValueError):
                log.error('STUDIO command_failed type=%s', type(cause).__name__, exc_info=cause)
            send = i.followup.send if i.response.is_done() else i.response.send_message
            await send(text[:1500], ephemeral=True)
