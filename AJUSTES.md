# Centro de ajustes

Abre **`/ajustes panel`** en La Venganza RP, fuera del canal exclusivo de perfiles.
Es una aplicación dentro de Discord: menú por sistemas, valores actuales, botones
para abrir formularios y enlaces a los canales correspondientes. No necesita una web.
La respuesta es privada y solo puede manejarla el administrador que la abrió.

## Cómo cambiar un ajuste

1. Elige un sistema en el menú.
2. Abre su formulario. Los campos muestran los valores que ya estás usando.
3. Envía el formulario para revisar el **antes y después**.
4. Pulsa **Guardar cambios** o **Cancelar**.

Abrir el panel, navegar o enviar un formulario no guarda nada por sí solo. Antes de
guardar, el bot vuelve a consultar en Discord que conservas Administrador. Si alguien
cambió esos valores mientras tenías abierto el formulario, pide revisarlos otra vez.
Una confirmación repetida usa el mismo recibo y no vuelve a aplicar la operación.

El menú tiene 16 secciones y 22 formularios, contando los tres ajustes originales y
el editor de productos:

| Sección | Qué puedes ajustar o consultar |
| --- | --- |
| Servidor y avisos | Hora, título, cuerpo y pie del Server Up; activar el aviso diario y las menciones a todos en avisos, mantenimiento y Server Up. |
| Tickets | Casos abiertos por jugador, recordatorios, aviso al encargado, espera al jugador, horario de madrugada, mensajes privados y límites para guardar pruebas. |
| Tienda y monedas | Precio y disponibilidad de cada producto; premios de eventos. Acceso a los comandos de economía y perfil. |
| Fotos | Premios del podio desde esta semana o la próxima; recibir fotos nuevas y límite semanal por jugador. |
| Minijuegos | Tiempo entre respuestas y modos disponibles. El premio sigue siendo 25 monedas por acierto. |
| Feedback | Permitir valoraciones fuera de tickets y tiempo entre ellas. |
| Sugerencias | Recibir ideas, tiempo entre propuestas y permitir votos. |
| Reportes de errores | Recibir reportes, máximo pendiente por jugador y tiempo entre reportes. |
| Solicitudes de staff | Abrir postulaciones, tiempo entre solicitudes y aviso de entrevista. |
| Creadores y directos | Seguidores mínimos para verificaciones nuevas y avisos de directos. |
| Eventos | Elegir recordatorios; acceso a los comandos de gestión. |
| Reuniones | Elegir recordatorios y activarlos para staff o comunidad. |
| Seguridad | Filtro de palabras, palabras adicionales y detección de enlaces repetidos entre canales. |
| Normas y guía | Canal oficial de normas, frecuencia de actualización del índice, título y bienvenida de la guía. |
| Respaldos | Activar copias automáticas y su horario con la conexión ya configurada; consultar su estado. |
| Historial y diagnóstico | Tareas del bot, cambios guardados, antes y después y restauración con confirmación. |

**`/ajustes funciones buscar:…`** permite buscar por nombre o descripción entre los
comandos que Discord tiene registrados. Desde cada sección también puedes abrir sus
funciones y pulsar el nombre del comando para usarlo. Cada comando conserva sus permisos.

## Valores y límites

Las horas son de **Puerto Rico**. El Server Up acepta `18:30` o `6:30 p. m.`. Guardar
su horario no envía un aviso de prueba ni repite uno ya revisado ese día. Si la hora
ya pasó, espera al siguiente día. Conserva la comprobación de servidor arriba y de
mantenimiento, el banner animado y el enlace de conexión.

Los textos del Server Up admiten `{enlace}`, `{servidor}` y `{hora}`; el cuerpo debe
conservar `{enlace}`. La vista previa no menciona a nadie. Los premios de Fotos
siguen siendo enteros de 1 a 1.000.000, de mayor a menor o iguales. No se cambian
semanas cerradas ni premios ya pagados. Cero fotos por semana significa sin límite.

Cambiar precios solo afecta compras nuevas. Conserva saldos, compras pagadas,
inventarios, stock, entregas pendientes y contenido de productos. Las pruebas de
reportes siguen siendo obligatorias y conservan el límite de **diez archivos de
120 MB cada uno**. Ese dato aparece como información, no como un límite editable
que Discord pueda ignorar. Los límites de respaldo de tickets se configuran por
separado; no pueden quedar por debajo de las pruebas ya guardadas.

Pausar nuevas fotos, ideas, reportes o postulaciones conserva lo recibido. Los
borradores admitidos pueden terminarse. Pausar un modo de minijuego conserva la
pregunta ya empezada. Los reportes contra staff mantienen su acceso reservado.
La aceptación de solicitudes sigue dejando la asignación de roles a administración.

El filtro mantiene su lista base, palabras manuales y exenciones. Solo administra
sus palabras adicionales y su estado de activación. El canal de normas necesita
ser un canal de texto del servidor que el bot pueda leer; el buscador comprueba
también los permisos de cada jugador antes de mostrar información.

El panel no muestra claves ni contraseñas. Para activar respaldos automáticos debe
existir una conexión válida de Drive en Railway. Cambiar el horario no configura
esa conexión. No se ofrecen controles para cambiar roles o permisos protegidos.

## Historial y recuperación

**`/ajustes historial`** muestra fecha, autor y estado de cada cambio. Abre uno para
revisar sus valores y pulsa **Revisar restauración** si quieres recuperar el ajuste
anterior. El bot prepara otra vista previa con los valores actuales: todavía debes
confirmarla. Solo restaura ese formulario o ese precio y disponibilidad; no restaura
una base antigua ni modifica compras, saldos o premios ya pagados.

Los ajustes y recibos se guardan en el SQLite existente. `admin_settings_revision`
evita sobrescribir cambios antiguos; `bot_setting_ops` conserva autor y valores
antes y después. `bot_setting_jobs` guarda actualizaciones pendientes de Discord.
Las copias completas de SQLite incluyen estos datos.

Si Discord falla después de guardar, el panel indica que su actualización está
pendiente. El bot la reintenta cada 30 segundos y después de reiniciar, usando la
configuración más reciente y sin guardar el mismo cambio de nuevo. Solo refresca
los paneles afectados. El registro privado `ADMIN_SETTINGS` usa `ChangeLog.tracked`;
los cambios no se anuncian en Registro Exclusive. La navegación principal expira
en 14 minutos; basta con abrir otro panel.

Para volver al código anterior, desplegar `1247aeeaaa085d8b0ea307c9e355df2fcd72ffd8`
y conservar el volumen y su SQLite actual. Revertir código no restaura valores:
usar primero el historial si hay que deshacerlos. La versión anterior ignora las
claves nuevas y no procesa la cola nueva, pero conserva los precios, premios,
horarios y otras claves ya compatibles. Si se cambió el filtro nativo de Discord,
restaurar sus ajustes antes de revertir código. Conservar las tablas y archivos;
no borrar mensajes, tickets, roles ni permisos para revertir el panel.
