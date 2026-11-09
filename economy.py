"""Panel persistente, compras privadas y comandos de economía de La Venganza RP."""

import asyncio
import io
import json
import logging
import time
from datetime import datetime
from typing import Literal

import discord
from discord import app_commands

from economy_delivery import LABELS, Delivery
from economy_store import BANNERS, PR, EconomyStore, clean_label
from meetings import ROLES
from profiles_hub import ensure_profiles
from server_fixes import fix_high_priorities
from community_features import CommunityFeatures

log = logging.getLogger("LaVenganzaRP.economia")
SHOP = "🛍️┊𝐓𝐢𝐞𝐧𝐝𝐚-𝐄𝐱𝐜𝐥𝐮𝐬𝐢𝐯𝐞"
PREVIOUS_SHOP_NAMES = {"🛍️・tienda-exclusive", "🛍️┊tienda-exclusive"}
PANEL = "🪙 La Venganza Exclusive"
DETAILS = {
    "badge": "Insignia decorativa para tu perfil",
    "limited": "Insignia de colección numerada para tu perfil",
    "color": "Rol con un color de la paleta",
    "title": "Título mediante un rol decorativo",
    "bio": "Frase personalizada en tu tarjeta",
    "theme": "Tema de color para tu tarjeta",
    "nickname": "Prefijo para tu apodo del servidor",
    "custom_color": "Un rol con el color hexadecimal que elijas",
    "bundle": "Título, color de rol y tema para tu tarjeta",
    "celebration": "Diseño de tu anuncio cuando ganas el primer puesto",
    "voice": "Sala privada con acceso por invitación durante siete días",
    "banner": "Ilustración panorámica para tu perfil, combinable con tu tema",
    "plate": "Placa de perfil con un texto de hasta 10 caracteres, como CHINO-7",
    "signature": "Tu frase en el anuncio si terminas entre los tres primeros",
    "showcase": "Exhibe hasta tres podios que ganaste, con evento y fecha",
    "souvenir": "Entrada de colección reservada al podio y a participantes confirmados",
}
TIERS = {
    "profile": "Colección",
    "event": "Evento",
    "cheap": "Básico",
    "saving": "Ahorro",
    "exclusive": "Exclusivo",
    "limited": "Limitado",
}
CUSTOM_FIELDS = {
    "plate": ("Matrícula (ejemplo: CHINO-7)", 10),
    "signature": ("Frase para tu anuncio de podio", 100),
    "custom_color": ("Color hexadecimal, por ejemplo #44AAFF", 7),
    "nickname": ("Prefijo para tu apodo", 8),
    "bio": ("Frase para tu perfil", 100),
}


def banner_preview(product):
    if product["kind"] == "banner":
        art = json.loads(product["payload"]).get("art")
        if art in BANNERS:
            return (
                "https://raw.githubusercontent.com/bryanjoel07/Alertas-La-Venganza-RP/main/assets/banners/"
                + art
                + ".jpg"
            )
    return None


def product_text(p):
    data = json.loads(p["payload"])
    preview = data.get("label") or data.get("title") or ""
    if "color" in data:
        preview += f" · #{data['color']:06X}"
    stock = (
        "Disponibilidad ilimitada"
        if p["stock"] is None
        else f"{p['stock']} disponibles"
    )
    duration = "7 días desde la entrega" if p["duration"] else "Permanente"
    returns = (
        "Disponible solo durante esta campaña"
        if p["campaign_end"]
        else "Puede regresar en otra rotación"
    )
    if p["tier"] in ("profile", "event"):
        returns = (
            "Colección permanente"
            if p["tier"] == "profile"
            else "Personal · participación verificada"
        )
    if p["campaign_end"]:
        returns += f" · hasta <t:{p['campaign_end']}:d>"
    return f"{DETAILS[p['kind']]} · {preview.strip(' ·')}\n**{p['price']} 🪙** · {duration} · {stock}\n{returns}"


def shop_embed(r):
    embed = discord.Embed(
        title=PANEL,
        description=f"Próxima rotación <t:{r['ends']}:R> · lunes, 6:30 p. m. de Puerto Rico.\nLos recuerdos de tus eventos aparecen en **Comprar artículos** si tienes un podio o asistencia confirmada.",
        color=0xBE2335,
    )
    for p in r["products"]:
        if p["tier"] in ("profile", "event"):
            continue
        state = (
            ""
            if p["active"]
            and (not p["campaign_start"] or p["campaign_start"] <= time.time())
            and (not p["campaign_end"] or p["campaign_end"] > time.time())
            else " · Inactivo"
        )
        embed.add_field(
            name=f"{p['name']} · {TIERS[p['tier']]}{state}",
            value=product_text(p) + f"\n`{p['sku']}`",
            inline=False,
        )
    for tier, title in [
        ("profile", "Colección de perfil"),
        ("event", "Recuerdos de tus eventos"),
    ]:
        items = [p for p in r["products"] if p["tier"] == tier]
        if items:
            embed.add_field(
                name=title,
                value="\n".join(
                    f"{discord.utils.escape_markdown(p['name'])[:90]} · **{p['price']} 🪙**"
                    for p in items
                ),
                inline=False,
            )
    return embed


