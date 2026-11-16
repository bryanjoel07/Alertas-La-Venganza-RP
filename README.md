# EssChino Studio Bot

Bot independiente para la tienda Tebex de EssChino Studio. Usa el token del bot nuevo, un volumen propio y una base SQLite propia. El servicio de Railway ejecuta `python main.py` desde la rama `esschino-bot`; el bot original conserva su rama `main` y sus datos.

## Servidor

La configuración utiliza las cinco categorías solicitadas: Información, Tienda, Soporte, Comunidad y Equipo. Los dieciocho canales tienen sus mensajes y paneles en español. El canal original 1514871828672151573 conserva el historial y queda privado en Equipo. El logo se aplica al servidor y al nuevo bot; el banner aparece en bienvenida, tienda y soporte. La cabecera nativa depende de la función BANNER de Discord.

Los tickets se abren en una categoría privada **Tickets Abiertos**, colocada arriba del servidor. Al cerrarlos, se mueven a **Tickets Cerrados**; el autor conserva acceso de lectura y el equipo puede reabrirlos. Formularios, transcripciones, adjuntos, votos, reseñas y operaciones se guardan en `/data/esschino.sqlite3`.

## Uso

La tienda está en fase de venta de **Community Sanctions System** por confirmación del propietario. Los veinte paneles y sus traducciones reflejan el lanzamiento. La ficha, compatibilidad y guía se basan en `README.md`, `fxmanifest.lua` y los documentos de instalación/cambios de `community_sanctions_system_1.42.2.zip`; no se adjunta el producto de pago al Discord ni al repositorio del bot. No se anuncian precios, descuentos ni vídeos sin una fuente real.

`StoreLaunch` actualiza los mensajes registrados y los temas de los canales mediante `ChangeLog.tracked`, conservando IDs, permisos, imágenes e historial. Guarda un recibo por panel y revisión/enlace; un reinicio no repite la migración ni sobrescribe posteriores ediciones manuales. Configurar la tienda mediante `/studio tienda` o el botón privado renueva los veinte paneles y agrega enlaces de compra en Tienda, Catálogo y Cómo comprar. Se rechazan `builder.tebex.io`, los paneles administrativos y las rutas de vista previa; se necesita una URL pública verificada. Sin URL, se anuncia la disponibilidad real y se dirige al canal de tienda/soporte para obtener el enlace, sin inventarlo.

Los veinte paneles oficiales (dieciocho canales, Dirección y el resumen de instalación) incluyen botones **English**, **Português (Brasil)**, **Français** y **Deutsch**, tomados del manifiesto de idiomas de `community_sanctions_system_1.42.2.zip`. El mensaje público conserva el español y no incluye un botón Español. Cada persona abre una traducción privada; si cambia de idioma en esa copia, se actualiza únicamente su copia. Se conservan imágenes, enlaces y controles, con sus etiquetas traducidas. El idioma de los formularios y de las respuestas operativas sigue siendo español.

- `/ayuda`, `/tienda`, `/soporte`, `/mis-tickets`, `/sugerir` y `/resena` son las funciones públicas.
- `/studio tienda enlace:` conecta el sitio oficial de Tebex.
- `/studio publicar` publica anuncios, productos, demostraciones, ofertas, actualizaciones, guías, preguntas frecuentes o normas. Solo usa los canales oficiales de la estructura. Las menciones son opcionales y limitadas a los roles elegidos por los miembros.
- `/studio cliente` registra una referencia que administración ya comprobó en Tebex y asigna Cliente. También se puede verificar desde el ticket. No consulta pagos automáticamente.
- `/studio tickets`, `/studio historial`, `/studio copia` y `/studio estado` muestran la gestión privada.
- Sugerencias tiene formularios, un voto por miembro y estados revisados por el equipo. Las reseñas exigen el rol Cliente; no se generan opiniones de ejemplo.

## Bienvenida personalizada

Cada entrada real de una persona genera en Bienvenida una tarjeta con su nombre visible, usuario y foto de perfil actual sobre la plantilla de EssChino Studio. Los reinicios no vuelven a saludar a todos los miembros. Los recibos de `studio_welcomes` permiten reconocer envíos completados, recuperar envíos interrumpidos y cancelar avisos de membresías que ya terminaron.

