# Minijuegos de La Venganza RP

El panel está en **General** (`1513422089162330184`). Publica un solo mensaje con botones; cada jugador recibe sus preguntas y resultados por privado en Discord.

- **Adivinar lugar:** 50 imágenes generadas de lugares reconocibles de GTA V / GTA Online. Son recreaciones, no capturas extraídas del juego. Los originales están en `assets/minigames/lugar-01.png` a `lugar-50.png`; los nombres de archivo no incluyen la solución.
- **Roleplay:** 25 preguntas sobre conceptos de rol y la comunidad. No inventa sanciones específicas del servidor.
- **Acertijos:** 25 preguntas cortas con sus variantes de respuesta.
- **Responder**, **Dame una pista** y **Otra pregunta**. Se aceptan las variantes guardadas, mayúsculas y minúsculas, respuestas sin tildes y frases como «es un…». No se usa coincidencia por fragmentos que acepte una respuesta incorrecta.
- **Mi progreso** y **Ranking** muestran aciertos y monedas ganadas. El ranking cuenta lo ganado jugando, aunque después se gaste en la tienda.

## Monedas

Cada respuesta correcta paga **25 monedas al mismo saldo de Tienda Exclusive**. Cada pregunta paga una vez por jugador, sin reinicio diario o semanal del premio. Cada miembro puede ganar sus propias 25 monedas por la misma pregunta.

El acierto, el movimiento en `eco_ledger`, la actualización en `eco_accounts` y el recibo de premio se guardan en una misma transacción SQLite. Un doble clic, dos respuestas concurrentes, una interacción repetida, un reinicio o restaurar una copia con el premio registrado no lo vuelven a pagar. No se descuentan monedas por equivocarse o cambiar la pregunta.

Cada jugador puede enviar **una respuesta cada 12 horas**, hasta dos en 24 horas. Es un límite compartido entre Fotos, Roleplay y Acertijos: el tiempo empieza cuando se guarda una respuesta real, correcta o incorrecta. Abrir, consultar, cambiar la pregunta o pedir una pista no consume el turno. Los botones antiguos y formularios que ya estaban abiertos respetan el mismo límite en la transacción de respuesta. La medianoche y los reinicios no lo reinician. El bot muestra cuándo vuelve a estar disponible en el resultado y en Mi progreso.

`lv_game_turns` conserva la última respuesta de cada jugador. Al iniciar se recuperan también respuestas reales de la versión anterior desde `lv_game_attempts`; las consultas de botones de preguntas ya terminadas no cuentan ni extienden la espera. No se retiran monedas de respuestas anteriores.

Los nuevos pagos no asignan roles, equipan artículos ni tocan permisos. `/saldo` y `/perfil` consultan el saldo existente de la economía. Se conserva una pregunta activa por jugador y su copia de respuestas; actualizar el banco no cambia una pregunta que el jugador ya tenía abierta ni vuelve a premiar un ID ya acertado.

## Comandos

- `/jugar modo:foto`, `/jugar modo:roleplay`, `/jugar modo:acertijo`.
- `/minijuegos progreso`.
- `/minijuegos ranking`.
- `/minijuegos panel`: administradores de Discord pueden recuperar el panel de General. El bot reconcilia el mensaje existente antes de publicar otro.

Las acciones verifican que el usuario sigue en el servidor, está usando General y es dueño de su pregunta. No se anuncian respuestas ni saldos en el canal público; los jugadores abren su propia consulta.

## Datos, respaldo y reversión

`lv_game_questions` guarda el banco vigente; `lv_game_sessions`, la pregunta de cada jugador; `lv_game_wins` y `lv_game_attempts`, los premios e intentos; `lv_game_turns`, la espera de 12 horas; `lv_game_config`, el mensaje del panel. El respaldo completo de SQLite incluye estas tablas y los movimientos de economía. Los archivos de imagen viajan con el código del bot; no se descargan de páginas externas al jugar.

`minigame_photos.json` describe los lugares y variantes. `minigame_catalog.py` añade preguntas de rol y acertijos. Mantener los IDs de preguntas ya existentes para impedir que editar una descripción vuelva a pagar el premio. Las imágenes están generadas para este sistema; no se borran las fotos enviadas por jugadores ni se modifica el concurso semanal.

La publicación o recuperación administrativa del panel conserva antes/después mediante `ChangeLog.tracked`. Esta versión no crea ni elimina canales y no cambia permisos de roles o miembros.

Para revertir solamente el límite de 12 horas, desplegar `ea246942c701fd723a944f77b68c498398c713d4` conservando SQLite: esa versión vuelve a permitir respuestas cada ocho segundos. Mantener `lv_game_turns` y `lv_game_attempts`; al regresar a la versión con límite se recupera la última respuesta real, incluso si se jugó durante la reversión. Para retirar todos los minijuegos, desplegar `1838de442938bcf1cffbc2a14e66067e05d19b02`. No restaurar una base antigua, retirar monedas ya ganadas ni borrar `lv_game_*` o movimientos `minigame:*`. La reversión no borra mensajes históricos de General.