async def private(i, text, **kwargs):
    send = i.followup.send if i.response.is_done() else i.response.send_message
    await send(
        text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(), **kwargs
    )


async def private_list(i, title, lines):
    body = "\n".join(lines) or "Todavía no hay registros."
    if len(body) < 1750:
        await private(i, f"**{title}**\n{body}")
    else:
        await private(
            i,
            title,
            file=discord.File(io.BytesIO(body.encode()), filename="exclusive.txt"),
        )


class Confirm(discord.ui.View):
    def __init__(self, user, action, field=None):
        super().__init__(timeout=170)
        self.user = user
        self.action = action
        self.field = field

    async def interaction_check(self, i):
        if i.user.id != self.user:
            await private(i, "Solo quien abrió esta confirmación puede usarla.")
            return False
        return True

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.success)
    async def confirm(self, i, button):
        if self.field:
            label, limit = self.field
            modal = discord.ui.Modal(title="Personalizar y comprar")
            value = discord.ui.TextInput(label=label, max_length=limit)
            modal.add_item(value)

            async def submit(click):
                if await self.interaction_check(click):
                    await self.complete(click, value.value)

            modal.on_submit = submit
            await i.response.send_modal(modal)
            return
        await self.complete(i)

    async def complete(self, i, *args):
        await i.response.defer(ephemeral=True, thinking=True)
        try:
            result = await self.action(i, *args)
            self.stop()
        except (ValueError, discord.HTTPException) as exc:
            result = f"No se pudo completar la operación. {exc}"
        await private(i, result)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, i, button):
        self.stop()
        await i.response.edit_message(
            content="Operación cancelada.", embed=None, view=None
        )


class Panel(discord.ui.View):
    def __init__(self, system):
        super().__init__(timeout=None)
        self.system = system

    @discord.ui.button(
        label="Comprar artículos",
        emoji="🛍️",
        custom_id="lv:eco:shop",
        style=discord.ButtonStyle.primary,
    )
    async def shop(self, i, button):
        await self.system.shop(i)

    @discord.ui.button(label="Mi saldo", emoji="🪙", custom_id="lv:eco:balance")
    async def balance(self, i, button):
        await self.system.balance(i)

    @discord.ui.button(label="Probar cosméticos", emoji="👔", custom_id="lv:eco:try")
    async def fitting(self, i, button):
        await self.system.community.show_picker(i)

    @discord.ui.button(label="Retos y monedas", emoji="🏆", custom_id="lv:eco:challenges")
    async def challenges(self, i, button):
        await self.system.community.show_challenges(i)


class ShopPicker(discord.ui.Select):
    def __init__(self, system, products):
        super().__init__(
            placeholder="Elige un artículo para comprar",
            options=[
                discord.SelectOption(
                    label=p["name"],
                    value=p["sku"],
                    description=f"{p['price']} monedas · {TIERS[p['tier']]}",
                )
                for p in products
            ],
        )
        self.system = system

    async def callback(self, i):
        try:
            await self.system.preview(i, self.values[0], i.user)
        except (ValueError, discord.HTTPException) as exc:
            await private(i, str(exc))


class InventoryControls(discord.ui.View):
    def __init__(self, system, user, items):
        super().__init__(timeout=180)
        self.system = system
        self.user = user
        choices = [
            discord.SelectOption(label=p["name"][:100], value=p["id"])
            for p in items
            if p["status"] == "delivered" and p["kind"] != "voice"
        ][:25]
        if choices:
            picker = discord.ui.Select(
                placeholder="Equipar un artículo", options=choices
            )

            async def choose(i):
                purchase = system.store.purchase(picker.values[0], user)
                if purchase["kind"] in CUSTOM_FIELDS:
                    modal = discord.ui.Modal(title="Personalizar artículo")
                    label, limit = CUSTOM_FIELDS[purchase["kind"]]
                    value = discord.ui.TextInput(label=label, max_length=limit)
                    modal.add_item(value)

                    async def submit(click):
                        await self.equip(click, purchase["id"], value.value)

                    modal.on_submit = submit
                    await i.response.send_modal(modal)
                else:
                    await self.equip(i, purchase["id"], "")

            picker.callback = choose
            self.add_item(picker)

        active = [
            discord.SelectOption(label=LABELS[r["slot"]], value=r["slot"])
            for r in system.store.equipped(user)
        ]
        if active:
            remove = discord.ui.Select(
                placeholder="Quitar un cosmético", options=active
            )

            async def clear(i):
                await i.response.defer(ephemeral=True, thinking=True)
                async with system.delivery.lock:
                    system.store.unequip(user, remove.values[0])
                    await system.delivery.sync_member(i.user)
                await private(i, "Cosmético retirado.")

            remove.callback = clear
            self.add_item(remove)

    async def equip(self, i, key, value):
        if i.user.id != self.user:
            return await private(i, "Este inventario pertenece a otro jugador.")
        await i.response.defer(ephemeral=True, thinking=True)
        try:
            async with self.system.delivery.lock:
                self.system.delivery.equip(i.user, key, value)
                await self.system.delivery.sync_member(i.user)
        except (ValueError, discord.HTTPException) as exc:
            return await private(i, str(exc))
        await private(i, "Cosmético equipado.")

    async def interaction_check(self, i):
        if i.user.id != self.user:
            await private(i, "Este inventario pertenece a otro jugador.")
            return False
        return True

    async def on_error(self, i, error, item):
        await private(i, f"No se pudo actualizar el cosmético. {error}")


