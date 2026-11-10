# Feedback de atención del staff

Canal existente: **1539014594348064939 · ✨┊𝐅𝐞𝐞𝐝𝐛𝐚𝐜𝐤**. No se cambian sus permisos, mensajes anteriores, nombre ni categoría.

El panel ofrece **Dejar feedback**, **Mis opiniones** y **Ver resultados**. Se puede valorar un ticket cerrado o elegir a quien ayudó por voz o fuera de tickets. El buscador usa la lista completa del servidor, incluidos los miembros desconectados. En el formulario se eligen 1–5 estrellas, un comentario opcional y si la opinión se publica o queda solo para administración. Fuera de tickets también se pregunta con qué ayudaron.

Cada ticket recibe una sola opinión de su autor, incluso si se eliminó su canal. Nadie puede valorarse a sí mismo. Fuera de tickets se permite una opinión por jugador cada 24 horas; retirarla no reinicia ese plazo. Los botones antiguos de Valorar usan el mismo registro. Los mensajes privados de cierre llevan un botón persistente que sigue funcionando después de eliminar el canal.

Las opiniones públicas dan crédito al jugador y a quien lo atendió. No copian el asunto, la solución, los mensajes, las pruebas ni los enlaces privados del ticket. Los reportes contra staff fuerzan privacidad, aunque se altere el formulario. Las valoraciones privadas antiguas se importan una sola vez con su privacidad original. Los resultados públicos excluyen opiniones privadas y retiradas.

El responsable que sigue siendo staff, o un administrador, puede dejar una respuesta a una opinión pública. Los jugadores pueden consultar y retirar sus opiniones. La retirada conserva el texto y quién la solicitó para revisión privada. El filtro de palabras existente se aplica también a los comentarios del formulario y a las respuestas del staff; una valoración negativa sin insultos sí se admite.

## Administración

- `/feedback panel`: comprueba e instala el panel existente sin duplicarlo.
- `/feedback resumen persona:@alguien dias:30 pagina:1`: media, distribución de estrellas y opiniones públicas/privadas con sus IDs. Persona es opcional; `dias:0` consulta todo el historial y `pagina` recorre las opiniones de cinco en cinco.
- `/feedback ver numero:1`: detalle; una opinión privada o retirada solo es visible para su autor y para quienes tienen Administrador en Discord.
- `/feedback retirar numero:1 motivo:...`: muestra la opinión y pide confirmar la retirada; exige Administrador real, comprobado de nuevo al confirmar.

La instalación del panel y las retiradas se guardan en ChangeLog con copias antes/después. Las tablas `lv_feedback`, `lv_feedback_events` y `lv_feedback_config` están en el SQLite persistente y se incluyen en sus respaldos. Las opiniones se guardan antes de publicar; las publicaciones interrumpidas se buscan por su marca y los fallos se reintentan. Si alguien elimina una publicación desde Discord, no se vuelve a publicar automáticamente. Si falla una retirada, queda pendiente para completar la eliminación del mensaje del bot. No se crean opiniones ficticias en producción.

Para revertir, seguir `RESTORE` de esta versión en `change_log.py`. No restaurar un SQLite antiguo ni borrar opiniones para revertir el código.
