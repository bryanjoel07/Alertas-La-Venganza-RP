# Reportes de errores

Foro existente: 1556488595131466000. La plantilla oficial 1564719087798460466, las etiquetas y los permisos se conservan. El bot añade una publicación con «Reportar un error» y «Mis reportes». Como Discord permite un solo hilo fijado, conserva fijada la plantilla oficial y añade también esos botones dentro de ella.

El formulario tiene dos pasos: ID dentro del juego, título, descripción, pasos y sistema afectado; después frecuencia y clip. Se puede **adjuntar un video MP4, WEBM, MOV o M4V de hasta 25 MB**, o pegar un enlace HTTPS. El enlace es una referencia para revisión del equipo, no una validación automática del contenido del video. La cuenta de Discord se identifica automáticamente. La vista previa avisa que el reporte será público y requiere confirmar antes de publicar. Los borradores sobreviven a reinicios.

Cada reporte crea un hilo con Pendiente, el crédito del jugador, los datos y el archivo. Los botones Tomar reporte y Cambiar estado comprueban permisos actuales: Owner, Programador, Admin, Súper Admin o Administrador de Discord. Cambiar estado pide un motivo y conserva el historial. El bot no cambia los permisos nativos de los roles ni del foro. Los cambios de etiqueta hechos directamente desde Discord se reflejan sin inventar quién los realizó.

Los reportes abiertos directamente por jugadores también reciben controles. Si falta el clip, el bot lo solicita en el mismo hilo y bloquea el avance mediante sus controles hasta recibirlo; administración puede cerrar uno incompleto. Se conserva el mensaje original. La plantilla sigue explicando los ocho campos que deben completar los reportes manuales.

- `/errores reportar`: abrir o continuar un borrador.
- `/errores mis`: consultar los últimos 25 reportes propios.
- `/errores estado numero:1 estado:revision motivo:...`: actualizar un reporte, solo administración.

SQLite conserva lv_bugs, lv_bug_events y lv_bug_config. Los archivos del formulario tienen SHA256 y se guardan antes de enviar a Discord; el presupuesto total de esos archivos es 200 MB. Los archivos o enlaces publicados manualmente permanecen en sus mensajes de origen. No se eliminan reportes ni evidencias al cerrar. Las creaciones interrumpidas se buscan por autor, número y marca del bot antes de crear otro hilo. Los cambios de estado pendientes se reintentan. El panel se reconstruye usando sus IDs y su marca.

Para revertir el código, seguir RESTORE en change_log.py conservando SQLite, los videos y las publicaciones.
