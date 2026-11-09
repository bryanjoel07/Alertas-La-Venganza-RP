# Registro del bot

Por solicitud del propietario, los cambios del bot ya no se publican en Registro-Exclusive. Se conservan internamente para consulta privada y recuperación. `CHANGE_LOG_DISCORD_PUBLISH=0` mantiene desactivados los anuncios. La limpieza puntual del canal conserva una copia verificada de mensajes y adjuntos en las tablas `bot_channel_cleanup_*` del respaldo de SQLite.

- `/cambios historial`: versiones, fecha y estado; permite elegir página.
- `/cambios detalle registro:1`: explicación, instrucciones y descarga JSON del estado anterior y posterior. Solo administradores del servidor, respuesta privada.
- SQLite conserva la tabla `bot_changes` en el volumen persistente y en los respaldos completos existentes. Reiniciar no duplica una versión ni reemplaza su copia anterior.
- Las operaciones de navegación, accesos, Vista Hermosa y reparación de Staff se registran antes de ejecutarse y al finalizar, incluyendo estado parcial si fallan. Los cambios hechos manualmente en Discord se consultan en su registro de auditoría; este historial no los atribuye al bot.
- El primer despliegue crea la referencia inicial del servidor. No se inventa un estado anterior cuando no existía registro.

## Restauración

Cada registro conserva sus propias instrucciones. Esta versión de la tienda puede revertirse desplegando `1e02a08001fa9c42c63a6cd0df677233ec76532f` y conservando `/data` y su SQLite actual. El código anterior reconstruye el panel. No restaurar una base antigua para revertir una presentación: perdería compras posteriores.

Para una operación de Discord, descargar el JSON, comparar `before` y `after`, y restaurar solo los campos autorizados usando los IDs originales. Las copias contienen categorías, posiciones, permisos y nombres; no contienen mensajes y no recuperan canales borrados. Nunca borrar/recrear canales como mecanismo de restauración. Owner, Programador, Admin y Súper Admin están excluidos de cualquier modificación.

## Publicar cambios futuros

Antes de desplegar otra versión, actualizar `RELEASE`, `SUMMARY` y `RESTORE` en `change_log.py`, incluyendo el commit anterior correcto y la forma de revertir el cambio sin perder datos. Railway identifica cada versión por `RAILWAY_GIT_COMMIT_SHA`; fuera de Railway se usa `RELEASE`.
