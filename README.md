# EssChino Studio Bot

Bot independiente para la tienda Tebex de EssChino Studio. Usa el token del bot nuevo, un volumen propio y una base SQLite propia. El servicio de Railway ejecuta `python main.py` desde la rama `esschino-bot`; el bot original conserva su rama `main` y sus datos.

## Servidor

La configuración utiliza las cinco categorías solicitadas: Información, Tienda, Soporte, Comunidad y Equipo. Los dieciocho canales tienen sus mensajes y paneles en español. El canal original 1514871828672151573 conserva el historial y queda privado en Equipo. El logo se aplica al servidor y al nuevo bot; el banner aparece en bienvenida, tienda y soporte. La cabecera nativa depende de la función BANNER de Discord.

Los tickets se abren en una categoría privada **Tickets Abiertos**, colocada arriba del servidor. Al cerrarlos, se mueven a **Tickets Cerrados**; el autor conserva acceso de lectura y el equipo puede reabrirlos. Formularios, transcripciones, adjuntos, votos, reseñas y operaciones se guardan en `/data/esschino.sqlite3`.

## Uso

- `/ayuda`, `/tienda`, `/soporte`, `/mis-tickets`, `/sugerir` y `/resena` son las funciones públicas.
- `/studio tienda enlace:` conecta el sitio oficial de Tebex.
- `/studio publicar` publica anuncios, productos, demostraciones, ofertas, actualizaciones, guías, preguntas frecuentes o normas. Solo usa los canales oficiales de la estructura. Las menciones son opcionales y limitadas a los roles elegidos por los miembros.
- `/studio cliente` registra una referencia que administración ya comprobó en Tebex y asigna Cliente. También se puede verificar desde el ticket. No consulta pagos automáticamente.
- `/studio tickets`, `/studio historial`, `/studio copia` y `/studio estado` muestran la gestión privada.
- Sugerencias tiene formularios, un voto por miembro y estados revisados por el equipo. Las reseñas exigen el rol Cliente; no se generan opiniones de ejemplo.

## Variables y pruebas

Configurar `DISCORD_BOT_TOKEN` solo en el servicio nuevo. `DB_PATH=/data/esschino.sqlite3`, `PORT=8080` y `ESSCHINO_SETUP_REQUEST_ID=esschino-store-20261115-v1` habilitan la instalación inicial. `ESSCHINO_TEBEX_URL` es opcional y debe ser el enlace real de la tienda. No copiar secretos, webhooks ni datos del servidor original.

Los comandos, formularios y paneles funcionan sin intents privilegiados. Si Discord ya concede Message Content Intent, el bot lo activa para respaldar también el texto de mensajes normales. El historial de cada ticket se conserva en Discord al cerrarlo.

Pruebas del bot activo: `python -m unittest discover -s tests -p test_esschino.py` y `python -m unittest discover -s tests -p test_store_bot.py`. Los módulos y pruebas heredados del otro proyecto son referencia y no forman parte del proceso activo.

## Restauración

Desactivar el servicio nuevo detiene sus funciones sin afectar al otro bot. Conservar el volumen y SQLite actuales. `/studio copia` descarga el estado previo y posterior de cada operación; las tablas esschino_messages y esschino_files guardan las copias anteriores a la retirada de canales. Discord no recupera IDs ni fechas originales de canales eliminados. Nunca restaurar una base vieja sobre pedidos y tickets nuevos.
