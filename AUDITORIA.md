# Auditoría del código original

Referencia inspeccionada: GitHub `bryanjoel07/Alertas-La-Venganza-RP`, commit
`30578fbb4a2c21c1af942fcec5c6e4e9192ce44f`. Cuatro archivos, sin subdirectorios ni pruebas.
Se revisaron todos: bot.py (1123 líneas), requirements.txt, railway.json y README.md.
No se inspeccionó la base de Railway: no está incluida en el repositorio ni disponible aquí.

## Implementado en la referencia original

- Monitor cada 30 segundos, confirmación de 90, lectura del campo Estado/Status de embeds,
  rechazo de parciales/desconocidos, estado persistente, historial y webhook desde entorno.
- Simulaciones separadas del tracker real y de la tabla outages.
- Mantenimiento con motivo, autor e intervalo; pausa del monitor y nueva referencia al finalizar.
- Eventos con dos formularios, cupos/premios, imagen adjunta opcional, vista previa, confirmación,
  inscripciones únicas/cancelables, contador y botones persistentes.
- Edición, premios/cupos con límite mínimo según inscritos, cambio de banner, participantes,
  finalización con tres miembros distintos, podio y borrado del anuncio al cerrar.
- Comandos administrativos protegidos con permiso Administrador de Discord.
- SQLite con transacciones commit/rollback y tablas settings, outages, maintenance, events,
  registrations. `CREATE TABLE IF NOT EXISTS`, sin sistema de versiones del esquema.
- Railway usa Railpack, ejecuta `python bot.py`, reintenta fallos diez veces. No fija Python.
  Dependencias: `discord.py>=2.4,<3.0`, `aiohttp>=3.9,<4.0`; SQLite es parte de Python.

## Ausente o incompleto

- No hay código de reuniones, sus canales/roles, confirmaciones, asistencia ni recordatorios.
- No hay backups programados, exportación Drive ni protección ante base vacía.
- README solo contiene el nombre. No hay instrucciones de despliegue ni pruebas.
- Listas de eventos se limitan a 30 en botones y se truncan en comando administrativo.
- Borradores son memoria temporal: se pierden al reiniciar, aunque los eventos publicados persisten.

## Riesgos y correcciones locales

1. Ruta calculada desde DATA_DIR, RAILWAY_VOLUME_MOUNT_PATH o /tmp: montar un volumen puede
   cambiar el origen silenciosamente. Se añadió guardia de existencia/ambigüedad y DB_PATH explícita.
2. Edición de datos/banner restablecía el botón a «Inscritos» sin número: se conserva el conteo.
3. Se permitía editar eventos cerrados cuyo mensaje ya había sido borrado: ahora requiere estado abierto.
4. Formularios y publicación no revalidaban permisos si se retiraba el rol después de abrirlos:
   se añadió comprobación y respuesta de error para vistas/formularios administrativos.
5. El campo Ganadores usaba separador literal `\\n`: corregido a salto de línea.
6. Premios escapados podían superar el límite de campo de Discord: se limita su presentación a 1024.
7. Un borrador podía publicarse después de su hora programada: ahora se rechaza.
8. Operaciones SQLite heredadas podían esperar 20 segundos en el hilo del bot: se redujo a 1 segundo.
   Inicialización y toda la persistencia nueva de reuniones se ejecutan en hilos.
9. Respuesta de error del webhook se incluía parcialmente en excepciones: ahora solo código HTTP.
10. Se añadió cancelación de tareas al cerrar el cliente.

## Límites pendientes

- La ruta real, integridad y conteos actuales, el contenido de /tmp/respaldo.db y su descarga externa
  siguen sin confirmar. El repositorio no demuestra el estado del servicio desplegado.
- El monitor heredado puede repetir una alerta si Discord recibe el webhook y falla la escritura
  posterior a SQLite. No hay transacción distribuida Discord/SQLite. Se conserva su flujo para
  evitar una reescritura de producción; se requiere recuperación operativa ante este fallo.
- Al iniciar mantenimiento, las caídas abiertas terminan como interrumpidas (duración NULL).
  Al finalizar, el estado leído se adopta como referencia, sin alerta de transición. Esto se conservó.
- La duración de caídas comienza en la confirmación, no en la primera muestra; se conservó.
- Las operaciones originales todavía usan SQLite síncrono con espera acotada; no se reescribieron
  todos los sistemas heredados en esta entrega. Una base muy grande necesita medición real.
- Si Discord acepta una publicación y falla el guardado posterior, puede quedar anuncio huérfano
  (eventos/podio y reuniones). Revisar mensajes y logs antes de repetir una operación fallida.
- Una cancelación/finalización persiste aunque Discord no permita editar el anuncio: los callbacks
  rechazan cambios nuevos y se avisa del fallo visual. Falta comprobar permisos reales.
- Hay que usar una réplica y evitar solapamiento durante despliegues de Railway.
- Drive se prepara mediante CLI opcional, sin credenciales ni subida probada. La programación de
  backups no está activada. Hay que verificar una restauración externa antes de confiar en ella.
- No se auditó exhaustivamente todo el historial Git en busca de secretos. Esta copia de trabajo
  no contiene tokens/webhooks literales; esto no garantiza que nunca estuvieron en commits anteriores.
- No se verificaron anuncios en iPhone, sincronización real slash, permisos reales, persistencia del
  volumen ni envíos a Discord. Esas comprobaciones requieren un despliegue autorizado y supervisado.
