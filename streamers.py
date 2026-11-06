import asyncio
import json
import re
import secrets
import sqlite3
import sys
import time
from contextlib import contextmanager, closing
from pathlib import Path

import discord
from discord import app_commands

from stream_proof import public_link, supported_url


SCHEMA = """
CREATE TABLE IF NOT EXISTS streamer_config (
 guild INTEGER PRIMARY KEY, role INTEGER NOT NULL, minimum INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS streamer_requests (
 id INTEGER PRIMARY KEY, guild INTEGER NOT NULL, member INTEGER NOT NULL,
 code TEXT NOT NULL UNIQUE, issued INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'nueva',
 proof TEXT, owner TEXT, followers INTEGER, reviewer INTEGER, checked INTEGER DEFAULT 0,
 UNIQUE(guild,member), UNIQUE(guild,owner)
);
"""


def decision(data, code, minimum):
    if data is None:
        return "pendiente"
    title = " ".join(data["title"].casefold().split())
    if code.casefold() not in title or "la venganza rp" not in title:
        return "falta_titulo"
    if data["followers"] < minimum:
        return "faltan_seguidores"
    return "verificada"


async def inspect_stream(url):
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(Path(__file__).with_name("stream_proof.py")), url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        output, _ = await asyncio.wait_for(proc.communicate(), timeout=35)
        return json.loads(output) if proc.returncode == 0 else None
    except (ValueError, TimeoutError):
        return None
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


