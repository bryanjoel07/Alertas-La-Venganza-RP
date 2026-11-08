"""Filtro nativo de Discord para lenguaje obsceno en La Venganza RP."""
import logging

import discord
from discord.ext import tasks

NAME = "La Venganza RP · Lenguaje obsceno"
NOTICE = "Este mensaje contiene lenguaje bloqueado en La Venganza RP. Reformúlalo para enviarlo."
# Palabras que ya constituyen un insulto, incluidas grafías regionales y evasiones.
REGIONAL_INSULTS = """
hijueperra hijueperras triplehijueputa triplehijueputas triplehp hpta hptas hdpta hdptas
mmg mmgb mmgv mmbicho mmbichos wlbicho wlbichos mamabichazo mamabichazos
mamabichón mamabichon mamabichones mamabishos mamabisho mamabishas mamabisha
huelebishos huelebisho güelebichos guelebicho guelebichos
lambehuevo lambehuevos lambegüevo lambegüevos lambeguevos mamagüebo mamagüebos
mamawebo mamawebos mamawevo mamawevos mamahuevazo mamahuevazos
mamapichas mamapicha mamapichos chupapolla chupapollas chupapichas chupapicha
comebicho comebichos comecrica comecricas lambepinga lambepingas lambepijas
tragabicho tragabichos tragasemen tragaleche tragasables
malcogido malcogida malcogidos malcogidas malfollado malfollada malfollados malfolladas
malculeado malculeada malculeados malculeadas recontraputa recontraputo
recontraputas recontraputos recontraputísima recontraputisima reputísima reputisima
putarraca putarracas putarraco putarracos putifero putífero putífera putifera
putipuerco putipuerca putiputa putiputas putorra putorras putón putones putona putonas
putísima putisima putísimo putisimo putísimas putisimas putísimos putisimos
putañero putañeros putañera putañeras
culeacabras culeaburras singamadre singamadres singatúmadre singatumadre
chuchatumadre chuchasumadre reculiao reculiaos reqliao reqliaos qliao qliaos qliá
reconchasumadre conchadetumadre conchasumare conchesumare csmr rctm
maricón maricon maricones mariconazo mariconazos mariconada mariconadas
pajeruelo pajeruela pajillero pajillera soplaverga soplavergas
""".split()

# Términos ambiguos como «perra» o «zorra» únicamente en expresiones dirigidas.
DIRECTED_PHRASES = {
    f"{prefix} {insult}"
    for prefix in ("eres una", "sos una", "pareces una", "pedazo de")
    for insult in ("perra en celo", "puta barata", "puta de mierda", "zorra barata",
                   "zorra de mierda", "perra de mierda", "ramera", "perra sarnosa")
}
DIRECTED_PHRASES.update("""
mi puta personal
mi perra sexual
mi esclava sexual
mi esclavo sexual
solo sirves para coger
sólo sirves para coger
solo sirves para que te cojan
solo sirves para que te follen
solo sirves para chupar
solo sirves para abrir las piernas
solo sirves pa abrir las piernas
solo sirves para mamar
solo sirves para dar el culo
abre las piernas puta
abre las piernas perra
perra de todos
puta de todos
zorra de todos
perra de alquiler
perra barata
perra asquerosa
zorra inmunda
zorra asquerosa
zorra culera
hijo de la chingada
hija de la chingada
hijo de la chucha
la concha de tu vieja
la reconcha de tu madre
la recalcada concha de tu madre
andate a la concha de tu madre
que te den por el culo
que te la metan por el culo
vete a chupar pija
andá a chupar pija
anda a chupar pico
vete a mamar bicho
te voy a violar
te vamos a violar
voy a violarte
vamos a violarte
te voy a follar a la fuerza
te voy a coger a la fuerza
te cojo aunque no quieras
te follo aunque no quieras
te voy a dar por el culo
trágate mi semen
tragate mi semen
trágate mi leche
tragate mi leche
muéstrame las tetas puta
muestrame las tetas puta
enseña las tetas puta
""".strip().splitlines())
for verb in ("chúpame", "chupame", "chúpate", "chupate", "mámame", "mamame", "mámate", "mamate"):
    DIRECTED_PHRASES.update(f"{verb} {obj}" for obj in
        ("el bicho","el pene","el pico","el güevo","el huevo","la verga","la pinga","la pija","el pito"))
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
} | set(REGIONAL_INSULTS) | DIRECTED_PHRASES)

# Compact patterns fit Discord's Rust regex limits and keep word boundaries.
PATTERNS = [
    r"(?i)\b(?:c[._-]?b|h[._-]?p|h[._-]?d[._-]?p(?:[._-]?t)?|w[._-]?l[._-]?b|m[._-]?m[._-]?b)\b",
    r"(?i)\bc+[ ._*/-]*[aá4@]+[ ._*/-]*b+[ ._*/-]*r+[ ._*/-]*[oó0]+[ ._*/-]*n+(?:[ae]s?|s)?\b",
    r"(?i)\bp+[ ._*/-]*[uú]+[ ._*/-]*[ñn]+[ ._*/-]*[eé3]+[ ._*/-]*t+[ ._*/-]*[aá4@]+s?\b",
    r"(?i)\b(?:m+[ ._*/-]*[aá4@]+[ ._*/-]*m+[ ._*/-]*[aá4@]+|(?:[hg]?[uü]|wu?)[eé3]+l+[eé3]+)[ ._*/-]*b+[ ._*/-]*[ií1!]+[ ._*/-]*c+[ ._*/-]*h+[ ._*/-]*[oó0]+s?\b",
    r"(?i)\bh[ií1]j[oa0]s?[ ._*/-]*(?:de?[ ._*/-]*)?(?:la[ ._*/-]+)?(?:gran[ ._*/-]+)?p+[ ._*/-]*[uú]+[ ._*/-]*t+[ ._*/-]*[aá4@]+s?\b",
    r"(?i)\bp+[ ._*/-]*[uú]+[ ._*/-]*t+[ ._*/-]*[aoáó04@]+s?\b",
    r"(?i)\b(?:m[ií1][eé3]rd[aá4@]s?|c[oó0]ñ[oó0]s?|v[eé3]rg[aá4@]s?|p[eé3]nd[eé3]j[oa04]s?)\b",
    r"(?i)\b(?:mama|chupa|lambe)[ ._*/-]*(?:g[uü]e[bv]o|huevo|verga|pinga|pija|crica)s?\b",
    r"(?i)\b(?:eres|sos|pareces)[ ._-]+(?:una?[ ._-]+)?(?:p[e3]rr[a4]|z[o0]rr[a4]|ram[e3]r[a4])\b",
    r"(?i)\b(?:te[ ._-]+(?:voy|vamos)[ ._-]+a[ ._-]+v[i1][o0]l[a4]r|(?:voy|vamos)[ ._-]+a[ ._-]+v[i1][o0]l[a4]rte)\b",
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
