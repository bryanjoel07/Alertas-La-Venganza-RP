# Centro de atención de La Venganza RP

Entrada: canal `1513423707467415642`. La activación usa `TICKETS_ENABLED=1`.

## Atención al jugador

El panel oficial ofrece Soporte técnico, Reportar jugador, Problemas con tienda, Donaciones, Apelar sanción, Gangas/negocios y Reportar al staff. Cada formulario solicita asunto, detalles, referencia y pruebas; los reportes permiten identificar al reportado por ID de Discord. Los adjuntos se envían dentro del caso. La tienda permite vincular únicamente compras propias (como pagador o destinatario).

Se permite un caso activo por usuario y motivo, hasta tres abiertos y una apertura por minuto. Se conserva el mismo canal al cerrar y reabrir. El autor puede reabrir durante siete días; después necesita al staff. Los participantes adicionales no pueden cerrar ni reabrir por su cuenta.

## Privacidad y roles

- Soporte, Moderador y Jefe de Staff atienden casos normales; donaciones sigue este mismo acceso, según la decisión del propietario.
- Los reportes contra staff están reservados al autor y usuarios que tengan Administrador de Discord. Owner y Programador lo tienen. No se promete ocultar un canal a un administrador, porque Discord permite el acceso técnico.
- La categoría Tickets Cerrados y sus casos normales conceden Ver canal y Leer historial a Owner, Programador, Jefe de Admin/Staff, Súper Admin, Admin, Moderador y Soporte, según la instrucción expresa del propietario. No se cambian sus permisos generales ni posiciones. Los reportes reservados mantienen su privacidad. En casos activos se puede usar Gestión Staff o `/ticket acceso numero:…` para el acceso individual autorizado.
- Las notas se guardan aparte y solo se consultan en respuestas privadas del personal autorizado. No se incluyen en transcripciones de jugadores.
- El reportado queda excluido del caso salvo que tenga Administrador, permiso que el bot no puede anular.
- Transferir al área reservada retira el acceso de participantes y revisores no autorizados. No se permite transferir un reporte reservado hacia un departamento normal.
- No se modifica Owner, Programador, Admin, Súper Admin ni los permisos generales de Ciudadanos. Los canales existentes del sistema anterior quedan intactos.

## Gestión

Controles persistentes: Eliminar ticket (solo tras cerrar), Reclamar, Solicitar pruebas, Resolver, Cerrar, Reabrir, Transcripción, Nota interna, Transferir, Prioridad, Participantes, Valorar y Pruebas guardadas.

Comandos principales:

- `/ticket mis`, `/ticket cerrados` y `/ticket gestion`: listas paginadas. El panel incluye un botón Tickets cerrados para abrir la lista autorizada desde el canal de entrada. Los datos reservados se filtran antes de calcular estadísticas.
- `/ticket acceso`, `/ticket estado`, `/ticket transferir`, `/ticket participante`.
- `/ticket nota`, `/ticket notas`, `/ticket historial`.
- `/ticket transcripcion` y `/ticket archivo` descargan copias privadas tras verificar de nuevo la autorización.
- `/ticket compra` consulta la compra vinculada; `/ticket devolver` exige autorización de economía, un motivo y una confirmación. Usa las transacciones idempotentes de la tienda, sin cobros ni devoluciones al abrir un caso.
- `/ticket configuracion`: límites y tiempos; requiere Administrador.
- `/ticket departamento`: añadir/quitar roles encargados en departamentos normales. No acepta roles protegidos, Ciudadanos, @everyone ni roles de bots. Los roles habituales de staff mantienen su acceso.
- `/ticket recuperar`: concilia creaciones y archivos interrumpidos. Una creación incierta nunca genera otro canal automáticamente. Tras revisar la auditoría y esperar dos minutos, un administrador puede cancelar solo la reserva con `cancelar_reserva:true` para permitir una nueva solicitud, sin borrar canales.

Estados: Nuevo → En atención → Esperando al jugador → Resuelto → Cerrado. Cada actuación conserva actor, fecha y motivo. Prioridades: normal, alta o urgente, con justificación.

Avisos: recordatorio tras 6 horas pendientes. Los casos esperando al jugador reciben advertencia después de 72 horas y se archivan tras otras 24 horas sin respuesta. Responder cancela el cierre pendiente. Los resueltos no se cierran automáticamente sin aviso. No se usa @everyone; la apertura avisa a los roles encargados dentro del canal privado, y los recordatorios se limitan al autor o responsable.

## Archivo y recuperación

Se crea `│・ 🔒┊ 𝐓𝐢𝐜𝐤𝐞𝐭𝐬 𝐂𝐞𝐫𝐫𝐚𝐝𝐨𝐬`, junto a Tickets. El bot mueve el mismo canal y conserva su historial, con escritura desactivada para participantes habituales. Si una categoría llega a su capacidad, crea otra privada con sufijo, sin mover tickets anteriores. No hay eliminación automática. Después del cierre aparece **Eliminar ticket**, solo para staff autorizado y con confirmación. Antes de borrar el canal se exige una transcripción completa, integridad de las pruebas y un respaldo verificado (Drive cuando está habilitado). Si falla, el canal se conserva. El registro y las pruebas permanecen accesibles con Tickets cerrados, aunque el canal ya no exista; no se puede reabrir un canal eliminado.

Mensajes y sus ediciones/eliminaciones se conservan en tablas SQLite. Los adjuntos se guardan como datos binarios con SHA-256, por lo que los respaldos completos existentes (incluido Drive) contienen también las pruebas, no solo enlaces caducables. Límites iniciales: 25 MB por archivo, 100 MB por caso y 500 MB en total; se reserva espacio para respaldos. Si falla una copia o excede el límite, se avisa y el archivo figura como no respaldado. Los enlaces externos son referencias, no copias de archivos.

El HTML de transcripción escapa el contenido de usuarios y excluye notas internas. Los archivos grandes se entregan por partes privadas con `/ticket archivo`. Los estados parciales se muestran explícitamente; los cierres interrumpidos se reconcilian al reiniciar.

Las acciones de tickets tienen su propio historial. Las creaciones, movimientos y cambios de accesos guardan además copias antes/después en `/cambios`, utilizando solo el caso afectado cuando corresponde.

## Migración y reversión

El nuevo panel se publica y fija en el canal indicado. Los paneles y casos de otros bots no se eliminan ni se modifican: los casos anteriores deben cerrarse desde sus controles originales. Este bot solo administra canales con sus propios registros y la marca `lv-ticket:<número>`.

Para pausar, poner `TICKETS_ENABLED=0` en Railway; se conserva toda la información. Para volver al código anterior desplegar `a85b9bdc5f9564abfcd57d5463fb94508d1768cc`, conservando `/data` y SQLite. No restaurar una base vieja sobre la actual: se perderían actuaciones nuevas. Conservar los canales ya creados y sus IDs. No modificar los cuatro roles protegidos para recuperar tickets.

`TICKETS_INSTALL_REQUEST_ID` identifica la instalación en el registro. `TICKETS_SELFTEST_REQUEST_ID` activa una única verificación privada con dos casos del bot, excluidos de las estadísticas de atención. Verifica privacidad, notas, respaldo real de adjuntos, cierre, reapertura, transferencia y una copia/restauración en Drive si los respaldos automáticos están habilitados. Quitar estas dos variables tras verificar; mantener `TICKETS_ENABLED=1`.
