# Respaldos diarios de LA VENGANZA RP en Google Drive

El código está preparado, pero **no está activado ni probado contra tu cuenta real** hasta
configurar OAuth en Railway y completar una copia/prueba real. No cambia DB_PATH, no restaura
sobre la base activa y no elimina respaldos anteriores. No hay nuevas tablas ni migraciones.

## Qué hace

- A las **03:00 de Puerto Rico** crea una copia consistente con la API de SQLite.
- Comprueba integridad, calcula SHA-256 y guarda un manifiesto privado.
- La sube a Drive; confirma tamaño y checksum de la subida.
- Vuelve a descargarla desde Drive y verifica SHA-256 y tamaño originales.
- Restaura la descarga **en un archivo temporal nuevo**, compara esquema, integridad y conteos.
- Solo confirma éxito completo después de pasar esa recuperación aislada.
- Ante un fallo intenta un aviso sin pings en General Staff `1515887549678223380`.
  El aviso no adjunta la base ni muestra tokens, datos de jugadores o URLs privadas de sesión.
- Conserva la programación en `/data/backup-schedule.json` con DB_PATH en `/data`.
  Un reinicio no repite el intento diario. Tras varios días desconectado ejecuta solo el periodo
  pendiente más reciente, no una ráfaga de copias atrasadas.

La primera activación puede generar inmediatamente la copia del último horario vencido.
Un intento fallido o interrumpido no se reenvía a ciegas: se avisa y un administrador puede usar
`/respaldo crear` para un nuevo intento. `/respaldo probar` permite verificar una copia subida
sin volver a subirla. El próximo horario diario vuelve a intentarlo normalmente.

## Tu caso: Drive personal de Gmail

Usa **OAuth de usuario con refresh token**. No necesitas una cuenta de servicio. Las cuentas
 de servicio no disponen de cuota propia para guardar estas copias en un My Drive personal.
La conexión de Drive en ChatGPT no transfiere sus credenciales a un proceso en Railway.
La autorización del bot debe configurarse por separado, sin compartir tokens por chat.

### 1. Crear un cliente OAuth propio en Google

Desde Safari puedes solicitar la versión de escritorio si se ocultan opciones.

