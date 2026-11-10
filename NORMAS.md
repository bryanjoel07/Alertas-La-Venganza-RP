# Buscador de normas

`/regla tema` busca en el canal oficial indicado por el dueño: `1528925322362228787` (Info-Servidor). La respuesta es privada y ofrece un enlace al mensaje original. Ejemplos: `/regla ck`, `/regla pk`, `/regla pkt`, `/regla secuestros`, `/regla vehículos`, `/regla zonas seguras`.

La fuente comprobada contiene ocho apartados, publicados en los mensajes `1567278823324782854` y `1567278835332812821`. CK se menciona en Muerte y heridas; PK se menciona ahí y en Enfrentamientos. El canal no contiene una definición detallada de CK. Para las búsquedas del canal, el bot devuelve los apartados tal como están publicados. Por solicitud expresa posterior del propietario, CK y PKT tienen las explicaciones adicionales descritas abajo, diferenciadas de las citas del canal.

## Búsquedas y resultados

- Lee texto y embeds del canal y separa los apartados por sus encabezados, conservando sus condiciones completas.
- Reconoce abreviaturas y algunas variantes de búsqueda; normaliza acentos, puntuación y letras decorativas. Las abreviaturas se buscan como palabras completas para no confundir PK con PKT ni encontrar coincidencias dentro de otras palabras.
- Las coincidencias en el título tienen prioridad. Si hay varios resultados, se muestran con Anterior y Siguiente; cada uno enlaza a su propio mensaje original. Un resultado único solo muestra el botón del enlace.
- Los apartados largos se dividen en partes navegables sin eliminar sus últimas condiciones. La respuesta no es un resumen generado.
- El autocompletado ofrece temas y títulos que aparecen en la fuente, además de las explicaciones CK y PKT aprobadas por el propietario. Si no hay coincidencia, lo indica y ofrece abrir el canal.

## Acceso y actualización

Solo se usa dentro del servidor y por miembros que puedan ver el canal de normas y leer su historial. Cada navegación comprueba otra vez el acceso. Los controles privados pertenecen a quien hizo la búsqueda; no se menciona a todos ni se publica la consulta en el chat.

El índice se guarda en memoria, se reconstruye al reiniciar y se refresca cada cinco minutos. Los eventos de creación, edición y borrado del canal invalidan el índice inmediatamente. Además, cada resultado vuelve a comprobar su mensaje original antes de mostrar el texto; si cambió, reconstruye y repite la búsqueda. Si Discord no permite verificar la fuente, no responde con una copia antigua.

Este sistema solo lee Discord: no modifica normas, canales, mensajes, roles ni permisos. No requiere acceso al host de FiveM ni bases de datos del juego, y no añade tablas al SQLite del bot.

Para revertir, seguir `RESTORE` de la versión en `change_log.py` conservando la base actual. Las normas originales no requieren restauración porque el buscador no las altera.

## Explicaciones de CK y PKT

El propietario solicitó añadir al comando el contenido conceptual de sus capturas, en palabras sencillas y como temas separados. `rule_topics.py` guarda esas explicaciones, que aparecen como **Explicación de administración**; el enlace al reglamento se presenta como contexto y no como una cita literal de esas explicaciones nuevas. No se publican ni se modifican mensajes en el canal original.

- **CK / Character Kill:** final definitivo del personaje, pérdida de su progreso, bienes, dinero y contactos dentro del rol; para continuar se crea otro personaje con otra historia. Explica que puede plantearse por acuerdo OOC o una situación importante de la historia y remite al ticket para revisión de administración. Es contenido explicativo, sin ejecutar cambios en datos del personaje ni saldos.
- **PKT / Player Kill Total:** pérdida total de los recuerdos relacionados con el conflicto o etapa acordados. El personaje sigue vivo y conserva cuerpo y nombre; olvida los hechos, personas, lugares e información de esa parte de la historia. Incluye el ejemplo del «cassette» y remite a administración para definir qué parte debe olvidarse.

`/regla ck`, `/regla pkt`, `Character Kill`, `PK Total`, abreviaturas con puntos y preguntas sencillas como «qué significa un PKT» abren el tema correspondiente. PK conserva sus resultados oficiales; no se convierte en PKT. El «cl» escrito por el dueño se interpretó como una errata por las capturas de CK; no se añade CL como alias de CK.

Ambos temas conservan la comprobación de acceso al canal de normas y sus respuestas privadas. No amplían los permisos ni ejecutan CK/PKT, borrados de bienes o cambios de economía.
