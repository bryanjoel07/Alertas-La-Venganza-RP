# LA VENGANZA RP | ALERTAS

Bot existente ampliado sin reemplazar los sistemas de alertas, mantenimiento ni eventos.
Zona horaria: `America/Puerto_Rico`. Datos: SQLite. Entrada: `python bot.py`.

## Estado de esta entrega

Cambios probados fuera de producción y preparados para publicar en GitHub con autorización.
La publicación en main puede activar Railway. No se ha ejecutado una migración ni una subida a Drive;
el estado real del despliegue y de la base debe comprobarse por separado.
Lee [AUDITORIA.md](AUDITORIA.md) y [DESPLIEGUE_IPHONE.md](DESPLIEGUE_IPHONE.md) antes de desplegar.

## Archivos

- `bot.py`: conserva comandos y tablas originales; conecta el módulo de reuniones, protege formularios y corrige contadores al editar.
- `meetings.py`: reuniones, permisos, confirmaciones, asistencia y recordatorios.
- `storage.py`: selección de base con protección contra arranque vacío o ambiguo.
- `backup.py`: copia consistente de SQLite, integridad, manifiesto SHA-256 y subida opcional a Drive.
- `requirements.txt`: discord.py 2.7.1 o superior para el selector de voz dentro del formulario.
- `requirements-backup.txt`: dependencia opcional para Google Drive.
- `railway.json`: configuración original sin cambios (Railpack, `python bot.py`, diez reintentos ante fallos).
- `tests/test_bot.py`: pruebas locales sin credenciales reales.
- `.gitignore`: excluye secretos, bases, respaldos y archivos temporales.

## Comandos

| Comando | Función | Acceso |
| --- | --- | --- |
| `/testalert` | DOWN o RESTORED claramente identificado como simulación | Administrador Discord |
| `/simular-ciclo` | Prueba del ciclo y dos alertas simuladas, sin registrar caídas | Administrador Discord |
| `/historial-caidas` | Últimas diez caídas, estado, duración e ID | Administrador Discord |
| `/mantenimiento iniciar` | Motivo, anuncio, registro y suspensión del monitor | Administrador Discord |
| `/mantenimiento finalizar` | Anuncio, lectura del panel y reactivación | Administrador Discord |
| `/evento crear` | Formulario en dos pasos, banner opcional en el segundo, vista previa y publicación explícita | Administrador Discord |
| `/evento editar` | Nombre, fecha, hora, lugar y descripción; conserva inscritos | Administrador Discord |
| `/evento premios` | Tres premios y cupos; no reduce por debajo de los inscritos | Administrador Discord |
| `/evento banner` | Cambia imagen del anuncio | Administrador Discord |
| `/evento participantes` | Lista de inscritos (con límite de texto original) | Administrador Discord |
| `/evento finalizar` | Tres miembros diferentes, podio y cierre de inscripciones | Administrador Discord |
| `/evento cerrar` | Elimina anuncio, banner y botones; conserva datos | Administrador Discord |
| `/reunion crear tipo` | Staff o General, formulario y publicación al enviarlo | Roles autorizados |
| `/reunion editar reunion_id` | Cambia datos sin perder confirmaciones ni asistencia | Roles autorizados |
| `/reunion cancelar reunion_id` | Conserva anuncio y registros; bloquea confirmaciones | Roles autorizados |
| `/reunion asistencia reunion_id` | Listas por respuesta y asistencia real, archivo si es extensa | Roles autorizados |
| `/reunion presente reunion_id miembro asistio` | Registra presencia real o corrige a ausente | Roles autorizados |
| `/reunion finalizar reunion_id` | Cierra confirmaciones y registro de presencia; conserva datos | Roles autorizados |

Roles autorizados de reuniones: Owner `1245008186440683530`, Super Admin `1245010156576833536`,
Admin `1300619682486947931`, Programador `1300627506801541230`.
Se exige también acceso al canal correspondiente. No se concede acceso a reuniones privadas
por tener permiso Administrador fuera de estos roles.

Canales: Staff `1515887549678223380`; General `1513422089162330184`.
Los usuarios con acceso al canal pueden elegir Asistiré, No asistiré o Tal vez y modificarlo.
Cada usuario conserva una sola respuesta por reunión. La asistencia real se almacena aparte,
con quién la registró y cuándo. No es necesario haber confirmado para registrar presencia real.
Los informes usan IDs de Discord para evitar errores con nombres duplicados.

Discord admite cinco campos de texto por formulario: tipo se elige en el comando y fecha/hora
se escriben juntas (`2026-12-20 19:30`, hora PR, formato de 24 horas).
El campo Canal de voz permite elegir un único canal de voz o escenario del servidor y valida acceso y conexión
al enviar. El anuncio muestra el enlace al canal elegido. En nuevas reuniones Staff se preselecciona
`1515887667298963579`, después de verificar que sea voz/escenario y que tu usuario tenga acceso
y permiso de conexión. Los permisos del bot no sustituyen los permisos del usuario. Los lugares de reuniones anteriores
se conservan; al editarlas se debe elegir un canal si antes tenían un lugar escrito.
La creación de reunión se confirma al enviar el formulario; eventos mantienen su vista previa.

### Crear un evento con imagen sin retrasar la apertura

