# Centro de atención de La Venganza RP

Entrada: canal `1513423707467415642`. La activación usa `TICKETS_ENABLED=1`.

## Atención al jugador

El panel oficial ofrece Soporte técnico, Reportar jugador, Problemas con tienda, Donaciones, Apelar sanción, Gangas/negocios y Reportar al staff. Cada tema tiene preguntas propias con palabras sencillas. Soporte pregunta qué pasa y desde cuándo; reportes preguntan quién fue, qué pasó, cuándo y qué pruebas hay; tienda pregunta por la compra y qué salió mal; Donaciones pregunta qué tipo de donación quieres hacer, qué quieres donar, cuánto y cómo; apelaciones preguntan por el castigo y qué pasó; Gangas pregunta el nombre, qué haces ahí y qué necesitas. Los reportes permiten añadir el ID de Discord de la persona, si se conoce. Los adjuntos se envían dentro del caso. La tienda permite vincular únicamente compras propias (como pagador o destinatario).

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

Botones del ticket abierto: Reclamar, Resolver, Cerrar y Prioridad. Tras cerrar: Valorar (solo para el autor) y Eliminar ticket (solo staff autorizado). Los mensajes antiguos se actualizan y se retiran sus botones sobrantes. El resto de herramientas del staff se usan por comandos.

Valorar abre un formulario con una selección de 1 a 5 estrellas y un comentario opcional. No hace falta escribir una puntuación ni usar un formato especial. Solo el jugador que abrió el ticket puede enviar una opinión, una sola vez y mientras el ticket siga cerrado y no eliminado. La autorización se comprueba de nuevo al enviar el formulario.

Comandos principales:

- `/ticket mis`, `/ticket cerrados` y `/ticket gestion`: listas paginadas. La consulta de cerrados está únicamente en la categoría Tickets Cerrados y en `/ticket cerrados`. El panel de entrada no incluye ese botón. Las listas excluyen todos los casos de prueba y eliminados y comprueban que exista el canal; la lista de cerrados solo admite estado cerrado. Los datos reservados se filtran antes de calcular estadísticas.
- `/ticket buscar jugador:@nombre pagina:1`: historial privado para el staff, con cinco casos por página, asunto, estado, responsable, quién atendió cuando está registrado y solución. Incluye abiertos y cerrados que conservan su canal. Cada caso se filtra por la autorización actual del revisor antes de contar o paginar; se excluyen eliminados, ausentes, de prueba y creaciones incompletas. Un encargado de un departamento solo ve los casos que puede atender; los reportes contra staff siguen reservados a administradores. Elegir un caso vuelve a comprobar acceso y existencia. Los resúmenes largos se recortan y el caso conserva el detalle completo. Consultar la lista no cambia permisos.
- `/ticket acceso`, `/ticket estado`, `/ticket transferir`, `/ticket participante`.
- `/ticket nota`, `/ticket notas`, `/ticket historial`.
- `/ticket transcripcion` y `/ticket archivo` descargan copias privadas tras verificar de nuevo la autorización.
- `/ticket compra` consulta la compra vinculada; `/ticket devolver` exige autorización de economía, un motivo y una confirmación. Usa las transacciones idempotentes de la tienda, sin cobros ni devoluciones al abrir un caso.
- `/ticket configuracion`: límites y tiempos; requiere Administrador.
- `/ticket departamento`: añadir/quitar roles encargados en departamentos normales. No acepta roles protegidos, Ciudadanos, @everyone ni roles de bots. Los roles habituales de staff mantienen su acceso.
- `/ticket recuperar`: concilia creaciones y archivos interrumpidos. Recupera el canal existente o reintenta una reserva sin canal después de revisar una lista completa y esperar la reserva temporal de tres minutos. `cancelar_reserva:true` permite cancelar únicamente una reserva sin canal y sin creación en curso, conservando sus datos.

Estados: Nuevo → En atención → Esperando al jugador → Resuelto → Cerrado. Cada actuación conserva actor, fecha y motivo. Prioridades: normal, alta o urgente, con justificación.

El botón **Prioridad** conserva el formulario actual. Al cambiar a **urgente**, se guarda primero la prioridad y su motivo y se avisa inmediatamente a los mismos encargados del aviso de 24 horas dentro del ticket privado. En reportes contra staff solo se menciona a roles con Administrador de Discord. Repetir urgente no vuelve a avisar; bajar la prioridad y volver a subirla inicia otro aviso. La entrega se guarda en SQLite para no duplicarla después de reiniciar. Si Discord falla, el mantenimiento puede reintentar después de 15 minutos mientras el caso siga abierto y urgente. No se envía otro aviso de 24 horas durante los 15 minutos posteriores a una alerta urgente entregada; después continúa el seguimiento pendiente. No hay nuevos botones dentro del ticket.

Avisos: recordatorio tras 6 horas pendientes. Los casos esperando al jugador reciben advertencia después de 72 horas y se archivan tras otras 24 horas sin respuesta. Responder cancela el cierre pendiente. Los resueltos no se cierran automáticamente sin aviso. No se usa @everyone; la apertura avisa a los roles encargados dentro del canal privado, y los recordatorios se limitan al autor o responsable.

Después de **24 horas esperando una respuesta del staff**, el bot avisa al Jefe de Staff dentro del mismo ticket privado. Si ese rango no existe o no tiene acceso, avisa a roles con Administrador de Discord. En reportes contra staff solo se menciona a roles humanos que tengan Administrador; nunca a Soporte, Moderador ni al jefe por su nombre de rango. Reclamar sin responder y los mensajes de seguimiento del jugador no retrasan el aviso. Se envía una vez por período de espera; una respuesta del staff termina ese período. No se aplica a casos resueltos, cerrados, eliminados, de prueba o que esperan al jugador. Un canal ausente o un aviso fallido no interrumpen los demás casos.