class Economy:
    def __init__(self, bot, path, guild):
        self.bot = bot
        self.guild = guild
        self.store = EconomyStore(path)
        self.delivery = Delivery(self.store)
        self.task = None
        self.ready = False
        self.last_error = ""
        self.signature = None
        self.player_commands = set()
        self.community = CommunityFeatures(self)
        self.admin = app_commands.Group(
            name="economia",
            description="Administración de la economía",
            default_permissions=discord.Permissions(administrator=True),
        )
        self.register()

    async def start(self):
        await asyncio.to_thread(self.store.initialize)
        await self.community.start()
        self.ready = True
        self.bot.add_view(Panel(self))
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.loop(), name="la-venganza-exclusive")

    def authorized(self, i):
        staff = self.store.config("admin_role")
        if i.guild_id != self.guild.id or not (
            i.user.guild_permissions.administrator
            or any(str(r.id) == staff for r in i.user.roles)
        ):
            raise ValueError("Se requiere un administrador de La Venganza RP.")

    async def loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            guild = self.bot.get_guild(self.guild.id)
            if guild:
                errors = []
                for job in (self.panel, self.audit, self.profiles, self.high_priorities, self.community.ensure_guide, self.delivery.recover):
                    try:
                        await job(guild)
                    except Exception as exc:
                        errors.append(f"{job.__name__}: {exc}")
                        log.exception("Economía: %s", job.__name__)
                self.last_error = " · ".join(errors)[:230]
            await asyncio.sleep(60)

    async def profiles(self, guild):
        await ensure_profiles(self, guild)

    async def high_priorities(self, guild):
        await fix_high_priorities(self.bot, guild.id)

    async def channel(self, guild, audit=False):
        category_id = self.store.config('audit_category') if audit else ''
        category = guild.get_channel(int(category_id)) if category_id else self.delivery.category(guild)
        if not isinstance(category,discord.CategoryChannel):
            raise ValueError('No encuentro la categoría configurada para este canal')
        key = "audit_channel" if audit else "shop_channel"
        name = "registro-exclusive" if audit else SHOP
        saved = self.store.config(key)
        channel = guild.get_channel(int(saved)) if saved else None
        marker = "La Venganza Exclusive · " + key
        if channel is None:
            available = await guild.fetch_channels()
            channel = next(
                (
                    c
                    for c in available
                    if isinstance(c, discord.TextChannel)
                    and c.category_id == category.id
                    and (
                        c.topic == marker
                        or (not audit and c.name in PREVIOUS_SHOP_NAMES | {SHOP})
                    )
                ),
                None,
            )
        if channel is None:
            kwargs = {}
            if audit:
                access = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    guild.me: discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, read_message_history=True
                    ),
                }
                for role in guild.roles:
                    if role.id in ROLES:
                        access[role] = discord.PermissionOverwrite(view_channel=True)
                kwargs["overwrites"] = access
            channel = await guild.create_text_channel(
                name, category=category, topic=marker, reason=PANEL, **kwargs
            )
        if not isinstance(channel, discord.TextChannel) or (
            not audit and channel.category_id != category.id
        ):
            raise ValueError(
                "El canal configurado no está en la categoría de la tienda."
            )
        if audit:
            self.check_private(channel)
        elif channel.name in PREVIOUS_SHOP_NAMES:
            channel = await channel.edit(
                name=SHOP,
                reason="Igualar el nombre de la tienda al estilo de La Venganza",
            )
        if saved != str(channel.id):
            self.store.runtime_config(key, channel.id)
            log.info(
                "Economía %s canal=%s categoría=%s",
                key,
                channel.id,
                channel.category_id,
            )
        return channel

    def check_private(self, ch):
        trusted = ROLES | {ch.guild.me.id}
        if ch.overwrites_for(ch.guild.default_role).view_channel is not False or any(
            perm.view_channel is True
            and target.id not in trusted
            and not (
                isinstance(target, discord.Role) and target.permissions.administrator
            )
            for target, perm in ch.overwrites.items()
        ):
            raise ValueError(
                "El registro debe ser privado y visible solo para Staff y el bot."
            )

    async def panel(self, guild):
        ch = await self.channel(guild)
        embed = shop_embed(self.store.rotation())
        mid = self.store.config("panel")
        signature = (ch.id, embed.to_dict())
        if self.signature == signature and mid:
            # A deleted panel is recovered by the raw message-delete listener.
            return
        msg = None
        if mid:
            try:
                msg = await ch.fetch_message(int(mid))
            except discord.NotFound:
                pass
        if msg is None:
            async for item in ch.history(limit=None):
                if (
                    item.author.id == guild.me.id
                    and item.embeds
                    and item.embeds[0].title == PANEL
                ):
                    msg = item
                    break
        if msg:
            await msg.edit(embed=embed, view=Panel(self))
        else:
            msg = await ch.send(embed=embed, view=Panel(self))
        self.store.runtime_config("panel", msg.id)
        self.signature = signature
        log.info(
            "Panel Exclusive listo canal=%s mensaje=%s categoría=%s nombre=%s",
            ch.id,
            msg.id,
            ch.category_id,
            ch.name,
        )

    async def audit(self, guild):
        ch = await self.channel(guild, True)
        for row in self.store.rows(
            "SELECT * FROM eco_audit WHERE sent=0 ORDER BY id LIMIT 20"
        ):
            await ch.send(
                f"Registro #{row['id']} · <t:{row['created']}:f> · ID {row['actor']}\n{row['action']}",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            self.store.rows("UPDATE eco_audit SET sent=1 WHERE id=?", (row["id"],))

    async def shop(self, i):
        if not i.response.is_done():
            await i.response.defer(ephemeral=True,thinking=True)
        rotation = await asyncio.to_thread(self.store.rotation,user=i.user.id)
        now = time.time()
        available = [
            p
            for p in rotation["products"]
            if p["active"]
            and p["stock"] != 0
            and (not p["campaign_start"] or p["campaign_start"] <= now)
            and (not p["campaign_end"] or now < p["campaign_end"])
        ]
        view = discord.ui.View(timeout=180)
        if available:
            view.add_item(ShopPicker(self, available))
        await private(
            i,
            "Elige un artículo para ver el precio y confirmar la compra."
            if available
            else "No quedan artículos disponibles en esta rotación.",
            embed=shop_embed(rotation),
            view=view if available else None,
        )

    async def balance(self, i):
        if not i.response.is_done():
            await i.response.defer(ephemeral=True,thinking=True)
        account = await asyncio.to_thread(self.store.account,i.user.id)
        text = f"Saldo: **{account['balance']} 🪙**"
        if account["goal"]:
            g = account["goal"]
            text += f"\nMeta: {g['name']} · faltan {max(0, g['price'] - account['balance'])} 🪙"
        await private(i, text)

    async def preview(self, i, sku, recipient):
        if recipient.bot:
            raise ValueError("Elige un jugador del servidor.")
        p = self.store.quote(i.user.id, recipient.id, sku)
        self.delivery.preflight(recipient, p["kind"])
        if self.store.account(i.user.id)["balance"] < p["price"]:
            raise ValueError(
                f"Necesitas {p['price']} monedas para comprar este artículo."
            )

        async def deliver(value=""):
            async with self.delivery.lock:
                member = await i.guild.fetch_member(recipient.id)
                self.delivery.preflight(member, p["kind"])
                receipt = self.store.buy(p["id"], i.user.id, value=value)
                if receipt["status"] in ("refunded", "expired"):
                    return "Esta compra ya terminó. Puedes consultar su historial en /movimientos."
                if receipt["kind"] == "voice" and receipt["status"] == "pending":
                    try:
                        await self.delivery.voice(i.guild, receipt)
                    except (ValueError, discord.HTTPException):
                        return f"Compra {receipt['id']} guardada. La sala está pendiente y se reintentará automáticamente."
                if receipt["kind"] == "voice":
                    room = self.store.purchase(receipt["id"])["resource_id"]
                    return f"Compra confirmada · {receipt['price']} 🪙. Tu sala está lista: <#{room}>."
                if self.store.rows(
                    "SELECT 1 FROM eco_sync WHERE user_id=?", (member.id,)
                ):
                    try:
                        await self.delivery.sync_member(member)
                    except (ValueError, discord.HTTPException):
                        return f"Compra guardada en /inventario. La entrega de {receipt['name']} está pendiente. El bot volverá a intentarlo sin cobrarte otra vez."
            return f"Compra confirmada: {receipt['name']} · {receipt['price']} 🪙. Puedes ver el artículo en /inventario y cambiarlo cuando quieras."

        field = CUSTOM_FIELDS.get(p["kind"])
        preview = {}
        art = banner_preview(p)
        if art:
            preview["embed"] = discord.Embed(title=p["name"]).set_image(url=art)
        note = (
            "Al confirmar, el bot creará la sala."
            if p["kind"] == "voice"
            else "Al confirmar, se equipará automáticamente y sustituirá el cosmético activo del mismo tipo."
        )
        if field:
            note += " Se pedirá la personalización antes de cobrar."

        async def buy(click, value=""):
            if recipient.id == i.user.id:
                return await deliver(value)

            async def accept(_, value=""):
                return await deliver(value)

            await recipient.send(
                f"{i.user.display_name} quiere regalarte **{p['name']}**. Pagará {p['price']} 🪙 al aceptar.\n{product_text(p)}\n{note}",
                view=Confirm(recipient.id, accept, field),
                allowed_mentions=discord.AllowedMentions.none(),
                **preview,
            )
            return "Se envió la invitación privada. El cobro se aplicará cuando el destinatario acepte antes del vencimiento."

        await private(
            i,
            f"**{p['name']}** para **{discord.utils.escape_markdown(recipient.display_name)}**\n{product_text(p)}\n{note}\nConfirma antes de <t:{p['expires']}:T>.",
            view=Confirm(i.user.id, buy, field if recipient.id == i.user.id else None),
            **preview,
        )

    def diagnostics(self):
        if not self.ready:
            return "Inicialización pendiente"
        r = self.store.rotation()
        n = self.store.rows(
            "SELECT (SELECT count(*) FROM eco_purchases WHERE status='pending')+(SELECT count(*) FROM eco_sync) AS n"
        )[0]["n"]
        return (
            f"Rotación {r['week']} · Próxima <t:{r['ends']}:R> · Entregas pendientes: {n}\n"
            + (self.last_error or "Operativa")
        )

    def register(self):
        def player(name, description):
            self.player_commands.add(name)
            return self.bot.tree.command(
                name=name, description=description, guild=self.guild
            )

        def admin(name, description):
            return self.admin.command(name=name, description=description)

        self.community.register(player)

        @player("saldo", "Ver tu saldo y meta de ahorro")
        async def balance(i: discord.Interaction):
            await self.balance(i)

        @player("tienda", "Ver artículos y precios de la semana")
        async def shop(i: discord.Interaction):
            await self.shop(i)

        @player("comprar", "Revisar y confirmar un artículo")
        async def buy(i: discord.Interaction, producto: str):
            await self.preview(i, producto, i.user)

        @player("regalar", "Revisar y comprar un regalo para otro jugador")
        async def gift(
            i: discord.Interaction, producto: str, destinatario: discord.Member
        ):
            await self.preview(i, producto, destinatario)

        @player(
            "inventario", "Artículos, fechas, ediciones y controles de personalización"
        )
        async def inventory(i: discord.Interaction):
            items = self.store.inventory(i.user.id)
            equipped = {r["purchase_id"] for r in self.store.equipped(i.user.id)}
            lines = []
            for p in items:
                state = {
                    "pending": "pendiente",
                    "delivered": "entregado",
                    "expired": "vencido",
                }.get(p["status"], p["status"])
                end = f" · vence <t:{p['expires']}:f>" if p["expires"] else ""
                edition = (
                    f" · edición #{p['edition']}" if p["kind"] == "limited" else ""
                )
                lines.append(
                    f"{p['name']}{edition} · <t:{p['created']}:d>{end} · {state}"
                    + (" · equipado" if p["id"] in equipped else "")
                    + f"\n`{p['id']}`"
                )
            controls = InventoryControls(self, i.user.id, items)
            body = "\n".join(lines) or "Todavía no tienes compras."
            if len(body) > 1750:
                await private(
                    i,
                    "Inventario completo · /equipar y /quitar",
                    file=discord.File(
                        io.BytesIO(body.encode()), filename="inventario.txt"
                    ),
                    view=controls,
                )
            else:
                await private(i, "**Inventario**\n" + body, view=controls)

        @player("equipar", "Equipar una compra o personalizar su valor")
        async def equip(i: discord.Interaction, compra: str, valor: str = ""):
            await i.response.defer(ephemeral=True, thinking=True)
            async with self.delivery.lock:
                self.delivery.equip(i.user, compra, valor)
                await self.delivery.sync_member(i.user)
            await private(i, "Cosmético equipado.")

        @player("quitar", "Retirar un cosmético de tu perfil")
        async def remove(
            i: discord.Interaction,
            espacio: Literal[
                "insignia",
                "titulo",
                "tema",
                "color",
                "prefijo",
                "frase",
                "victoria",
                "trofeo",
                "banner",
                "matricula",
                "firma",
                "vitrina",
                "recuerdo",
            ],
        ):
            await i.response.defer(ephemeral=True, thinking=True)
            if espacio == "trofeo":
                self.store.runtime_config(f"trofeo:{i.user.id}", "")
            else:
                async with self.delivery.lock:
                    self.store.unequip(i.user.id, espacio)
                    await self.delivery.sync_member(i.user)
            await private(i, "Selección retirada.")

        @player("trofeo", "Destacar en tu perfil un podio que ganaste")
        async def trophy(
            i: discord.Interaction,
            evento: int,
            espacio: app_commands.Range[int, 1, 3] = None,
        ):
            if espacio is not None:
                self.store.pin_trophy(i.user.id, espacio, evento)
                await private(
                    i, f"Evento #{evento} en el espacio {espacio} de tu vitrina."
                )
                return
            winners = self.store.rows(
                "SELECT winner1,winner2,winner3 FROM events WHERE id=?", (evento,)
            )
            if not winners or str(i.user.id) not in winners[0].values():
                raise ValueError(
                    "Solo puedes destacar un evento en el que ganaste un puesto."
                )
            self.store.runtime_config(f"trofeo:{i.user.id}", evento)
            await private(i, f"Trofeo del evento #{evento} destacado.")

        @player("movimientos", "Historial privado de monedas, compras y ajustes")
        async def ledger(
            i: discord.Interaction, pagina: app_commands.Range[int, 1, 1000000] = 1
        ):
            rows = self.store.rows(
                "SELECT * FROM eco_ledger WHERE user_id=? ORDER BY id DESC LIMIT 20 OFFSET ?",
                (i.user.id, (pagina - 1) * 20),
            )
            await private_list(
                i,
                f"Movimientos · página {pagina}",
                [
                    f"<t:{r['created']}:d> {r['amount']:+} 🪙 · {r['reason']} · {r['op']}"
                    for r in rows
                ],
            )

        @player("deseos", "Ver o editar tu lista de deseos y tu meta de ahorro")
        async def wishes(
            i: discord.Interaction,
            accion: Literal["ver", "agregar", "quitar", "meta"],
            producto: str = "",
        ):
            if accion in ("agregar", "quitar") and not producto:
                raise ValueError("Indica el código de producto.")
            values = self.store.preferences(i.user.id, producto, accion)
            await private_list(
                i, "Lista de deseos · usa /saldo para ver tu meta", values
            )

        @player("sala", "Cambiar nombre o administrar invitados de tu sala temporal")
        async def room(
            i: discord.Interaction,
            accion: Literal["nombre", "invitar", "retirar"],
            jugador: discord.Member = None,
            nombre: str = "",
        ):
            await i.response.defer(ephemeral=True, thinking=True)
            async with self.delivery.lock:
                rooms = self.store.rows(
                    "SELECT * FROM eco_purchases WHERE recipient=? AND kind='voice' AND status='delivered' AND expires>? ORDER BY created DESC",
                    (i.user.id, int(time.time())),
                )
                if len(rooms) != 1:
                    raise ValueError("Necesitas una sala activa.")
                ch = i.guild.get_channel(rooms[0]["resource_id"])
                if not isinstance(ch, discord.VoiceChannel):
                    raise ValueError("No se encontró tu sala.")
                if accion == "nombre":
                    await ch.edit(name=clean_label(nombre, 65))
                elif (
                    jugador is None
                    or jugador.bot
                    or jugador.id == i.user.id
                    or any(r.id in ROLES for r in jugador.roles)
                ):
                    raise ValueError(
                        "Elige un invitado distinto del propietario, Staff o el bot."
                    )
                else:
                    perms = (
                        discord.PermissionOverwrite(
                            view_channel=True, connect=True, speak=True
                        )
                        if accion == "invitar"
                        else None
                    )
                    await ch.set_permissions(
                        jugador, overwrite=perms, reason="Invitados de sala Exclusive"
                    )
            await private(i, f"Sala actualizada. Vence <t:{rooms[0]['expires']}:f>.")

        @admin("asistencia", "Confirmar o retirar la participación real de un jugador")
        async def attend(
            i: discord.Interaction,
            evento: int,
            jugador: discord.Member,
            presente: bool = True,
        ):
            self.authorized(i)
            if jugador.bot:
                raise ValueError("Elige un jugador.")
            self.store.participant(evento, jugador.id, presente, i.user.id)
            await private(
                i,
                "Participación registrada y premios del evento actualizados cuando corresponde.",
            )

        @admin("corregir", "Revisar y confirmar los ajustes por corrección de podio")
        async def correct(
            i: discord.Interaction,
            evento: int,
            primero: discord.Member,
            segundo: discord.Member,
            tercero: discord.Member,
        ):
            self.authorized(i)
            winners = [m.id for m in (primero, segundo, tercero)]
            expected = self.store.correct(evento, winners, i.user.id)

            async def apply(click):
                self.authorized(click)
                self.store.correct(evento, winners, click.user.id, expected)
                return "Resultados y diferencias aplicados."

            lines = [f"<@{user}> {n:+} 🪙" for user, n in expected[1].items()]
            await private(
                i,
                f"Evento #{evento} · podio propuesto: {primero.mention}, {segundo.mention}, {tercero.mention}\n"
                + ("\n".join(lines) or "Sin cambios de saldo."),
                view=Confirm(i.user.id, apply),
            )

        @admin("premios", "Configurar las monedas para nuevos resultados")
        async def rates(
            i: discord.Interaction,
            primero: int,
            segundo: int,
            tercero: int,
            participante: int,
        ):
            self.authorized(i)
            values = [primero, segundo, tercero, participante]
            if not all(0 <= v <= 1000000 for v in values):
                raise ValueError("Usa cantidades entre 0 y 1.000.000.")
            self.store.config(
                "rewards",
                json.dumps(
                    dict(zip(("first", "second", "third", "participant"), values))
                ),
                i.user.id,
            )
            await private(i, "Recompensas actualizadas para los próximos eventos.")

        @admin("ajustar", "Ajustar el saldo de un jugador con motivo")
        async def adjust(
            i: discord.Interaction, jugador: discord.Member, cantidad: int, motivo: str
        ):
            self.authorized(i)
            self.store.adjust(jugador.id, cantidad, motivo, i.user.id, str(i.id))
            await private(i, "Ajuste registrado.")

        @admin("devolver", "Devolver una compra al pagador y retirar el artículo")
        async def refund(i: discord.Interaction, compra: str, motivo: str):
            self.authorized(i)
            async with self.delivery.lock:
                self.store.refund(compra, i.user.id, motivo)
            await private(
                i,
                "Devolución registrada. Se retirarán los recursos de Discord correspondientes.",
            )

        @admin("catalogo", "Ver códigos, precios y estado del catálogo")
        async def catalog(i: discord.Interaction):
            self.authorized(i)
            await private_list(
                i,
                "Catálogo",
                [
                    f"{p['sku']} · {p['name']} · {p['price']} 🪙 · {'activo' if p['active'] else 'inactivo'}"
                    for p in self.store.products()
                ],
            )

        @admin("producto", "Crear o actualizar una ficha del catálogo")
        async def product(
            i: discord.Interaction,
            codigo: str,
            nombre: str,
            tipo: Literal[
                "badge",
                "limited",
                "color",
                "title",
                "bio",
                "theme",
                "nickname",
                "custom_color",
                "bundle",
                "celebration",
                "voice",
            ],
            categoria: Literal["cheap", "saving", "exclusive", "limited"],
            precio: int,
            activo: bool = True,
            existencias: int = None,
            color: str = "D60000",
            fin_campana: str = "",
            inicio_campana: str = "",
            etiqueta: str = "",
        ):
            self.authorized(i)
            try:
                tint = int(color.lstrip("#"), 16)
                if not 0 <= tint <= 0xFFFFFF:
                    raise ValueError
                start = (
                    int(
                        datetime.strptime(inicio_campana, "%Y-%m-%d")
                        .replace(tzinfo=PR)
                        .timestamp()
                    )
                    if inicio_campana
                    else None
                )
                end = (
                    int(
                        datetime.strptime(fin_campana, "%Y-%m-%d")
                        .replace(tzinfo=PR)
                        .timestamp()
                    )
                    if fin_campana
                    else None
                )
            except ValueError:
                raise ValueError("Usa un color hexadecimal y una fecha AAAA-MM-DD.")
            label = clean_label(etiqueta or nombre, 65)
            self.store.save_product(
                i.user.id,
                codigo,
                clean_label(nombre, 70),
                tipo,
                categoria,
                precio,
                existencias,
                604800 if tipo == "voice" else 0,
                activo,
                dict(color=tint, label=label, title=label),
                end,
                start,
            )
            await private(
                i, "Ficha guardada. Los inventarios y precios ya pagados se conservan."
            )

        @admin("rotacion", "Programar los productos de un lunes futuro")
        async def schedule(i: discord.Interaction, lunes: str, codigos: str):
            self.authorized(i)
            self.store.schedule(
                i.user.id, lunes, [s.strip() for s in codigos.split(",")]
            )
            await private(i, "Rotación programada.")

        @admin(
            "coleccion", "Ajustar precio y disponibilidad de un artículo de colección"
        )
        async def collection(
            i: discord.Interaction, codigo: str, precio: int, activo: bool = True
        ):
            self.authorized(i)
            self.store.collection_price(codigo, precio, activo, i.user.id)
            await private(i, "Artículo de colección actualizado.")

        @admin("destinos", "Configurar categoría de tienda, salas o registro privado")
        async def destinations(
            i: discord.Interaction,
            tienda: discord.CategoryChannel = None,
            voz: discord.CategoryChannel = None,
            registro: discord.TextChannel = None,
            administrador: discord.Role = None,
        ):
            if (
                i.guild_id != self.guild.id
                or not i.user.guild_permissions.administrator
            ):
                raise ValueError(
                    "Solo un administrador del servidor puede cambiar permisos o canales."
                )
            if administrador:
                if administrador.is_default() or administrador.managed:
                    raise ValueError("Elige un rol de Staff.")
                self.store.config("admin_role", administrador.id, i.user.id)
            if registro:
                self.check_private(registro)
                self.store.config("audit_channel", registro.id, i.user.id)
            if tienda:
                self.store.config("category", tienda.id, i.user.id)
                self.store.runtime_config("shop_channel", "")
                self.store.runtime_config("panel", "")
                self.signature = None
            if voz:
                self.store.config("voice_category", voz.id, i.user.id)
            await private(i, "Configuración guardada.")

        @admin("registro", "Consultar movimientos administrativos recientes")
        async def audit(
            i: discord.Interaction, pagina: app_commands.Range[int, 1, 1000000] = 1
        ):
            self.authorized(i)
            rows = self.store.rows(
                "SELECT * FROM eco_audit ORDER BY id DESC LIMIT 20 OFFSET ?",
                ((pagina - 1) * 20,),
            )
            await private_list(
                i,
                "Registro de economía",
                [f"#{r['id']} · {r['actor']} · {r['action']}" for r in rows],
            )

        @admin("pendientes", "Revisar y reintentar entregas guardadas")
        async def pending(i: discord.Interaction):
            self.authorized(i)
            await i.response.defer(ephemeral=True, thinking=True)
            await self.delivery.recover(i.guild)
            rows = self.store.rows(
                "SELECT id,name FROM eco_purchases WHERE status='pending'"
            )
            await private_list(
                i,
                "Entregas pendientes",
                [r["id"] + " · " + r["name"] for r in rows]
                + [
                    str(r["user_id"]) + " · equipamiento"
                    for r in self.store.rows("SELECT * FROM eco_sync")
                ],
            )

        async def products(i, current):
            items = (
                self.store.rotation(
                    user=i.user.id if i.command.name == "comprar" else None
                )["products"]
                if i.command.name in ("comprar", "regalar")
                else self.store.products()
            )
            return [
                app_commands.Choice(
                    name=f"{p['name']} · {p['price']} 🪙"[:100], value=p["sku"]
                )
                for p in items
                if current.casefold() in (p["name"] + " " + p["sku"]).casefold()
            ][:25]

        for command in (buy, gift, wishes):
            command.autocomplete("producto")(products)

        @equip.autocomplete("compra")
        async def owned(i, current):
            return [
                app_commands.Choice(name=p["name"], value=p["id"])
                for p in self.store.inventory(i.user.id)
                if p["status"] == "delivered"
                and current.casefold() in p["name"].casefold()
            ][:25]

        self.bot.tree.add_command(self.admin, guild=self.guild)

    def decorate(self, embed, user):
        if not self.ready:
            return
        for item in self.store.equipped(user):
            slot = item["slot"]
            value = discord.utils.escape_markdown(item["value"])[:150]
            if slot == "tema":
                embed.color = discord.Color(json.loads(item["payload"])["color"])
            elif slot == "banner":
                art = banner_preview(item)
                if art:
                    embed.set_image(url=art)
            elif slot == "matricula":
                value = f"`{item['value']}`"
            elif slot == "vitrina":
                lines = []
                for pos, event in enumerate(
                    self.store.showcase(user, item["purchase_id"]), 1
                ):
                    if event:
                        rank = next(
                            i
                            for i in range(1, 4)
                            if str(event[f"winner{i}"]) == str(user)
                        )
                        stamp = int(
                            datetime.fromisoformat(event["starts_at"]).timestamp()
                        )
                        lines.append(
                            f"{pos}. {('🥇', '🥈', '🥉')[rank - 1]} {discord.utils.escape_markdown(event['title'])[:90]} · <t:{stamp}:d>"
                        )
                value = "\n".join(lines) or "Tus próximos podios aparecerán aquí."
            elif slot == "recuerdo":
                stamp = int(
                    datetime.fromisoformat(
                        json.loads(item["payload"])["date"]
                    ).timestamp()
                )
                value += f" · <t:{stamp}:d>"
            embed.add_field(
                name=LABELS[slot],
                value=value,
                inline=slot != "vitrina",
            )
        trophy = self.store.config(f"trofeo:{user}")
        if trophy:
            rows = self.store.rows(
                "SELECT title,winner1,winner2,winner3 FROM events WHERE id=?", (trophy,)
            )
            if rows:
                for pos, k in enumerate(("winner1", "winner2", "winner3"), 1):
                    if rows[0][k] == str(user):
                        embed.add_field(
                            name="Trofeo destacado",
                            value=f"{pos}.º · {rows[0]['title']}"[:150],
                        )
                        break

        account = self.store.account(user)
        embed.add_field(name="🪙 Saldo Exclusive", value=f"**{account['balance']:,} 🪙**", inline=True)
        if account['goal']:
            goal = account['goal']
            embed.add_field(name="🎯 Meta de ahorro", value=f"{discord.utils.escape_markdown(goal['name'])}\nFaltan **{max(0, goal['price'] - account['balance']):,} 🪙**", inline=True)

    def victory(self, embed, user):
        if self.ready:
            for item in self.store.equipped(user):
                if item["slot"] == "victoria":
                    embed.color = discord.Color(json.loads(item["payload"])["color"])
                    embed.add_field(name="Celebración del ganador", value=item["value"])

    def podium_signature(self, user):
        if self.ready:
            for item in self.store.equipped(user):
                if item["slot"] == "firma":
                    return "\n“" + discord.utils.escape_markdown(item["value"]) + "”"
        return ""
