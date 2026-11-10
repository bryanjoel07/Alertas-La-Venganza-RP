# Reportes de errores

Foro: 1556488595131466000. El panel oficial del bot es 1569705426704924753; su ID se conserva en lv_bug_config.official_guide_v4. Se actualiza ese mismo mensaje, con «Reportar un error» y «Mis reportes», conservando las etiquetas y los permisos. Los reinicios no crean entradas duplicadas.

## Un solo formulario

1. ID dentro del juego.
2. Nombre del error.
3. Detalles: descripción, cómo ocurrió, sistema afectado y frecuencia. Cada apartado se guarda por separado.
4. Fotos y videos: **hasta 10 archivos mezclados, de 60 MiB cada uno** (62.914.560 bytes).
5. Enlace alternativo HTTPS, si no se adjuntan archivos.

Se admiten PNG, JPG/JPEG, WEBP, GIF, HEIC/HEIF y AVIF; y MP4, WEBM, MOV y M4V. Una foto sola cuenta como prueba; ya no se exige video en todos los reportes. Hace falta al menos un archivo o un enlace para guardar el formulario completo y publicar. La cuenta de Discord se identifica automáticamente. El aviso distingue un formato no compatible, un archivo vacío y un tamaño excesivo. Los nombres largos conservan su extensión.

Discord aplica además el límite de carga de la cuenta del jugador; el bot no puede ampliarlo. Un archivo ya aceptado por el selector no se rechaza por el límite menor de los adjuntos del bot. Si Discord impide subirlo, puede pegarse su enlace. Un enlace es una referencia para que el equipo revise su contenido.

## Preparación y publicación

Al enviar, el bot confirma los datos guardados y prepara los archivos en segundo plano. Para grupos, el mismo mensaje muestra el progreso; no se publica un reporte parcial. «Publicar reporte» permanece deshabilitado y el servidor bloquea su uso hasta guardar íntegramente todas las pruebas.

Los archivos se descargan de uno en uno dentro de cada grupo, con hasta dos preparaciones de reportes en paralelo y 180 segundos por descarga. Cada original tiene tamaño comprobado y SHA256. Los grupos sobreviven a reinicios y solo vuelven a descargar archivos pendientes; un trabajo antiguo no puede sobrescribir un formulario editado después. Si una descarga falla, se conservan los datos y se pide volver a adjuntar las pruebas o usar un enlace.

Una vez preparado, se muestra la vista previa y se confirma que el reporte será público. Cada envío crea **una sola publicación**, con crédito al jugador, detalles, estado y responsable. Para grupos, se muestran todas las fotos y se incluye un enlace individual para abrir cada foto o video. El archivo único puede adjuntarse directamente si cabe en el límite del bot; si lo supera, se sirve con un enlace al original. Una respuesta 413 también activa esa alternativa. No se eliminan pruebas al cerrar un reporte.

## Gestión

Tomar reporte y Cambiar estado comprueban permisos actuales: Owner, Programador, Admin, Súper Admin o Administrador de Discord. Un cambio de estado pide motivo y deja historial. Los cambios de etiquetas hechos directamente desde Discord se reflejan sin inventar quién los realizó. El bot no altera los permisos de roles ni del foro.

Los reportes abiertos directamente por jugadores también reciben controles. Una foto, video o enlace cuenta como prueba; si falta, se solicita en el mismo hilo y se bloquea el avance mediante los controles hasta recibirla. Administración puede cerrar un reporte incompleto. Se conserva el mensaje original.

- `/errores reportar`: crear o continuar un borrador.
- `/errores mis`: consultar los últimos 25 reportes propios.
- `/errores estado numero:1 estado:revision motivo:...`: actualizar un reporte, solo administración.

## Persistencia y lectura de archivos

SQLite conserva lv_bugs, lv_bug_events, lv_bug_config, lv_bug_uploads, lv_bug_media y lv_bug_files. Los archivos individuales anteriores siguen en lv_bugs.video; no se migran ni se eliminan. lv_bug_files conserva cada archivo de un grupo, su fuente de Discord, revisión, orden, estado, contenido, SHA256 y enlace aleatorio. El presupuesto compartido de originales es 1 GiB, incluyendo reservas de descargas pendientes. Los borradores reemplazados conservan sus pruebas anteriores hasta completar las nuevas; nunca se reemplazan archivos de un reporte ya publicado.

Las creaciones interrumpidas se buscan por autor, número y marca del bot antes de crear otro hilo. Los cambios de estado pendientes se reintentan. Los respaldos de SQLite incluyen los contenidos de ambas formas de almacenamiento. Formularios, listados y registros administrativos usan metadatos sin copiar todos los archivos a memoria.

`BUG_CLIPS_BASE_URL` configura el origen HTTPS y `PORT` el puerto del lector aiohttp en el mismo servicio Railway. `/health` confirma conexión a Discord, límite, tipos y máximo de archivos sin mostrar datos de jugadores. Las rutas `/clips/{token}/clip.ext` (archivo individual) y `/files/{token}/file.ext` (grupos) exigen tokens aleatorios de 256 bits y una publicación confirmada. No se comparten borradores ni índices de archivos. Quien reciba el enlace puede abrirlo; la confirmación del reporte ya indica que será público.

Cada lectura comprueba el acceso contra SQLite. El primer acceso crea una caché temporal con SHA256 verificado y cierra la transacción antes de servirla, para que un cliente lento no bloquee la economía u otras escrituras. aiohttp admite Range, HEAD y caché condicional. La caché temporal se reconstruye desde el original en SQLite y no requiere respaldo. Las fotos se sirven con su tipo de imagen y los videos con su tipo de video, con nosniff.

Los logs BUGS form_received, file_prepared y files_prepared separan recepción y preparación. No se registran fuentes privadas, nombres de archivos ni contenido del usuario. Las interacciones normales aprovechan el miembro de Discord recibido; los controles administrativos conservan comprobaciones frescas.

## Restauración

Consultar RESTORE en change_log.py. El código anterior no reconoce grupos ni sirve `/files`; conservar esas funciones y su dominio al desactivar nuevas cargas múltiples. No restaurar una base antigua para revertir una presentación.

La retirada anterior de la plantilla manual 1564719087798460466 fue autorizada por el dueño, respaldada con JSON y SHA256 en lv_bug_panel_backups y verificada sin reportes reales, archivos ni respuestas de terceros. No se repite esa limpieza. El historial privado conserva también el texto anterior a cada actualización de este panel.