Si se abre entre **12:00 a. m. y 8:00 a. m., hora de Puerto Rico**, se confirma en el ticket y en la respuesta privada: «Recibimos tu ticket, bro. El equipo te responde cuando esté disponible». Es un aviso de recepción, no una promesa de horario ni de respuesta inmediata.

El jugador recibe un privado al reclamar su ticket y otro cuando el staff le responde, con un enlace al canal o mensaje real del caso. Las respuestas se agrupan por turno del jugador y hay al menos 15 minutos entre avisos de respuesta y el aviso de reclamación. Si una respuesta llega durante ese intervalo, el mantenimiento puede avisar después si el jugador todavía no ha contestado. Las ediciones no generan avisos nuevos. Los intentos se conservan en SQLite para no duplicarlos tras reiniciar; un fallo temporal se puede reintentar después de 15 minutos y los privados bloqueados no detienen la atención. Los casos internos de prueba y los canales eliminados no generan estos privados.

## Archivo y recuperación

Se crea `│・ 🔒┊ 𝐓𝐢𝐜𝐤𝐞𝐭𝐬 𝐂𝐞𝐫𝐫𝐚𝐝𝐨𝐬`, junto a Tickets. La categoría incluye un índice privado Archivo-Tickets, visible para los rangos autorizados, que permite consultar los casos y mantiene la categoría visible aunque no queden canales de casos. El bot mueve el mismo canal y conserva su historial, con escritura desactivada para participantes habituales. Si una categoría llega a su capacidad, crea otra privada con sufijo, sin mover tickets anteriores. No hay eliminación automática. Después del cierre aparece **Eliminar ticket**, solo para staff autorizado y con confirmación. Antes de borrar el canal se exige una transcripción completa, integridad de las pruebas y un respaldo verificado (Drive cuando está habilitado). Si falla, el canal se conserva. El registro y las pruebas se conservan en el respaldo interno; los tickets eliminados no aparecen en las listas y no pueden reabrirse.

Mensajes y sus ediciones/eliminaciones se conservan en tablas SQLite. Los adjuntos se guardan como datos binarios con SHA-256, por lo que los respaldos completos existentes (incluido Drive) contienen también las pruebas, no solo enlaces caducables. Límites iniciales: 25 MB por archivo, 100 MB por caso y 500 MB en total; se reserva espacio para respaldos. Si falla una copia o excede el límite, se avisa y el archivo figura como no respaldado. Los enlaces externos son referencias, no copias de archivos.

El HTML de transcripción escapa el contenido de usuarios y excluye notas internas. Los archivos grandes se entregan por partes privadas con `/ticket archivo`. Los estados parciales se muestran explícitamente; los cierres interrumpidos se reconcilian al reiniciar.

Las acciones de tickets tienen su propio historial. Las creaciones, movimientos y cambios de accesos guardan además copias antes/después en `/cambios`, utilizando solo el caso afectado cuando corresponde.

## Migración y reversión

El nuevo panel se publica y fija en el canal indicado. Los paneles y casos de otros bots no se eliminan ni se modifican: los casos anteriores deben cerrarse desde sus controles originales. Este bot solo administra canales con sus propios registros y la marca `lv-ticket:<número>`.

Para pausar, poner `TICKETS_ENABLED=0` en Railway; se conserva toda la información. Para volver al código anterior desplegar `67b4dcce78d5dbfdd1cce876b31859776d6f0db8`, conservando `/data` y SQLite. No restaurar una base vieja sobre la actual: se perderían actuaciones nuevas. Conservar los canales ya creados y sus IDs. No modificar los cuatro roles protegidos para recuperar tickets.

`TICKETS_INSTALL_REQUEST_ID` identifica la instalación en el registro. `TICKETS_SELFTEST_REQUEST_ID` activa una única verificación privada con dos casos del bot, excluidos de las estadísticas de atención. Verifica privacidad, notas, respaldo real de adjuntos, cierre, reapertura, transferencia y una copia/restauración en Drive si los respaldos automáticos están habilitados. Quitar estas dos variables tras verificar; mantener `TICKETS_ENABLED=1`.


## Canales nuevos de Discord y reservas de creación

La creación, las listas y la recuperación usan `discord_channels.fetch_channels`. Si la librería rechaza un tipo nuevo (por ejemplo, 20), se vuelven a leer los datos del servidor: los canales conocidos siguen usando sus constructores normales y los desconocidos se conservan como metadatos de solo lectura. Se mantienen ID, categoría, posición y permisos en las copias antes/después; no se cambian, reclasifican ni eliminan estos canales. Otros errores de red o datos siguen siendo errores.

Las reservas en estado creando sin canal se reintentan automáticamente conservando el mismo número, autor y formulario. Antes de crear se comprueba que no exista ya un canal con el topic del ticket. Una coincidencia de tipo desconocido requiere revisión y nunca genera un duplicado. La creación inicial y la recuperación comparten una reserva de tres minutos guardada en SQLite (`creation-lease:*`) para no solaparse ni repetir una petición cuyo resultado todavía sea incierto. Si el autor ya no está en el servidor, la reserva se conserva sin crear un canal sin su acceso.

`/ticket recuperar numero:8` permite reintentar la creación. `cancelar_reserva:true` solo reconcilia y cancela una reserva sin canal después de las comprobaciones; no crea un canal al pedir cancelarla ni cancela una creación en curso. Se siguen protegiendo los casos reservados y los roles protegidos.