Ejecuta `/evento crear` sin adjuntar archivos al comando. Completa los datos principales y pulsa
Premios y cupos. El segundo formulario incluye un selector de archivo opcional para el banner
(PNG, JPG, WEBP o GIF, hasta 8 MB). Al enviarlo se confirma la interacción antes de descargar
el archivo o subir la vista previa. La descarga tiene un límite de 15 segundos y, si falla,
el borrador se conserva para reintentar. Revisa el banner y pulsa Publicar evento para enviarlo
al canal oficial. El comando ya no tiene el parámetro `imagen`: el archivo se elige dentro del
formulario, para que Discord no tenga que terminar su subida antes de enviar el comando inicial.
La velocidad de subida sigue dependiendo de la conexión del usuario y de Discord.


## Variables de entorno

| Variable | Uso |
| --- | --- |
| `DISCORD_BOT_TOKEN` | Obligatoria; token del bot, solo en Railway |
| `DISCORD_WEBHOOK_URL` | Obligatoria; webhook privado de alertas, solo en Railway |
| `DB_PATH` | Ruta absoluta explícita de la base existente; recomendada tras verificar la ruta activa |
| `DATA_DIR` | Compatibilidad anterior si no hay `DB_PATH` |
| `RAILWAY_VOLUME_MOUNT_PATH` | Variable de Railway, último directorio alternativo antes de `/tmp` |
| `ALLOW_EMPTY_DB` | `0` por defecto. `1` solo para instalar una base nueva o pruebas; nunca como solución a datos desaparecidos |
| `GOOGLE_APPLICATION_CREDENTIALS` | Solo para respaldos Drive: ruta de archivo secreto OAuth o identidad de servicio compatible con ADC |

`DB_PATH` tiene prioridad. Se conserva la elección anterior de directorio, pero un destino inexistente
ahora detiene el arranque. Si hay dos bases posibles en `/tmp` y el directorio seleccionado,
se exige elegir explícitamente después de verificarlas. No hay traslado automático.
No cambies estas variables ni montes el volumen en producción sin completar el procedimiento.

## Recordatorios y persistencia

El arranque agrega únicamente `meetings`, `meeting_responses`, `meeting_attendance`,
`meeting_reminders` y un índice. No borra ni altera tablas anteriores.
Los recordatorios se revisan cada 30 segundos: 24 horas, 1 hora y 15 minutos antes.
Si se cruzaron varios umbrales durante la desconexión, solo se reserva el más reciente.
No se recuperan avisos anteriores a la creación ni posteriores al inicio de la reunión.
Editar fecha/hora reprograma recordatorios para la nueva fecha; puede enviar nuevos avisos
para esa nueva programación. Editar otros datos conserva los avisos ya registrados.

La reserva es transaccional y persiste antes del envío para evitar duplicados. Si el envío falla
o el proceso se interrumpe, puede perderse ese recordatorio: no se reintenta automáticamente
una entrega incierta. Los estados `claimed`, `sent`, `failed`, `skipped` permiten auditarlo.
No ejecutar dos réplicas del bot: las alertas y operaciones originales usan bloqueo de un proceso.

## Respaldos

Ejemplo, **solo después de verificar origen y autorizar la operación en producción**:

```sh
python backup.py --source /RUTA/ACTIVA/lavenganza.sqlite3 --output /RUTA/RESPALDOS/copia-FECHA.db
```

Usa `sqlite3.Connection.backup`, verifica integridad y crea un manifiesto con SHA-256 y conteos.
No sobrescribe destinos. No restaura ni borra respaldos. Respalda también el manifiesto.
Una copia en `/tmp` o en el mismo volumen NO es protección externa.
El script es manual: no hay un respaldo automático activado silenciosamente.
Para automatizarlo, un operador debe programar su ejecución en un entorno con acceso a la base
y a almacenamiento externo, definir frecuencia y revisar fallos. No asumir que otro servicio
Railway puede montar simultáneamente el mismo volumen. Recomendación: diario y antes de cambios.

Para Drive instala además `pip install -r requirements-backup.txt` y ejecuta:

```sh
python backup.py --source /RUTA/ACTIVA/lavenganza.sqlite3 --output /RUTA/RESPALDOS/copia-FECHA.db --drive-folder ID_CARPETA
```

Autenticación: ADC con credenciales OAuth de usuario con refresh token o identidad de servicio.
Usa una cuenta dedicada y el alcance `drive.file`; la carpeta destino debe ser accesible a la
identidad y aplicación. Una cuenta de servicio requiere un Shared Drive con permisos adecuados;
no asumas que puede almacenar archivos en My Drive usando su cuota propia. Si tu cuenta personal
no tiene Shared Drive, usa OAuth de usuario. La autorización inicial debe realizarse fuera del bot.
Monta el JSON como secreto fuera del repositorio y configura su ruta mediante la variable anterior.
No pegues JSON, refresh tokens ni claves en GitHub. Se valida tamaño y checksum devueltos por Drive.
Si falla la subida, se conserva la copia local y el proceso devuelve error; todavía no está protegida.

## Pruebas locales

Python 3.12 usado en la validación; Python 3.9+ es necesario por `zoneinfo`; discord.py debe ser 2.7.1 o superior.

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m py_compile bot.py meetings.py storage.py backup.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/pip check
```

No requiere tokens reales. Las pruebas usan bases temporales e interacciones simuladas,
no llaman Discord, Google Drive ni Railway. PyNaCl y davey no son necesarios: este bot no conecta audio.

En Discord Developer Portal debe estar habilitado Message Content Intent, ya usado por el bot.
El bot necesita Ver canal, Leer historial, Enviar mensajes, Insertar enlaces y Adjuntar archivos
en los canales correspondientes. Se conserva sincronización exclusiva del servidor original.
