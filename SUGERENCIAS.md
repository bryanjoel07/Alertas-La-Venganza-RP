# Sugerencias de La Venganza RP

Canal solicitado: `1539013973947588759`. El panel del bot contiene **Proponer una idea** y **Mis ideas**. En un canal de texto se fija únicamente ese panel; en un foro se crea una entrada propia con las instrucciones. Cada idea se publica como mensaje o como entrada del foro según el tipo del canal. Se conservan las publicaciones, permisos y paneles anteriores.

## Jugadores

El formulario pide un título (3–100 caracteres), la idea (10–2000) y, opcionalmente, en qué ayudaría (hasta 700). La publicación muestra quién la propuso. Un clic repetido sobre el mismo envío no crea otra idea. Las ideas idénticas del mismo jugador que siguen abiertas se detectan y se indica su número; entre formularios distintos hay una espera de un minuto.

Cada idea tiene **A favor**, **En contra**, **Quitar voto** y **Estado**. Cada persona tiene un solo voto por idea y puede cambiarlo o retirarlo. El autor puede participar igual que los demás. Los recuentos se calculan a partir de los votos guardados, sin sumar clics repetidos. No se entregan monedas por votar.

**Mis ideas** muestra únicamente las propuestas del jugador, con su estado y un enlace a cada publicación. La lista es privada y tiene páginas de diez ideas. Las publicaciones eliminadas se retiran de la lista sin borrar sus datos internos.

Comandos disponibles dentro del servidor:

- `/sugerencias proponer`: abre el mismo formulario.
- `/sugerencias mis`: consulta las ideas propias.
- `/sugerencias ver numero`: consulta una idea y el enlace a su publicación.

## Administración

**Estado** abre un selector con Pendiente, Aceptada, En proceso, Hecha y Rechazada y un campo para explicar la decisión. Solo los roles originales Owner, Programador, Admin y Súper Admin o miembros con el permiso real Administrador pueden usarlo. Se comprueban otra vez sus roles y su acceso al enviar el formulario; si otra persona cambió antes la decisión, se pide volver a abrirlo. Los votos recibidos mientras el administrador escribe no invalidan su formulario.

La explicación y el administrador responsable aparecen en la idea. Hecha y Rechazada cierran los votos y desactivan sus botones; una revisión posterior puede volver a abrirlos conservando todos los votos. Cada decisión guarda actor, estado anterior, estado nuevo, explicación y fecha, además de una copia privada anterior y posterior en el registro de cambios.

## Acceso y conservación

Los jugadores necesitan poder ver el canal y leer su historial. Si Ciudadanos no tiene alguno de los accesos necesarios, el instalador concede únicamente ver, historial y comandos en ese canal con respaldo y lectura de verificación. Conserva su permiso de escritura y todos los demás accesos. No cambia definiciones, jerarquía ni membresías de roles. Los formularios y avisos no mencionan a todos.

Los botones siguen funcionando después de reiniciar. Las sugerencias, votos y decisiones están en las tablas `lv_suggestions`, `lv_suggestion_votes`, `lv_suggestion_events` y `lv_suggestion_config` del SQLite actual; el respaldo completo existente las incluye automáticamente.

Una publicación incompleta conserva una reserva de tres minutos. Al recuperarla, el bot busca primero su propia publicación por el número de idea para evitar duplicarla si Discord aceptó el envío y se perdió la respuesta. Los votos y estados cuya edición falló permanecen pendientes y se reintentan cada minuto. Antes de marcar una actualización como terminada, el bot vuelve a leer la publicación y comprueba texto, estado, votos y botones. Las publicaciones eliminadas no se recrean; se conservan sus datos y su historial.

Para volver al código anterior, seguir `RESTORE` de la versión en `change_log.py`, conservando la base actual. No restaurar una base antigua ni eliminar mensajes para revertir el código.