El botón **Mi bienvenida** del panel genera una vista privada para la persona que lo pulsa, también para miembros que ya estaban en el servidor. La tarjeta respeta el idioma de esa copia del panel. Discord comparte el panel público entre todos; cada tarjeta individual contiene la identidad real de su destinatario. No se publica una entrada ficticia para mostrar una prueba.

El bot utiliza la autorización Gateway Guild Members del nuevo bot para recibir entradas; no copia datos ni permisos del bot original. La plantilla gráfica está en `assets/esschino/welcome-template.png`, y las fuentes Noto incluyen su licencia SIL OFL. Las fotos se descargan del CDN de Discord y las tarjetas se componen localmente, sin enviar perfiles a servicios de generación de imágenes.

## Variables y pruebas

Configurar `DISCORD_BOT_TOKEN` solo en el servicio nuevo. `DB_PATH=/data/esschino.sqlite3`, `PORT=8080` y `ESSCHINO_SETUP_REQUEST_ID=esschino-store-20261115-v1` habilitan la instalación inicial. `ESSCHINO_TEBEX_URL` es opcional y debe ser el enlace real de la tienda. No copiar secretos, webhooks ni datos del servidor original.

Los comandos y formularios no requieren intents privilegiados; la bienvenida automática utiliza Guild Members Intent, ya configurado en este bot. Si Discord ya concede Message Content Intent, el bot lo activa para respaldar también el texto de mensajes normales. El historial de cada ticket se conserva en Discord al cerrarlo.

Pruebas del bot activo: `python -m unittest discover -s tests -p test_esschino.py` y `python -m unittest discover -s tests -p test_store_bot.py`. Los módulos y pruebas heredados del otro proyecto son referencia y no forman parte del proceso activo.

Las pruebas de idiomas están en `test_panel_languages.py`: cobertura de todos los paneles e idiomas, límites de componentes, cambios privados, controles persistentes, enlaces, imágenes, permisos y actualización idempotente con copia anterior duradera.

Las pruebas de tarjetas y entregas están en `test_welcome_cards.py`: nombre, avatar, tamaño de imagen, nombres largos, idiomas, recibos persistentes, reentradas reales, envíos ambiguos, privacidad y aislamiento del servidor.

Las pruebas de lanzamiento están en `test_store_launch.py`: actualización de los mismos veinte mensajes con copias previas, conservación de controles/banners/permisos, aislamiento, cambios de enlace de compra y conservación de ediciones posteriores al reiniciar. También validan los cinco idiomas sin marcadores pendientes ni enlaces de editor.

## Restauración

Desactivar el servicio nuevo detiene sus funciones sin afectar al otro bot. Conservar el volumen y SQLite actuales. `/studio copia` descarga el estado previo y posterior de cada operación; las tablas esschino_messages y esschino_files guardan las copias anteriores a la retirada de canales. Discord no recupera IDs ni fechas originales de canales eliminados. Nunca restaurar una base vieja sobre pedidos y tickets nuevos.

Para revertir los botones de idiomas, primero restaurar los componentes anteriores de las operaciones `PANEL_LANGUAGES` (sin alterar texto, adjuntos, permisos ni roles) mediante una operación registrada, y después desplegar `23ad8d96b0eaa12cdd058559a7ee237b93b1f11c`. Volver solo al código anterior deja botones de idiomas sin manejador; no restaurar una base antigua ni repetir la instalación del servidor.

Para revertir la bienvenida personalizada, conservar `studio_welcomes`, restaurar solo los componentes anteriores del registro `WELCOME_PANEL` y desplegar `670d61a385e077c24568734ab68b11b9dd8b20f0`. No eliminar tarjetas ya enviadas ni restaurar bases antiguas.

Para revertir el lanzamiento, conservar la base actual y restaurar solo los textos/componentes/temas de las copias `STORE_LAUNCH` mediante una nueva operación registrada; después desplegar `8fb1218ef70a894625ae7027ce165aa7a8d28fb8`. No restaurar una base antigua sobre tickets o pedidos nuevos.
