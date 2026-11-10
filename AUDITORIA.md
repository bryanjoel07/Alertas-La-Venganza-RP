# Auditoría y optimización del bot — 10 de noviembre de 2026

Referencia anterior: `ac09372d59020d6994aaf3ba1dd88728865c6ebe`.
Entrega: `bot-runtime-audit-v21`. Servicio: Alertas La Venganza RP, Railway.
La auditoría inicial del repositorio de cuatro archivos se conserva en el historial Git de este documento; ya no describe el bot actual.

## Evidencia inicial

- Se revisaron los módulos del bot, sus tareas, consultas, conexiones, formularios, recuperación, archivos y dependencias. Se cruzaron referencias de importaciones y herramientas temporales antes de retirar código.
- Las 635 pruebas originales pasaron antes de modificar código: 14.218 s en este entorno.
- En los registros acotados del despliegue `deb7086d-01d6-4c77-b7dd-656f463acaba` no aparecieron errores de ejecución. Sí se observó doble preparación de Reportes y Feedback al arrancar.
- Railway, ventana previa de una hora: CPU media 0.00202 núcleos, máxima 0.02377; memoria media 0.081276 GB, máxima 0.18913 GB. No hay evidencia de falta de CPU o memoria en esa ventana. Son métricas agregadas del servicio, no una prueba de carga ni una medida de la mejora.
- El host directo de FiveM no respondió en una muestra; Connect sí permitió continuar el monitoreo. Se conserva esa combinación de fuentes y la confirmación de cambios de estado.

## Problemas corregidos

| Hallazgo | Cambio y protección |
| --- | --- |
| Consultas de lectura reservaban el bloqueo de escritura con `BEGIN IMMEDIATE`. | Transacciones comunes con lectura real (`mode=ro`, `query_only`, `BEGIN`) en diez almacenes. Las operaciones que compran, pagan, votan, reclaman, migran o modifican datos conservan su transacción de escritura. |
| Lectores podían frenar la confirmación de escrituras largas. | SQLite WAL con durabilidad FULL. Antes de cambiar una base existente se exige un respaldo completo, integridad comprobada, SHA-256 y manifiesto privado. Si falla el respaldo, no se cambia el diario. Se conserva la base original y su ruta. |
| El seguimiento cargaba hasta 10,000 tickets completos, incluyendo transcripciones cerradas, cada minuto. | Consulta de metadatos de casos activos. Conserva también los paneles cerrados que aún tienen pendiente confirmar una prioridad. No se elimina ningún registro ni archivo. |
| La recuperación recorría todo el historial y descargaba los canales del servidor incluso sin trabajo pendiente. | Consulta solo de operaciones interrumpidas. Descarga el inventario de canales únicamente si debe buscar una creación pendiente. Conserva las reservas, archivos interrumpidos y comprobaciones contra duplicados. |
| Historiales por ticket carecían de índices adecuados. | Índices para seguimiento activo, eventos, notas y versiones de mensajes. Los planes SQL se verifican en pruebas; no se reconstruyen tablas ni se cambia el contenido. |
| Dos rutas de arranque preparaban los mismos paneles con pocos segundos de diferencia. | Preparación coordinada y comprobación breve de Reportes. Cada ciclo continúa verificando el panel y puede repararlo si desaparece o cambia. Feedback conserva actualización inmediata después de una opinión. |
| Varios `start()` podían crear otra tarea si se llamaban dos veces. | Inicio idempotente en Tickets, Fotos, Feedback, Reportes, Solicitudes y Sugerencias; también en los bucles de directos y su panel. |
| El cierre cancelaba tres bucles de Discord sin esperar su finalización. | Se espera a que terminen las tareas antes de cerrar descargas y el servidor de archivos. Se cierra explícitamente la conexión de validación de la ruta de SQLite. |
| El diagnóstico privado mostraba solo parte de las tareas. | `/estado-bot` incluye los sistemas principales, el modo de diario y el tamaño del WAL. No expone credenciales. |

## Código retirado y conservado

Se eliminaron `channel_design.py`, una inspección temporal del foro ya transferido, y `ticket_priority_repair.py`, una corrección puntual ya completada para el ticket #5. También se retiraron sus llamadas, dos pruebas exclusivas de esa herramienta terminada y las importaciones sin uso verificadas. Sus estados e historial siguen en SQLite y Git.

Se consolidó el manejo repetido de conexiones en `sqlite_runtime.py`, conservando la política previa de claves foráneas y los tiempos de espera de cada almacén.

Se conservan expresamente las migraciones necesarias para instalaciones anteriores, la recuperación de operaciones pendientes, los adjuntos antiguos, los respaldos y `stream_proof.py` (lo ejecuta la verificación de creadores). La antigüedad de un archivo no demuestra que esté sin uso. Las advertencias de librerías opcionales de audio no requieren instalar dependencias: este bot no conecta audio.

## Validación

- Suite completa: **647 pruebas**, incluyendo concurrencia, bloqueo, rollback, copia anterior a WAL, respaldo con registros aún en WAL, consultas de recuperación, índices, paneles y cierre ordenado.
- Se conservaron 633 pruebas funcionales anteriores; las dos retiradas correspondían exclusivamente a la corrección puntual ya terminada. Se añadieron 14 pruebas para esta optimización y se ampliaron las de paneles.
- Comparación AST: definiciones de comandos y `custom_id` de componentes sin cambios en los 29 módulos modificados que existían anteriormente. No se añaden cambios de roles, permisos, categorías, precios, recompensas o saldos.
- Los módulos compartidos se verifican con las pruebas actuales de privacidad, miembros de tickets, administración, economía, fotos, reportes de hasta 120 MB, minijuegos, solicitudes, sugerencias, normas y respaldos.