class Streamers(app_commands.Group, name="streamer", description="Solicitudes para el rol Streamer"):
    def __init__(self, path):
        super().__init__(guild_only=True)
        self.path = path
        self.lock = asyncio.Lock()
        self.slots = asyncio.Semaphore(2)

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            yield conn

    def start(self):
        with self.db() as db:
            db.executescript(SCHEMA)

    def request(self, guild, member):
        with self.db() as db:
            return db.execute("SELECT * FROM streamer_requests WHERE guild=? AND member=?", (guild, member)).fetchone()

    def config(self, guild):
        with self.db() as db:
            row = db.execute("SELECT * FROM streamer_config WHERE guild=?", (guild.id,)).fetchone()
        if row:
            return guild.get_role(row["role"]), row["minimum"]
        matches = self.named_roles(guild)
        return (matches[0] if len(matches) == 1 else None), 50

    @staticmethod
    def named_roles(guild):
        return [role for role in guild.roles if re.sub(r"[\W_]+", "", role.name.casefold()) in {"streamer", "streamers"}]

    @staticmethod
    def safe_role(role):
        return role and role.is_assignable() and role.permissions.value == 0

    @app_commands.command(description="Elige el rol de creador y el mínimo de seguidores")
    @app_commands.checks.has_permissions(administrator=True)
    async def configurar(self, interaction: discord.Interaction, rol: discord.Role,
                         minimo: app_commands.Range[int, 1, 10000000] = 50):
        if not self.safe_role(rol):
            return await interaction.response.send_message("Elige un rol sin permisos de servidor y por debajo del rol del bot. El bot necesita Gestionar roles.", ephemeral=True)
        async with self.lock:
            with self.db() as db:
                db.execute("INSERT OR REPLACE INTO streamer_config VALUES(?,?,?)", (interaction.guild_id, rol.id, minimo))
        await interaction.response.send_message(f"Las nuevas verificaciones entregarán {rol.mention} con un mínimo de {minimo} seguidores en un canal.", ephemeral=True)
        panel = interaction.client.streamer_panel
        panel.published = False
        if not panel.install.is_running():
            panel.install.start()

    @app_commands.command(description="Recibe el código personal para verificar tu directo o repetición")
    async def solicitar(self, interaction: discord.Interaction):
        await self.issue_code(interaction)

    async def issue_code(self, interaction):
        guild, member = interaction.guild_id, interaction.user.id
        _, minimum = self.config(interaction.guild)
        async with self.lock:
            row = self.request(guild, member)
            now = int(time.time())
            if row and row["state"] in {"verificada", "entregada", "pendiente"}:
                return await interaction.response.send_message(f"Tu solicitud está {row['state']}. Pulsa **Ver mi estado** en el panel.", ephemeral=True)
            if not row or row["state"] == "rechazada" or now-row["issued"] >= 86400:
                code = "LVRP-" + secrets.token_hex(5).upper()
                with self.db() as db:
                    db.execute("INSERT INTO streamer_requests(guild,member,issued,code) VALUES(?,?,?,?) "
                               "ON CONFLICT(guild,member) DO UPDATE SET issued=excluded.issued,code=excluded.code,"
                               "state='nueva',proof=NULL,owner=NULL,reviewer=NULL,followers=NULL,checked=0",
                               (guild, member, now, code))
            else:
                code = row["code"]
        await interaction.response.send_message(
            f"Necesitas **{minimum} seguidores** (suscriptores en YouTube) en un canal. "
            f"Pon **La Venganza RP {code}** en el título de tu directo o repetición pública de la ciudad. "
            "Luego pulsa **Enviar enlace** en el panel o usa **/streamer verificar**. Tu código dura 24 horas. "
            "Aceptamos Twitch, YouTube, TikTok y otras plataformas.", ephemeral=True)

    @app_commands.command(description="Comprueba el enlace de tu directo o repetición pública")
    async def verificar(self, interaction: discord.Interaction, enlace: app_commands.Range[str, 1, 500]):
        await self.check_link(interaction, enlace)

    async def check_link(self, interaction, enlace):
        try:
            supported = supported_url(enlace)
        except ValueError:
            return await interaction.response.send_message("Pega la dirección HTTPS completa de tu directo o repetición.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild, member = interaction.guild_id, interaction.user.id
        async with self.lock:
            row = self.request(guild, member)
            now = int(time.time())
            if not row or row["state"] == "rechazada":
                return await interaction.followup.send("Pulsa **Solicitar código** en el panel para empezar.", ephemeral=True)
            if row["state"] in {"verificada", "entregada"}:
                return await interaction.followup.send(await self.deliver(interaction.guild, row), ephemeral=True)
            if now-row["issued"] >= 86400:
                return await interaction.followup.send("Código vencido. Consulta /streamer estado si está pendiente de revisión, o usa /streamer solicitar para renovarlo.", ephemeral=True)
            if now-row["checked"] < 60 or self.slots.locked():
                return await interaction.followup.send("Espera un minuto y vuelve a intentarlo.", ephemeral=True)
            # One verification per member at a time. A stale review uses the old evidence ID.
            with self.db() as db:
                db.execute("UPDATE streamer_requests SET state='comprobando',proof=?,checked=? WHERE id=?", (enlace, now, row["id"]))
        async with self.slots:
            data = await inspect_stream(supported[1]) if supported else None
        async with self.lock:
            current = self.request(guild, member)
            if current["code"] != row["code"] or current["checked"] != now or current["state"] != "comprobando":
                return await interaction.followup.send("La solicitud cambió. Consulta /streamer estado.", ephemeral=True)
            _, minimum = self.config(interaction.guild)
            state = decision(data, row["code"], minimum)
            try:
                with self.db() as db:
                    db.execute("UPDATE streamer_requests SET state=?,owner=?,followers=? WHERE id=?",
                               (state, data["owner"] if state == "verificada" else None,
                                data["followers"] if data else None, row["id"]))
            except sqlite3.IntegrityError:
                with self.db() as db:
                    db.execute("UPDATE streamer_requests SET state='canal_en_uso' WHERE id=?", (row["id"],))
                state = "canal_en_uso"
            if state == "verificada":
                msg = await self.deliver(interaction.guild, self.request(guild, member))
            elif state == "pendiente":
                msg = "Tu enlace quedó pendiente de revisión por el staff. Conserva el código en el título hasta que lo revisen."
            elif state == "falta_titulo":
                msg = f"Pon La Venganza RP y {row['code']} en el título del directo e inténtalo de nuevo."
            elif state == "canal_en_uso":
                msg = "Este canal ya está vinculado a otra solicitud."
            else:
                msg = f"El canal muestra {data['followers']} seguidores. El mínimo actual es {minimum}."
        await interaction.followup.send(msg, ephemeral=True)

    async def deliver(self, guild, row):
        if row["state"] == "entregada":
            return "Esta solicitud ya recibió el rol Streamer."
        role, minimum = self.config(guild)
        if row["followers"] < minimum:
            with self.db() as db:
                db.execute("UPDATE streamer_requests SET state='faltan_seguidores', owner=NULL WHERE id=?", (row["id"],))
            return "El mínimo cambió. Vuelve a verificar tu canal."
        with self.db() as db:
            configured = db.execute("SELECT 1 FROM streamer_config WHERE guild=?", (guild.id,)).fetchone()
        if not configured and not role and not self.named_roles(guild) and guild.me.guild_permissions.manage_roles:
            try:
                role = await guild.create_role(name="Streamer", permissions=discord.Permissions.none(),
                                               reason="Rol para creadores verificados de La Venganza RP")
            except discord.HTTPException:
                role = None
            if role:
                with self.db() as db:
                    db.execute("INSERT OR IGNORE INTO streamer_config VALUES(?,?,?)", (guild.id, role.id, minimum))
        if not self.safe_role(role) or not guild.me.guild_permissions.manage_roles:
            return "Solicitud verificada. Un administrador debe configurar un rol asignable con /streamer configurar y dar al bot Gestionar roles. Después usa /streamer estado."
        try:
            member = await guild.fetch_member(row["member"])
            if role not in member.roles:
                await member.add_roles(role, reason="Verificación Streamer de La Venganza RP")
        except discord.HTTPException:
            return "Solicitud verificada. Discord no permitió entregar el rol. Puedes reintentar con /streamer estado."
        with self.db() as db:
            db.execute("UPDATE streamer_requests SET state='entregada' WHERE id=?", (row["id"],))
        return f"✅ Verificación completada. Recibiste el rol {role.mention}."

    @app_commands.command(description="Consulta tu solicitud o reintenta la entrega del rol verificado")
    async def estado(self, interaction: discord.Interaction):
        await self.show_status(interaction)

    async def show_status(self, interaction):
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            row = self.request(interaction.guild_id, interaction.user.id)
            if row and row["state"] == "verificada":
                msg = await self.deliver(interaction.guild, row)
            elif row:
                msg = "Estado de tu solicitud: **" + row["state"].replace("_", " ") + "**."
            else:
                msg = "Pulsa **Solicitar código** en el panel para empezar."
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(description="Lista privada de pruebas pendientes para administración")
    @app_commands.checks.has_permissions(administrator=True)
    async def pendientes(self, interaction: discord.Interaction, pagina: app_commands.Range[int, 1, 10000] = 1):
        with self.db() as db:
            rows = db.execute("SELECT * FROM streamer_requests WHERE guild=? AND state='pendiente' ORDER BY checked,id LIMIT 2 OFFSET ?",
                              (interaction.guild_id, (pagina-1)*2)).fetchall()
        lines = [f"<@{r['member']}> · código `{r['code']}` · revisión `{r['id']}-{r['checked']}`\n<{r['proof']}>" for r in rows]
        await interaction.response.send_message("\n".join(lines) or "Sin solicitudes pendientes en esta página.", ephemeral=True)

    @app_commands.command(description="Resuelve una prueba revisada en la plataforma (solo administración)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(revision="Referencia que muestra /streamer pendientes", aprobar="Confirmas titularidad, contenido de la ciudad y directo público",
                           seguidores="Conteo comprobado en la plataforma", canal="URL pública del perfil verificado para aprobación manual")
    async def revisar(self, interaction: discord.Interaction, revision: str, aprobar: bool,
                      seguidores: app_commands.Range[int, 0, 2000000000] = 0, canal: str = ""):
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            with self.db() as db:
                row = db.execute("SELECT * FROM streamer_requests WHERE guild=? AND id || '-' || checked=? AND state='pendiente'",
                                 (interaction.guild_id, revision)).fetchone()
            if not row:
                return await interaction.followup.send("Revisión vencida o ya resuelta.", ephemeral=True)
            if row["member"] == interaction.user.id:
                return await interaction.followup.send("Otro administrador debe revisar esta solicitud.", ephemeral=True)
            _, minimum = self.config(interaction.guild)
            owner = None
            if aprobar:
                try:
                    url = public_link(canal)
                    if not url.path.strip("/") or seguidores < minimum:
                        raise ValueError()
                except ValueError:
                    return await interaction.followup.send(f"Comprueba el perfil, el código en el título del directo de la ciudad y un mínimo de {minimum} seguidores. Indica el enlace del perfil y su conteo.", ephemeral=True)
                owner = "perfil:" + url.hostname.removeprefix("www.") + url.path.rstrip("/")
            try:
                with self.db() as db:
                    db.execute("UPDATE streamer_requests SET state=?,followers=?,owner=?,reviewer=? WHERE id=?",
                               ("verificada" if aprobar else "rechazada", seguidores, owner, interaction.user.id, row["id"]))
            except sqlite3.IntegrityError:
                return await interaction.followup.send("Este perfil ya está vinculado.", ephemeral=True)
            msg = "Solicitud rechazada."
            if aprobar:
                msg = await self.deliver(interaction.guild, self.request(interaction.guild_id, row["member"]))
        await interaction.followup.send(f"<@{row['member']}> · {msg}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            return await interaction.response.send_message("Este comando requiere permisos de administrador.", ephemeral=True)
        raise error
