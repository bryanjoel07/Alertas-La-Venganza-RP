# Foto de la semana

Canal existente: `1513422142014754976`. El sistema no crea, mueve ni borra canales y no cambia permisos, roles ni mensajes originales. Las respuestas con votos y los destacados pertenecen al bot.

## Participación

- Las fotos subidas por personas reciben una respuesta del bot con miniatura, crédito, cierre y botones **❤️ Votar** y **↩️ Quitar voto**. Cada imagen de un álbum tiene su propia votación.
- Admite adjuntos JPG, PNG, WEBP, GIF y AVIF que Discord identifica como imágenes. No inscribe enlaces, archivos de texto, videos ni publicaciones de otros bots.
- Cada persona puede dar un voto por foto y retirarlo. Puede votar varias fotos de otros jugadores; no su propia foto ni desde otra cuenta de bot. Se comprueba acceso al canal y que la imagen original siga existiendo.
- La semana va del lunes a las 00:00 al siguiente lunes a las 00:00 en `America/Puerto_Rico`. El cierre corresponde al final del domingo. La base rechaza votos desde el instante del cierre aunque la actualización visual se retrase un ciclo.
- Al instalar se incluyen las fotos ya publicadas esta semana. Se retoma la lectura con un cursor y se recuperan publicaciones posteriores a una interrupción sin duplicar registros. Fotos de semanas anteriores a la instalación no se inscriben.
- Las imágenes retiradas o cuyo mensaje original desaparece dejan de competir. Los votos quedan en el registro interno. Un fallo temporal de permisos o de Discord no descalifica la imagen.

## Ganador

El bot elige la foto activa con más votos. En un empate, gana la publicada primero; se usa el ID del adjunto para ordenar imágenes del mismo segundo. Se exige al menos un voto. Si no hubo participantes, no publica un ganador vacío; si hubo fotos pero ninguna consiguió votos, anuncia que no hubo ganadora.

La publicación ganadora incluye la foto, el nombre de quien la subió, sus votos, la semana y un enlace al original. Cuando el tamaño permite subirla con la cuenta del bot, se conserva temporalmente una copia binaria en SQLite y se vuelve a subir al anunciarla; la copia temporal se libera tras confirmar el envío. Las imágenes mayores al límite de subida del bot se muestran mediante el adjunto original. La copia subida por el bot tiene su propio adjunto. Solo se menciona al ganador, sin @everyone.

El panel de instrucciones se mantiene sin fijar; el fijado inicial de ese panel se retira automáticamente. Solo se fija una publicación registrada como ganadora tras el cierre semanal. Se deja de fijar el destacado anterior del propio bot, conservando ambos mensajes. No se retiran fijados de jugadores ni de otros bots. Las operaciones de fijado guardan antes/después con `ChangeLog.tracked`. Un fallo al fijar no elimina la publicación ganadora.

Los registros de publicación y sus marcas permiten recuperar controles y anuncios enviados justo antes de un reinicio. Los cierres pendientes se retoman al volver a conectar. Los controles quedan desactivados al terminar su semana.

## Comandos y premios opcionales

- `/foto semana`: clasificación actual privada y hora del cierre.
- `/foto premio articulo:… semana:…`: los responsables que ya autoriza la economía pueden escoger un artículo activo de perfil o **Sin premio de tienda**. `semana` es opcional y usa el lunes de referencia, por ejemplo `2026-11-09`; por defecto es la actual. Exige confirmación y comprueba autorización otra vez al confirmar.

No hay premio de tienda hasta que un responsable lo elige. Al publicarse el ganador se añade el artículo a su inventario una sola vez, con precio cero, sin cobrar a nadie ni equiparlo. No se asignan roles como parte de entregar el premio. La entrega respeta el stock; si el ganador ya tiene ese artículo o no está disponible, queda pendiente para que administración elija otro. No se permite sustituir un premio ya entregado. Los productos que crean salas de voz no son premios de este sistema.

## Datos y reversión

Las tablas `lv_photo_config`, `lv_photo_weeks`, `lv_photo_entries`, `lv_photo_votes` y `lv_photo_actions` viven en el SQLite persistente existente. Los respaldos completos incluyen resultados, votos, premios y cualquier imagen que esté pendiente de publicación. No se promete que el respaldo contenga todas las fotos históricas del canal.

`PHOTO_CONTEST_ENABLED=0` pausa el sistema conservando registros y mensajes. Para revertir solo el cambio del panel sin fijar, desplegar `f75291817ac30d73bf66f3f7173924171921edf2`; esa versión vuelve a fijarlo. Para volver al código anterior a todo el concurso, desplegar `7394be7065f03292afa0e7b5b068d9968c6a16a4`. Conservar `/data`. No restaurar una base antigua: se perderían votos y movimientos nuevos. No borrar mensajes de Fotos ni modificar roles protegidos para revertir la función.