Medición reproducible, **con datos temporales, fuera de producción**:

```bash
.venv/bin/python benchmarks/sqlite_audit.py --records 5000 --runs 5
```

| Seguimiento de 5,000 tickets cerrados y 5 abiertos | Antes | Después |
| --- | ---: | ---: |
| Registros devueltos | 5,005 | 5 |
| Mediana de consulta, cinco repeticiones | 139.513 ms | 0.427 ms |
| Pico de memoria Python durante la consulta | 47,635,398 bytes | 6,393 bytes |

El mismo ensayo comprueba que la lectura nueva continúa con una escritura pendiente y que, con WAL, un escritor puede confirmar mientras otro lector conserva su instantánea. Estas cifras describen esa consulta y ese conjunto de prueba; no representan la latencia completa del bot ni una mejora medida en el tráfico real.

## Despliegue y recuperación

La publicación en `main` activa Railway. La comprobación operativa debe confirmar el estado terminal `SUCCESS`, la versión servida por `/health`, conexión a Discord, comandos sincronizados, preparación de los sistemas y ausencia de errores nuevos en los registros del despliegue. El arranque registra `STORAGE before_wal_backup_verified` y `STORAGE ready journal_mode=wal synchronous=FULL`.

Para revertir código, desplegar `ac09372d59020d6994aaf3ba1dd88728865c6ebe` conservando el volumen y la base actual. Ese código admite WAL y los índices adicionales. No restaurar la copia anterior para revertir código: se perderían los movimientos posteriores. No borrar `-wal` o `-shm` ni copiar solo el archivo principal; usar `backup.py`, que emplea la API de respaldo de SQLite. El manifiesto de `backups/before-wal-*.sqlite3` corresponde al momento anterior al cambio de diario y no sustituye los respaldos externos existentes.

## Límites de la revisión

Verificación operativa realizada a las **22:40 UTC**: commit `5617cb355bf3e99fc543725f4b21a98bbfc01031`, despliegue `97bf1260-5ef9-448d-adc9-7a972ad2e3aa` en `SUCCESS`, una réplica activa y ninguna caída o incidencia de Railway. `/health` devolvió `status=ok`, `discord_connected=true` y `release=5617cb355bf3`, manteniendo fotos, videos, diez archivos y 120 MB. El arranque verificó una copia de 42,369,024 bytes con integridad `ok` y SHA-256 `cf682edc03f2e43a007fd8743290374ce79c89475ea063a0ea48d32f0908e5f3`, seguida de WAL con durabilidad FULL. Se confirmaron los sistemas y comandos, incluido el ticket asignado #5 con sus cuatro controles. Reportes y Feedback se prepararon una sola vez; no aparecieron errores nuevos, reintentos pendientes ni bloqueos SQLite en la ventana revisada. Sigue el aviso previo de que el canal del ticket cerrado #6 ya no existe; se conserva su registro, sin inventar ni borrar historia.

No se dispone de una consola SQL remota ni de una copia de producción para ejecutar pruebas destructivas; el cambio de diario exige y verifica su propia copia dentro del volumen. Los ensayos funcionales se hacen en bases temporales. La comprobación real del despliegue se realiza con Railway y el endpoint de salud, sin crear tickets de jugadores, gastar monedas ni publicar mensajes de prueba.

La velocidad de Discord, las subidas del jugador y la disponibilidad del servidor de juego dependen también de servicios externos. Sigue siendo posible una respuesta ambigua cuando Discord acepta una operación y la conexión se pierde antes de confirmarla; se conservan las reservas, recibos y rutas de recuperación existentes. No se ha auditado todo el historial Git en busca de secretos ni se afirma haber reproducido cada condición de carga real.

## Corrección posterior del GIF de SERVER UP — v22

El propietario mostró la imagen rota del aviso `1569841663361417331`. El enlace firmado que había compartido venció el 10 de noviembre a las 12:06:30 UTC y devuelve HTTP 403. El GIF guardado en el proyecto sí se decodifica completo: 400 × 225, 150 fotogramas, diez segundos y 7,083,987 bytes, SHA-256 `69e8b6cba68d6824ba837ac8dbe0f3fe1ac588571f154ffd167e84fe1e484f23`. No se altera su contenido ni su animación.

Se añade una ruta pública exacta para ese archivo en el servidor HTTP existente, con tipo `image/gif` y URL que incluye su huella. No permite listar archivos ni acceder a otras rutas. Los avisos nuevos usan esa dirección estable sin un segundo adjunto visible. Se conserva la alternativa de adjuntar el GIF si no está configurado el servidor de archivos.

La reparación del aviso indicado verifica canal, autor, mensaje y adjuntos, guarda el estado previo con `ChangeLog.tracked` y edita solo la imagen en el mismo mensaje, sin nuevas menciones. Verifica tanto los bytes originales servidos como la respuesta del proxy de imágenes de Discord antes de registrar su finalización. La suite ampliada pasa **654 pruebas**, incluyendo preservación del GIF, ruta pública, aviso único, reparación con copia previa, permisos de menciones vacíos al editar y reintento de procesamiento de imágenes de Discord.
