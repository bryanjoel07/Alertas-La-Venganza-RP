# Validación local

Fecha: 6 de noviembre de 2026. Python 3.12, Linux, datos temporales.

- Sintaxis: `python -m py_compile bot.py meetings.py storage.py backup.py summaries.py` correcta.
- 35 pruebas pasan con discord.py 2.7.1 (nuevo mínimo) y aiohttp 3.14.5.
- La entrega inicial pasó 15 pruebas con discord.py 2.4.0. Esa versión ya no es compatible
  con el selector de canales dentro del formulario. Se comprobó también 2.6.0 y no admite
  el parámetro required de ChannelSelect usado aquí: el mínimo se elevó a 2.7.1.
- `pip check`: sin dependencias incompatibles.
- Instalación opcional de `google-auth[requests]` verificada; no autenticación ni subida real.
- `git diff --check`: sin errores de espacios o conflictos.

Cobertura: esquema adicional conserva registros, reinicialización, respuestas únicas modificables,
asistencia independiente, edición conserva respuestas y presencia, cancelación/finalización bloquean
cambios, recordatorios persistentes y reserva concurrente, reinicio tardío sin ráfagas, reuniones ya
iniciadas sin avisos, base ausente/esquema incorrecto rechazan arranque, respaldo íntegro sin
sobrescritura, simulación sin caídas falsas, persistencia de estado y cierre de caída, estructura de
comandos, IDs de componentes únicos y persistentes, roles/canales privados y arranque con sync simulado.

Ninguna prueba conectó el bot a Discord ni accedió a datos de producción. No se ejecutó migración real.
La prueba de setup usa el contexto asincrónico de discord.py y sustituye sync por un mock;
no demuestra que Discord haya aceptado los comandos ni que los permisos de producción sean correctos.

Pendiente: token/intents/permisos reales, webhook, presentación móvil, mensajes existentes,
volumen Railway, respaldo externo de producción, autorización y subida/restauración Drive.
Los respaldos están preparados como herramienta manual; no hay programación automática activada.
La entrega contiene código completo y documentación, pero no es un despliegue validado en producción.

Selector de voz: probado payload del modal con cinco campos Label, tipo de canal restringido a
voz, selección única obligatoria, canal preseleccionado al editar, compatibilidad con lugares
anteriores, enlace del canal y rechazo de selección sin permiso de conexión o de tipo incorrecto.
El anuncio de Staff conserva como destino 1515887549678223380. Sin cambios de esquema ni datos.

Creación de eventos con banner: pruebas de apertura del formulario sin parámetro de archivo,
selector opcional de un archivo, confirmación anterior a la descarga, vista previa privada con
los bytes del banner, ausencia de publicación anticipada, flujo sin imagen, rechazo de archivos
mayores de 8 MB sin descargarlos y timeout de descarga que conserva el borrador.
No se midió la latencia desde un iPhone real: la carga del archivo depende de su red y de Discord.

Canal Staff: se verifica y preselecciona 1515887667298963579 sin cambiar el canal de anuncios
1515887549678223380. Se admiten voz y escenario; pruebas de selección de escenario, rechazo
por falta de permiso de conexión, conservación del canal anterior al editar y mensajes de
validación del comando. El tipo y los permisos reales del canal de producción no se consultaron
desde este entorno: se verifican con el bot al abrir/enviar el formulario.

Listas públicas: se verificaron creación única, edición del mismo mensaje tras reinicio,
actualizaciones concurrentes, separación por evento/reunión, reposición de lista eliminada,
retiro al cerrar evento, ausencia de pings, entrega incierta sin duplicados, reintento tras
rechazo de permisos y límites de Discord con listas grandes. Las pruebas de integración de
botones verifican inscripción/cancelación, respuestas cambiantes y cancelación de reunión
sin perder registros. `public_summaries` es una tabla nueva; no altera tablas anteriores.
No se verificó la entrega/edición real de mensajes públicos en Discord desde este entorno.
