"""Filtro nativo de Discord para lenguaje obsceno en La Venganza RP."""
import logging

import discord
from discord.ext import tasks

NAME = "La Venganza RP · Lenguaje obsceno"
NOTICE = "Este mensaje contiene lenguaje bloqueado en La Venganza RP. Reformúlalo para enviarlo."
# Keywords without wildcards match whole words. Short abbreviations are intentional.
WORDS = sorted(set("""
cb hdpt hp wlb mmb hdp hijueputa hijueputas jueputa jueputas hijoputa hijoputas hijadeputa
hijoeputa hijoesuputa malparido malparida malparidos malparidas carechimba carechimbas caremonda
gonorrea gonorreas pirobo piroba pirobos pirobas careverga carevergas carepicha carepichas
cabrón cabron cabrones cabrona cabronas cabronazo cabronazos cabronada cabronadas
puñeta puñetas puneta punetas coñazo coñazos coño coños coñomadre coñemadre coñetumadre
mamabicho mamabichos mamagüevo mamagüevos mamaguevo mamaguevos mamahuevo mamahuevos
mamaguebo mamagüebo mamaguebos mamagüebos mamaverga mamavergas mamapinga mamapingas
huelebicho huelebichos güelebicho güelebichos welebicho welebichos wuelebicho wuelebichos
lambecrica lambecricas lambebicho lambebichos lambeguevo lambegüebo lambeverga
comemierda comemierdas comeminga comemingas comepinga comepingas
chupapija chupapijas chupaverga chupavergas chupapinga chupapingas chupapico chupapicos
puta putas puto putos putazo putazos putería puteria putear puteada puteadas
mierda mierdas carajo carajos culo culos culero culera culeros culeras
pendejo pendeja pendejos pendejas pendejada pendejadas
chingar chingada chingadas chingado chingados chingadera chingaderas chingón chingon chingona
chingatumadre chtm vetealaverga alv vergazo vergazos verga vergas vergajo vergajos
pinche pinches culiao culiaos culiá culiás culiaos culeado culeada culiado culiada
conchetumare conchesumare conchetumadre conchesumadre ctm reconchetumare
pelotudo pelotuda pelotudos pelotudas boludo boluda boludos boludas putamadre
güevón huevón huevon huevona huevones huevonas huevada huevadas
singao singaos singada singadas singazón singazon pingazo pingazos pinga pingas
""".split()) | {
    "hijo de puta","hija de puta","hijos de puta","hijas de puta","hijo de la gran puta",
    "hijo de tu puta madre","la puta madre","puta madre","chingas a tu madre","chinga tu madre",
    "vete a la verga","vete al carajo","la concha de tu madre","la concha de tu hermana",
    "coño de tu madre","coño de la madre","coño de su madre","mama bicho","huele bicho",
    "mama el bicho","mama la verga","chupa la verga","chupa el pico",
})

# Compact patterns fit Discord's Rust regex limits and keep word boundaries.
PATTERNS = [
    r"(?i)\b(?:c[._-]?b|h[._-]?p|h[._-]?d[._-]?p(?:[._-]?t)?|w[._-]?l[._-]?b|m[._-]?m[._-]?b)\b",
    r"(?i)\bc+[\W_]*[aá4@]+[\W_]*b+[\W_]*r+[\W_]*[oó0]+[\W_]*n+(?:[ae]s?|s)?\b",
    r"(?i)\bp+[\W_]*[uú]+[\W_]*[ñn]+[\W_]*[eé3]+[\W_]*t+[\W_]*[aá4@]+s?\b",
    r"(?i)\b(?:m+[\W_]*[aá4@]+[\W_]*m+[\W_]*[aá4@]+|(?:[hg]?[uü]|wu?)[eé3]+l+[eé3]+)[\W_]*b+[\W_]*[ií1!]+[\W_]*c+[\W_]*h+[\W_]*[oó0]+s?\b",
    r"(?i)\bh[ií1]j[oa0]s?[\W_]*(?:(?:de|d)[\W_]*(?:(?:la[\W_]+)?gran[\W_]+)?)?p+[\W_]*[uú]+[\W_]*t+[\W_]*[aá4@]+s?\b",
    r"(?i)\bp+[\W_]*[uú]+[\W_]*t+[\W_]*[aoáó04@]+s?\b",
    r"(?i)\b(?:m[ií1][eé3]rd[aá4@]s?|c[oó0]ñ[oó0]s?|v[eé3]rg[aá4@]s?|p[eé3]nd[eé3]j[oa04]s?)\b",
    r"(?i)\b(?:mama|chupa|lambe)[\W_]*(?:g[uü]e[bv]o|huevo|verga|pinga|pija|crica)s?\b",
]


class ObscenityFilter:
    def __init__(self, client, guild_id, get_setting, set_setting):
        self.client, self.guild_id = client, guild_id
        self.get_setting, self.set_setting = get_setting, set_setting
        self.last_status = None

    def status(self, message):
        if self.last_status != message:
            logging.getLogger(__name__).info("AutoMod: %s", message)
            self.last_status = message

    @tasks.loop(minutes=2)
    async def install(self):
        guild = self.client.get_guild(self.guild_id)
        if guild is None or guild.me is None or not guild.me.guild_permissions.manage_guild:
            self.status("pendiente de Gestionar servidor")
            return
        try:
            existing = await guild.fetch_automod_rules()
            saved = self.get_setting("obscenity_rule_id")
            if saved:
                self.status("regla activa" if any(str(r.id)==saved and r.enabled for r in existing)
                            else "regla retirada o desactivada en Discord")
                self.install.stop()
                return
            rule = next((r for r in existing if r.name == NAME),None)
            if rule and rule.creator_id != self.client.user.id:
                self.status("nombre ocupado por otra regla; se conserva")
                return
            if rule is None:
                rule = await guild.create_automod_rule(name=NAME,event_type=discord.AutoModRuleEventType.message_send,
                    trigger=discord.AutoModTrigger(keyword_filter=WORDS,regex_patterns=PATTERNS),
                    actions=[discord.AutoModRuleAction(custom_message=NOTICE)],enabled=True,
                    reason="Filtro acordado de palabras obscenas para La Venganza RP")
            self.set_setting("obscenity_rule_id",str(rule.id))
            self.status("regla activa" if rule.enabled else "regla desactivada en Discord")
            self.install.stop()
        except discord.HTTPException as exc:
            self.status(f"Discord HTTP {exc.status}, código {exc.code}: {exc.text[:300]}")

    @install.before_loop
    async def before(self):
        await self.client.wait_until_ready()
