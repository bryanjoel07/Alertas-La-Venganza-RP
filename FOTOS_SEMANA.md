# Foto de la semana

Canal existente: `1513422142014754976`. El sistema no crea, mueve ni borra canales y no cambia permisos, roles ni fotos originales de jugadores. Las publicaciones con imagen y votos y los destacados pertenecen al bot; el autor real figura en cada foto.

## Participación

- **📸 Subir foto** abre un formulario con selector de una imagen, texto opcional y **¿Quieres mencionar a alguien?** opcional. Se pueden elegir hasta cinco personas que pertenezcan al servidor y puedan ver Fotos. El bot publica imagen completa, autor, menciones elegidas, cierre y botones **❤️ Votar**, **↩️ Quitar voto** y **📸 Subir foto** en un único mensaje, sin responder a otra publicación. También existe `/foto subir`.
- Solo se avisa a las personas elegidas en ese campo al publicar. Dejarlo vacío no menciona a nadie. Las menciones de roles o @everyone escritas en el texto no generan avisos. Actualizar el contador o recuperar un envío ya publicado no vuelve a notificar.
- Admite adjuntos JPG, PNG, WEBP, GIF y AVIF que Discord identifica como imágenes. No inscribe enlaces, archivos de texto, videos ni publicaciones de otros bots.
- Cada persona puede dar un voto por foto y retirarlo. Puede votar varias fotos de otros jugadores; no su propia foto ni desde otra cuenta de bot. Se comprueba acceso al canal y que la imagen original siga existiendo.
- La semana va del lunes a las 00:00 al siguiente lunes a las 00:00 en `America/Puerto_Rico`. El cierre corresponde al final del domingo. La base rechaza votos desde el instante del cierre aunque la actualización visual se retrase un ciclo.
- Las fotos que ya estaban inscritas se convierten al formato completo conservando sus votos y las fotos originales. Solo después de verificar la nueva publicación se retira la tarjeta antigua del propio bot; su copia antes/después queda en `PHOTO_LEGACY_CONTROL`. Las fotos antiguas del canal no se copian en masa.
- Para participar se usa **Subir foto** o `/foto subir`. Las imágenes enviadas directamente al chat se conservan allí, sin respuestas automáticas de votación. Los permisos de escribir de Ciudadanos se mantienen.
- Las imágenes retiradas o cuyo mensaje original desaparece dejan de competir. Los votos quedan en el registro interno. Un fallo temporal de permisos o de Discord no descalifica la imagen.

## Ganador

El bot elige la foto activa con más votos. En un empate, gana la publicada primero; se usa el ID del adjunto para ordenar imágenes del mismo segundo. Se exige al menos un voto. Si no hubo participantes, no publica un ganador vacío; si hubo fotos pero ninguna consiguió votos, anuncia que no hubo ganadora.

La publicación ganadora incluye la foto, el nombre de quien la subió, sus votos, la semana y un enlace al original. Cuando el tamaño permite subirla con la cuenta del bot, se conserva temporalmente una copia binaria en SQLite y se vuelve a subir al anunciarla; la copia temporal se libera tras confirmar el envío. Las imágenes mayores al límite de subida del bot se muestran mediante el adjunto original. La copia subida por el bot tiene su propio adjunto. Solo se menciona al ganador, sin @everyone.

El panel de instrucciones se mantiene sin fijar; el fijado inicial de ese panel se retira automáticamente. Solo se fija una publicación registrada como ganadora tras el cierre semanal. Se deja de fijar el destacado anterior del propio bot, conservando ambos mensajes. No se retiran fijados de jugadores ni de otros bots. Las operaciones de fijado guardan antes/después con `ChangeLog.tracked`. Un fallo al fijar no elimina la publicación ganadora.

Las subidas pendientes guardan la imagen en SQLite hasta confirmar la publicación. Sus marcas permiten recuperar un envío aceptado justo antes de un reinicio sin duplicarlo. Los anuncios semanales también se recuperan. Los botones de votar y quitar voto se desactivan al terminar su semana; Subir foto sigue disponible para la siguiente ronda.

## Comandos y premios opcionales

- `/foto semana`: clasificación actual privada y hora del cierre.
- `/foto subir`: abre el formulario de imagen dentro de Fotos, igual que el botón. Requiere poder ver y escribir en el canal. Se admite una imagen por envío, hasta el menor límite entre la subida de la cuenta del bot en el servidor y 25 MB.
- `/foto retirar foto:…`: el autor o un miembro con permiso de moderar mensajes puede retirar una foto publicada por el bot, con confirmación y comprobación de permisos de nuevo. Se elimina esa publicación del bot y queda fuera de la votación; el registro de votos se conserva. No se vuelve a publicar una foto retirada.
- `/foto premio articulo:… semana:…`: los responsables que ya autoriza la economía pueden escoger un artículo activo de perfil o **Sin premio de tienda**. `semana` es opcional y usa el lunes de referencia, por ejemplo `2026-11-09`; por defecto es la actual. Exige confirmación y comprueba autorización otra vez al confirmar.

No hay premio de tienda hasta que un responsable lo elige. Al publicarse el ganador se añade el artículo a su inventario una sola vez, con precio cero, sin cobrar a nadie ni equiparlo. No se asignan roles como parte de entregar el premio. La entrega respeta el stock; si el ganador ya tiene ese artículo o no está disponible, queda pendiente para que administración elija otro. No se permite sustituir un premio ya entregado. Los productos que crean salas de voz no son premios de este sistema.

## Datos y reversión

Las tablas `lv_photo_config`, `lv_photo_weeks`, `lv_photo_entries`, `lv_photo_votes` y `lv_photo_actions` viven en el SQLite persistente existente. Los respaldos completos incluyen resultados, votos, premios y cualquier imagen que esté pendiente de publicación. No se promete que el respaldo contenga todas las fotos históricas del canal.

`PHOTO_CONTEST_ENABLED=0` pausa el sistema conservando registros y mensajes. Para revertir solo las menciones opcionales, desplegar `cdbca6fa59586d56a38c69957341d886335560d5` y conservar la columna `mentions`. Para volver al código anterior a Subir foto, desplegar `0801ca84815332d512a02f3b2a65137a69d57815` y mantener el concurso pausado: ese código no comprende las publicaciones nuevas del bot ni las imágenes pendientes. Para volver al código anterior a todo el concurso, desplegar `7394be7065f03292afa0e7b5b068d9968c6a16a4`. Conservar `/data` y todas las columnas nuevas. No restaurar una base antigua: se perderían votos y movimientos nuevos. No borrar fotos originales ni modificar roles protegidos para revertir la función.
