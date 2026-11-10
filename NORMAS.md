# Buscador de normas

`/regla tema` busca en el canal oficial indicado por el dueño: `1528925322362228787` (Info-Servidor). La respuesta es privada y ofrece un enlace al mensaje original. Ejemplos: `/regla ck`, `/regla pk`, `/regla secuestros`, `/regla vehículos`, `/regla zonas seguras`.

La fuente comprobada contiene ocho apartados, publicados en los mensajes `1567278823324782854` y `1567278835332812821`. CK se menciona en Muerte y heridas; PK se menciona ahí y en Enfrentamientos. El canal no contiene una definición detallada de CK. El bot devuelve los apartados tal como están publicados, sin completar las condiciones con definiciones de otros servidores.

## Búsquedas y resultados

- Lee texto y embeds del canal y separa los apartados por sus encabezados, conservando sus condiciones completas.
- Reconoce abreviaturas y algunas variantes de búsqueda; normaliza acentos, puntuación y letras decorativas. Las abreviaturas se buscan como palabras completas para no confundir PK con PKT ni encontrar coincidencias dentro de otras palabras.
- Las coincidencias en el título tienen prioridad. Si hay varios resultados, se muestran con Anterior y Siguiente; cada uno enlaza a su propio mensaje original. Un resultado único solo muestra el botón del enlace.
- Los apartados largos se dividen en partes navegables sin eliminar sus últimas condiciones. La respuesta no es un resumen generado.
- El autocompletado ofrece temas y títulos que realmente aparecen en la fuente. Si no hay coincidencia, lo indica y ofrece abrir el canal.

## Acceso y actualización

Solo se usa dentro del servidor y por miembros que puedan ver el canal de normas y leer su historial. Cada navegación comprueba otra vez el acceso. Los controles privados pertenecen a quien hizo la búsqueda; no se menciona a todos ni se publica la consulta en el chat.

El índice se guarda en memoria, se reconstruye al reiniciar y se refresca cada cinco minutos. Los eventos de creación, edición y borrado del canal invalidan el índice inmediatamente. Además, cada resultado vuelve a comprobar su mensaje original antes de mostrar el texto; si cambió, reconstruye y repite la búsqueda. Si Discord no permite verificar la fuente, no responde con una copia antigua.

Este sistema solo lee Discord: no modifica normas, canales, mensajes, roles ni permisos. No requiere acceso al host de FiveM ni bases de datos del juego, y no añade tablas al SQLite del bot.

Para revertir, seguir `RESTORE` de la versión en `change_log.py` conservando la base actual. Las normas originales no requieren restauración porque el buscador no las altera.
