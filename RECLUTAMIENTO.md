# Solicitudes de staff

El panel vive en **Aplicar Staff**. Usa los canales ya existentes de Reclutamiento Staff; no crea categorías ni borra canales. Las respuestas solo se publican en **Solicitudes Staff**, que sigue siendo privado.

## Jugadores

- **Solicitar STAFF** abre dos formularios: nombre en el servidor, edad, horario, experiencia, motivo y preguntas sobre las reglas y cómo ayudarían a los jugadores. No se piden contraseñas, documentos ni acceso al host de FiveM.
- El borrador se guarda después de cada formulario. **Mi solicitud** permite continuar, revisar, cambiar respuestas, enviar o retirar la solicitud. Los borradores no se muestran al staff.
- Solo se permite una solicitud activa por jugador. Doble clic o una confirmación antigua no duplica la solicitud ni la decisión.
- **Mi solicitud** muestra el estado, encargado, entrevista, mensajes y resultado. El jugador puede responder allí o desde los botones del aviso privado del bot.
- Si los privados están cerrados, el resultado sigue disponible en el panel. No se envía un aviso por cada mensaje del servidor.

## Equipo

Pueden revisar y decidir **Owner, Programador, Jefe de Staff, Súper Admin, Admin, Moderador y Soporte**, además de quienes tengan Administrador de Discord. Los IDs autorizados están en `tickets_store.ALL_STAFF`. La autorización se vuelve a consultar en Discord para cada operación; no basta con tener un botón antiguo. Nadie puede revisar su propia solicitud.

Cada solicitud tiene cuatro controles: **Ver solicitud**, **Me encargo**, **Entrevista** y **Decidir**. Al abrirla también se puede pedir información, enviar un mensaje y dejar una nota que solo ve el equipo. Las respuestas y notas se conservan en el historial privado.

- **Entrevista** permite agendar o cambiar la fecha y marcarla como realizada. Quien la agenda queda como entrevistador; fechas introducidas en hora de Puerto Rico. El bot publica la cita en Entrevistas Staff, avisa al candidato y recuerda la cita una hora antes.
- El candidato puede entrar a la Sala Entrevista desde una hora antes hasta dos horas después. Se guarda y restaura su permiso anterior al terminar, retirarse o decidir. Si alguien cambia manualmente ese permiso durante el proceso, el bot conserva el cambio y marca el caso para revisión interna.
- **Aceptar** requiere una entrevista marcada como realizada. Tanto aceptar como rechazar pide un mensaje para el candidato y confirmación. La decisión es final; una segunda confirmación queda invalidada.
- **La administración asigna el rol después de aceptar**, por elección del propietario. Este sistema no asigna ni modifica roles.

Comandos:

- `/staff solicitar`, `/staff mi_solicitud`.
- `/staff pendientes pagina:1`: solicitudes activas del equipo.
- `/staff historial jugador:...`: historial de un jugador.
- `/staff ver numero:...`: solicitud y respuestas; cada jugador solo consulta las suyas.
- `/staff abrir abierto:...`: administración puede abrir o pausar nuevas solicitudes con confirmación; las que ya llegaron siguen en revisión.

## Transferencia y recuperación

La revisión inicial encontró un panel de entrada y **cero solicitudes en Solicitudes Staff**. Los mensajes originales de Información Staff y Entrevistas Staff se conservan. Antes del cambio se respaldaron los mensajes y componentes en `lv_recruit_sources`, con su inventario en `lv_recruit_surveys`; los archivos disponibles se guardan en `lv_recruit_source_files`.

La transferencia primero publica y verifica los dos botones del nuevo panel. Solo después retira el mensaje exacto del panel anterior (`1567401986670858344`), tras comprobar que coincide con su respaldo y que no llegó una solicitud nueva al canal antiguo. No elimina ni expulsa otros bots. Si aparecen solicitudes del sistema anterior durante el cambio, la transferencia se detiene para conservarlas.

Los accesos nuevos se limitan a Jefe de Staff, Moderador y Soporte en los tres canales privados existentes. Se conservan todos los demás permisos y se verifica que los cuatro roles protegidos no cambien. Cada ajuste de acceso, sustitución del panel y decisión conserva antes/después mediante `ChangeLog.tracked`. No se publican avisos de cambios en Registro Exclusive.

SQLite guarda solicitudes, eventos, recibos de avisos y permisos temporales en `lv_recruit_*`. El respaldo completo del bot ya incluye estas tablas. Al reiniciar se recuperan borradores y controles, se reconcilian publicaciones por su identificador y no se repiten decisiones ni premios de otros sistemas.

Para revertir el código, desplegar `eb53eb5e623439325da6a752abe4ad6b97109efe` conservando la SQLite actual. **No restaurar una base antigua.** Esto detiene los nuevos controles de solicitudes; no reconstruye automáticamente el panel funcional de otro bot. Para volver al bot anterior hay que regenerar su panel desde la configuración de ese bot. El respaldo permite recuperar su texto, pero no sus credenciales ni su estado interno.

Antes de volver al código anterior, completar/restaurar los accesos temporales pendientes en `lv_recruit_voice`, comparando `before_json`, `after_json` y el permiso actual. Para deshacer permisos de revisores, usar solo los cambios de los tres roles no protegidos en el registro correspondiente. Conservar permisos manuales posteriores, roles protegidos, canales e historial.
