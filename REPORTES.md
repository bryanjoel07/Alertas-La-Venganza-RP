# Reportes de errores

Foro existente: 1556488595131466000. La plantilla manual antigua 1564719087798460466 se reemplaza, por petición expresa del dueño, con una publicación del bot: instrucciones, «Reportar un error» y «Mis reportes» juntos en el mismo mensaje. Su ID queda en lv_bug_config.official_guide_v4. Las etiquetas y los permisos se conservan. No se crean varias entradas activas al reiniciar.

El formulario es una sola ventana. Sus cinco campos son ID dentro del juego, título, detalles con cuatro apartados, archivo de video y enlace alternativo. El cuadro de detalles trae los títulos «Descripción del error», «Cómo ocurrió», «Sistema afectado» y «Frecuencia»; hay que completar todos. Cada respuesta se guarda por separado y aparece con su encabezado en el reporte. Se puede **adjuntar un video MP4, WEBM, MOV o M4V de hasta 60 MiB (62.914.560 bytes)**, o pegar un enlace HTTPS. Discord aplica además el límite de carga de la cuenta del jugador; el bot no puede ampliar ese límite del selector nativo. Un archivo que Discord ya aceptó no se rechaza por el límite inferior de los adjuntos del bot. El enlace es una referencia para revisión del equipo, no una validación automática del contenido del video. La cuenta de Discord se identifica automáticamente. El clip es obligatorio: sin archivo ni enlace válido no se guarda el formulario como completo ni se publica un reporte. La vista previa avisa que el reporte será público y requiere confirmar antes de publicar. Los borradores sobreviven a reinicios.

Cada reporte crea un hilo con Pendiente, el crédito del jugador, los datos y el archivo. Los botones Tomar reporte y Cambiar estado comprueban permisos actuales: Owner, Programador, Admin, Súper Admin o Administrador de Discord. Cambiar estado pide un motivo y conserva el historial. El bot no cambia los permisos nativos de los roles ni del foro. Los cambios de etiqueta hechos directamente desde Discord se reflejan sin inventar quién los realizó.

Los reportes abiertos directamente por jugadores también reciben controles. Si falta el clip, el bot lo solicita en el mismo hilo y bloquea el avance mediante sus controles hasta recibirlo; administración puede cerrar uno incompleto. Se conserva el mensaje original. La plantilla sigue explicando los ocho campos que deben completar los reportes manuales.

- `/errores reportar`: abrir o continuar un borrador.
- `/errores mis`: consultar los últimos 25 reportes propios.
- `/errores estado numero:1 estado:revision motivo:...`: actualizar un reporte, solo administración.

SQLite conserva lv_bugs, lv_bug_events y lv_bug_config. Los archivos del formulario tienen SHA256 y se guardan antes de enviar a Discord; el presupuesto total de esos archivos es 1 GiB, incluyendo reservas de cargas pendientes. Los archivos o enlaces publicados manualmente permanecen en sus mensajes de origen. No se eliminan reportes ni evidencias al cerrar. Las creaciones interrumpidas se buscan por autor, número y marca del bot antes de crear otro hilo. Los cambios de estado pendientes se reintentan. El panel se reconstruye usando sus IDs y su marca.

Para revertir el código, seguir RESTORE en change_log.py conservando SQLite, los videos y las publicaciones.

La retirada de la plantilla antigua requiere una copia JSON con SHA256, un panel nuevo verificado y ausencia de reportes reales, archivos o respuestas de terceros en la publicación anterior. Si aparecen, se conserva archivada para revisión. La copia queda en lv_bug_panel_backups; el historial administrativo registra el reemplazo. No se eliminan otras publicaciones.

## Recepción del formulario y preparación del clip

Al enviar, primero se validan los apartados y se guardan los datos junto con la fuente del archivo de Discord. El mismo mensaje privado muestra «Datos guardados. Preparando el clip…», sin esperar a descargarlo. Publicar está deshabilitado y el servidor también bloquea su uso hasta que el archivo esté completo. Al terminar, el mensaje se convierte en la vista previa normal, sin una segunda publicación. Con enlace y sin archivo no hace falta preparar una descarga.

La tabla lv_bug_uploads conserva fuente, tamaño, revisión y estado. Dos preparaciones pueden trabajar a la vez. Una interrupción del proceso conserva el trabajo pendiente para el siguiente arranque; un fallo de descarga conserva los datos y pide volver a adjuntar o usar un enlace. Un trabajo antiguo no puede sobrescribir un formulario editado después. No se almacenan tokens de interacción ni se registran enlaces privados en los logs.

Los logs BUGS form_received y BUGS clip_prepared separan el tiempo de recepción del tiempo de descarga. La comprobación ordinaria aprovecha el miembro recibido en la interacción; los controles administrativos siguen leyendo al miembro y sus permisos actuales desde Discord.

## Publicación de clips grandes

Los videos que caben en el límite del bot siguen adjuntándose al reporte. Los mayores se publican con «Ver el clip», un enlace HTTPS al original guardado en Railway; no se intenta enviarlos como adjuntos que Discord rechazaría. Una respuesta 413 de Discord también activa esta alternativa. La preparación del archivo tiene hasta 180 segundos y no retiene la confirmación inicial del formulario.

`BUG_CLIPS_BASE_URL` configura el origen HTTPS y `PORT` el puerto del lector aiohttp en el mismo servicio. `/health` confirma el límite del bot y su conexión a Discord sin mostrar datos de jugadores. `/clips/{token}/clip.mp4` (o la extensión original) solo permite leer un video cuya publicación fue confirmada. El token aleatorio de 256 bits se conserva en lv_bug_media junto al SHA256: no se publican enlaces a borradores ni índices de archivos. Quien reciba el enlace puede abrir el clip; el foro de Reportes ya es público y su confirmación lo indica.

El lector comprueba cada acceso contra SQLite. Al primer acceso crea una copia temporal con SHA256 verificado y cierra la transacción antes de servirla, para que una conexión lenta no bloquee la economía u otras escrituras del bot. aiohttp admite reproducción por partes (Range), HEAD y caché condicional. La caché temporal se reconstruye desde SQLite al reiniciar; no hace falta incluirla en respaldos. El archivo original permanece en SQLite y en sus respaldos existentes. Formularios, listados y registros administrativos usan metadatos sin copiar los videos completos.

Conservar el dominio y el lector si se revierte el resto del cambio: el código antiguo no sirve estos enlaces. Consultar RESTORE en change_log.py.