1. Abre [Google Cloud Console](https://console.cloud.google.com/) con tu Gmail y selecciona
   o crea un proyecto, por ejemplo `La Venganza RP Backups`.
2. En APIs y servicios → Biblioteca, habilita **Google Drive API**.
3. En **Google Auth Platform**, configura Branding/Audience (pantalla de consentimiento):
   nombre de aplicación, correo de soporte y audiencia externa para tu Gmail personal.
4. Declara únicamente el permiso `https://www.googleapis.com/auth/drive.file`.
   Permite trabajar con archivos creados o autorizados para esta aplicación, sin pedir acceso
   completo a todos tus archivos de Drive.
5. Crea un **cliente OAuth de tipo Aplicación web**. Añade exactamente esta URI de redirección:
   `https://developers.google.com/oauthplayground`.
6. Conserva el Client ID y Client Secret de ese cliente en un lugar privado.

Si la aplicación queda en modo **Testing/Prueba**, Google puede hacer expirar el refresh token
 a los siete días para estos permisos. Para un servicio continuo revisa la opción de publicación
 a producción y cumple los requisitos que indique Google. No confíes en un token de prueba como
 autenticación permanente: un token revocado/expirado producirá avisos de fallo.

### 2. Obtener la autorización en la herramienta oficial de Google

1. Abre [OAuth 2.0 Playground](https://developers.google.com/oauthplayground/).
2. En el engranaje activa **Use your own OAuth credentials** e introduce el Client ID y Client
   Secret anteriores. Es importante usar tu propio cliente, no el predeterminado del Playground.
3. Selecciona acceso **Offline** y, si aparece, consentimiento forzado para obtener refresh token.
4. En Step 1 introduce el permiso `https://www.googleapis.com/auth/drive.file` y pulsa Authorize APIs.
5. Autoriza tu Gmail para la aplicación que acabas de crear.
6. En Step 2 pulsa Exchange authorization code for tokens y conserva el **refresh_token**.
   Un access_token por sí solo caduca y no permite mantener el bot funcionando diariamente.

Los nombres de menús pueden cambiar. Si Google exige pasos adicionales de consentimiento,
complétalos en Google. No envíes capturas con Client Secret, refresh token ni access token visibles.

### 3. Guardar la configuración privada en Railway

En el servicio del bot, entorno production → Variables, añade:

```text
AUTO_BACKUP_ENABLED=0
BACKUP_TIME_PR=03:00
```

Añade **GOOGLE_DRIVE_CREDENTIALS_JSON** como variable privada. Su valor es un JSON con tus datos
reales, que solo debes introducir dentro del campo Value de Railway:

```json
{
  "type": "authorized_user",
  "client_id": "TU_CLIENT_ID.apps.googleusercontent.com",
  "client_secret": "TU_CLIENT_SECRET",
  "refresh_token": "TU_REFRESH_TOKEN",
  "token_uri": "https://oauth2.googleapis.com/token"
}
```

No pegues ese JSON en GitHub, Discord ni en el asistente de Railway/ChatGPT.
No cambies DISCORD_BOT_TOKEN, DISCORD_WEBHOOK_URL ni DB_PATH.
Mantén `DB_PATH=/data/lavenganza.sqlite3` y el volumen actual adjunto.
Aplica los cambios de Railway.

Deja **GOOGLE_DRIVE_BACKUP_FOLDER_ID** sin configurar al principio. El primer respaldo crea
una carpeta privada **LA VENGANZA RP - Respaldos** en el Drive de la identidad OAuth y guarda
su ID para reutilizarla. No comparte esa carpeta ni crea enlaces públicos. Si configuras una
carpeta existente, debe estar autorizada para esta misma aplicación; un ID por sí solo no
concede permisos con el alcance drive.file.

### 4. Ejecutar una prueba real antes de activar el horario

1. En Discord, con un rango de administración del bot, ejecuta **`/respaldo crear`**.
2. El bot responde de forma privada que empezó y después confirma el resultado. Espera:
   la operación trabaja en segundo plano y no bloquea los eventos/reuniones.
3. Revisa **`/estado-bot`**: Drive debe figurar verificado y recuperación verificada.
4. Abre tu Drive y comprueba que la carpeta contiene el archivo `.sqlite3`.
5. Ejecuta **`/respaldo probar`**: debe volver a descargar y recuperar la copia de Drive en un
   archivo temporal. No modifica ni reemplaza la base que usa el bot.
6. Solo después cambia **`AUTO_BACKUP_ENABLED=1`** en Railway y aplica los cambios.
7. Comprueba `/estado-bot`: diario activado, horario PR y tarea diaria activa.

Si falla, no borres la base, los archivos ni el volumen. Revisa la etapa indicada, corrige
la autenticación/permisos/espacio y vuelve a `/respaldo crear`. Las copias locales y subidas
anteriores se conservan aunque una nueva prueba falle.

## Comandos y permisos

- `/respaldo crear`: copia local, subida y prueba de recuperación real desde Drive.
- `/respaldo probar`: descarga de la copia de Drive registrada más reciente y prueba aislada.
- `/estado-bot`: diagnóstico privado de programación, operación, copia y recuperación.

Solo los rangos de administración del bot en el servidor original pueden ejecutar estos comandos. No se entregan
los archivos de SQLite a Discord. Las notificaciones de fallo van al canal Staff indicado.
Si Discord no permite enviar el aviso o la entrega es incierta, se registra el fallo en logs;
consulta `/estado-bot`. No se reenvían avisos inciertos repetidamente. Si el almacenamiento
impide guardar la constancia del aviso, se intenta una sola entrega en ese proceso; un reinicio
no puede garantizar la deduplicación de un aviso cuya constancia no se pudo persistir.

## Variables adicionales opcionales

| Variable | Valor predeterminado / función |
| --- | --- |
| `AUTO_BACKUP_ENABLED` | `0`; `1` activa la tarea diaria |
| `BACKUP_TIME_PR` | `03:00`; hora y minuto de Puerto Rico |
| `GOOGLE_DRIVE_CREDENTIALS_JSON` | JSON privado OAuth; alternativamente se admite ADC con archivo secreto |
| `GOOGLE_APPLICATION_CREDENTIALS` | Ruta de archivo secreto ADC, si no usas el JSON de entorno |
| `GOOGLE_DRIVE_BACKUP_FOLDER_ID` | Vacío: crea carpeta propia; si se indica, verifica permiso para añadir archivos |
| `BACKUP_ALERT_CHANNEL_ID` | `1515887549678223380`, General Staff |
| `BACKUP_DIR` | `backups` junto a la base: `/data/backups` con tu configuración |
| `BACKUP_STATE_PATH` | `backup-schedule.json` junto a SQLite |
| `BACKUP_STATUS_PATH` | `backup-status.json` junto a SQLite |

Las rutas deben ser absolutas. Ningún archivo de estado puede ser el archivo de SQLite;
los dos archivos de estado tampoco deben coincidir. El registro diario valida que corresponda
 a la misma base. Si cambias la ruta de SQLite en el futuro, revisa primero la migración y usa
 un registro de programación nuevo, sin sobrescribir el registro anterior.

Se instala google-auth con requests mediante requirements.txt. Los secretos no se escriben
 a disco cuando se usa GOOGLE_DRIVE_CREDENTIALS_JSON. No se incorporan a logs, manifiestos ni Git.

## Qué significa la prueba y qué falta verificar

La recuperación prueba la copia **descargada de Drive**, no solo una copia que siga en Railway.
Comprueba contenido descargado mediante SHA-256 y tamaño, integridad SQLite, restauración a
otro archivo, esquema y conteos de todas las tablas de usuario. No cambia registros en vivo.
Las inscripciones posteriores a la hora de la copia pertenecen al siguiente respaldo.

No hay borrado automático de copias locales ni de Drive. Revisa periódicamente la cuota del
volumen y de tu Gmail. Se comprueba espacio antes de crear una copia y se limita la espera de
SQLite para evitar que una operación quede abierta indefinidamente. Mantén una sola réplica del bot.
Un proceso interrumpido puede haber subido un archivo sin confirmar el resultado; se conserva
la copia, se avisa al reconectar y no se intenta duplicarla automáticamente.

En esta entrega las pruebas locales usan una base SQLite real y un Drive simulado. La autorización,
la carpeta real, el envío de avisos a Discord y el ciclo contra tu Drive solo se pueden confirmar
cuando completes la configuración privada y las pruebas del apartado 4.
