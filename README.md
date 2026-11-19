# EssChino Studio Bot

Bot independiente para la tienda Tebex de EssChino Studio. Usa el token del bot nuevo, un volumen propio y una base SQLite propia. El servicio de Railway ejecuta `python main.py` desde la rama `esschino-bot`; el bot original conserva su rama `main` y sus datos.

## Servidor

La configuración utiliza las cinco categorías solicitadas: Información, Tienda, Soporte, Comunidad y Equipo. Los dieciocho canales tienen sus mensajes y paneles en español. El canal original 1514871828672151573 conserva el historial y queda privado en Equipo. El logo se aplica al servidor y al nuevo bot; el banner aparece en bienvenida, tienda y soporte. La cabecera nativa depende de la función BANNER de Discord.

Los tickets se abren en una categoría privada **Tickets Abiertos**, colocada arriba del servidor. Al cerrarlos, se mueven a **Tickets Cerrados**; el autor conserva acceso de lectura y el equipo puede reabrirlos. Formularios, transcripciones, adjuntos, votos, reseñas y operaciones se guardan en `/data/esschino.sqlite3`.

## Uso

La tienda está en fase de venta de **Community Sanctions System** por confirmación del propietario. Los veinte paneles y sus traducciones reflejan el lanzamiento. La ficha, compatibilidad y guía se basan en `README.md`, `fxmanifest.lua` y los documentos de instalación/cambios de `community_sanctions_system_1.42.2.zip`; no se adjunta el producto de pago al Discord ni al repositorio del bot. No se anuncian precios, descuentos ni vídeos sin una fuente real.

El propietario indicó `https://esschino-studio.tebex.store` como dominio en estado Pending. La portada y `/category/3503301` devolvieron HTTP 503 al comprobarlas el 16 de noviembre de 2026. Se guarda como `pending_shop_url`, separado de `shop_url`; los paneles informan de la activación pendiente y Tienda/Catálogo/Cómo comprar muestran un botón deshabilitado, traducido a los cuatro idiomas. El bot no comprueba periódicamente el sitio ni habilita pagos por el mero paso del tiempo. Cuando el dominio esté disponible, el propietario puede conectar el enlace mediante `/studio tienda` o el botón privado; la URL activa tiene prioridad y el flujo existente renueva los paneles de compra.

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

### Reabrir el mismo ticket — v1

Los paneles de tickets cerrados incluyen **Reabrir**, **Valorar atención** y **Eliminar**. Solo el equipo vigente puede reabrir: el mismo canal vuelve a Ayuda, recupera escritura privada y conserva sus mensajes, autor, categoría de consulta, fecha original y responsable vigente. Si el responsable ya no pertenece al equipo, se conserva su asignación anterior como historial y el caso queda sin asignar. Un autor que ya salió del servidor o tiene otro ticket abierto debe resolver esa condición primero. No se reabre ningún caso automáticamente al instalar el botón.

La reapertura guarda intención, copia previa y revisión para reanudar fallos o reinicios sin duplicar canales o paneles. Vuelve al panel de pendientes; los avisos esperan 2h si nunca hubo respuesta del equipo o 24h si ya la hubo, respetando el límite diario. Las copias privadas anteriores y valoraciones aceptadas se conservan. Cada nuevo cierre captura el responsable actual; sigue habiendo una valoración por caso. Confirmaciones antiguas de eliminación y formularios anteriores de valoración no sirven después de otro ciclo.

Para retirar la función, desactivar únicamente Reabrir en los paneles cerrados registrados mediante operaciones journaled y esperar a completar las reaperturas pendientes. Después desplegar la revisión previa `95dfabc8e38721211d01152ea1d24a4ccadd948a`, conservando canales reabiertos, base actual y todos los recibos. No restaurar una base antigua, recrear tickets ni borrar mensajes. Mantener compatibilidad de paneles de cierre y metadatos de ciclo si hay casos reabiertos pendientes de cerrarse.

### Decoración uniforme para móvil — v6

La corrección v6 usa ┌ / ├ / └ para las categorías y elimina las ramas y puntos adicionales de los canales, que quedan como emoji╎nombre en versalitas. Mantiene los emojis, palabras completas y separador ╎; no añade relleno. Discord controla la sangría nativa de cada tipo de fila, por lo que este formato uniforme no promete alineación exacta entre categorías y canales ni entre dispositivos. El manifiesto v6 conserva el estado previo de los 38 objetos y solo se cambia el nombre mediante recibos nuevos, sin repetir migraciones anteriores.

Para restaurar v5, aplicar individualmente el `name` previo del manifiesto v6 solo si el nombre actual todavía coincide con `target_name`, mediante operaciones registradas. Conservar cambios manuales posteriores y la base actual. El servicio de mejoras acepta ambos formatos durante la transición; no alterar permisos, posiciones, temas, historial ni el mensaje de pendientes.

### Flechas de inicio y cierre, separador ╎ — v5

La revisión v5 conserva las versalitas, los emojis y las ramas de los canales. Cambia el separador entre emoji y nombre a ╎. Las categorías usan ↱ al inicio de la lista, │ en posiciones intermedias y ↳ al final, según el orden observado; solo cambia sus nombres. El manifiesto v5 conserva los 38 IDs, nombres previos y posiciones de referencia. No añade relleno, no reordena objetos y no repite migraciones anteriores. La creación futura de tickets y salas conserva este formato.

Para volver al diseño anterior, restaurar individualmente el nombre original del manifiesto v5 únicamente cuando todavía coincida con el nombre aplicado, mediante operaciones registradas. Restaurar primero el nombre del canal de mejoras o conservar su validación compatible antes de desplegar `29f96c499c41a5d4c18e88291a86ec6e7ce1addd`. Respetar cambios manuales y conservar la base actual, permisos, mensajes y recibos.

### Diseño anterior restaurado por solicitud del propietario — v4

El propietario canceló el experimento de separadores y alineación. `vice-channel-style-v4` restaura exclusivamente los nombres de las 38 categorías y canales a sus valores originales en versalitas, guardados como `name` en `channel-style-v2.json`. Conserva Staff, Pendientes, los emojis y las ramas originales, además de IDs, permisos, posiciones, temas e historial. El manifiesto v4 parte de un nuevo estado real y cada restauración deja copia y recibo; cambios manuales posteriores se respetan. Los nombres futuros vuelven al formato original. No se repiten las migraciones anteriores ni se restablece una base antigua.

### Separadores y nombres hacia la derecha — v3

La revisión `vice-channel-style-v3` aplica `၊၊||၊` a las categorías y coloca los nombres de categorías y canales a la derecha de sus iconos, con líneas decorativas de longitud limitada. Discord eliminó el relleno invisible de v2 al guardar; v3 parte de los nombres reales posteriores y usa caracteres visibles. La posición se aproxima según la longitud del nombre y puede variar con el ancho de la barra lateral y la fuente. Se conservan las palabras completas, versalitas y emojis. El manifiesto `channel-style-v3.json` fija los 38 objetos observados, incluido Pendientes. Solo cambia el nombre y conserva los recibos previos, permisos, IDs e historial. Los tickets y salas futuros usan el mismo formato.

Para revertir al formato v1 estable, conservar la base actual y restaurar individualmente los nombres originales del manifiesto v2 solo cuando aún coincidan con el nombre aplicado de v3, mediante operaciones registradas. El canal de mejoras `1572704521371652166` debe recuperar su nombre v1 antes de desplegar `f984035a488f798195226e4df00334645c14def4`, o se debe conservar la validación compatible con los nombres reales en el código anterior. No volver al despliegue intermedio de v2. Respetar cambios manuales; no recrear ni eliminar canales ni restaurar una base antigua. El panel de pendientes y sus recordatorios conservan sus mensajes y datos.

### Panel privado de pendientes y nombres en versalitas

La categoría Equipo pasa a Staff y las 37 categorías/canales existentes reciben letras en versalitas, conservando sus emojis y separadores. `channel-style-v1.json` fija los IDs, tipos y nombres originales; la migración cambia únicamente el nombre, con un recibo y copia anterior por objeto. No recrea objetos ausentes ni vuelve a imponer el nombre tras una edición manual posterior. Los nuevos tickets, sus nombres al cerrar y las salas temporales usan el mismo estilo.

El canal privado Pendientes, dentro de Staff, mantiene un único mensaje con enlaces directos a cada ticket abierto, responsable y tiempo de espera. Distingue espera del equipo y espera del usuario; los datos desconocidos se indican como tales. Los botones de página permiten consultar todos los casos sin publicar mensajes adicionales. Solo el equipo autorizado puede ver o usar el panel. Se conservan los recibos de creación/publicación, se comprueba la privacidad antes de actualizar y solo se edita cuando cambia el contenido. No copia consultas privadas ni valoraciones. Una marca temporal adicional de la última respuesta humana permite mostrar la espera del usuario sin alterar los recordatorios de 2/24 horas.

Para revertir esta revisión, conservar la base actual y las copias de `CHANNEL_STYLE` y del panel. Deshabilitar los botones del mensaje registrado mediante una operación documentada antes de desplegar `22be4e528c4bac7df7fb07b124085aae7dbcabdc`, que conserva los recordatorios y la auditoría. Ese código exige el nombre original del canal de mejoras: antes del despliegue, restaurar únicamente el canal `1572704521371652166` a `├・💎│mejoras-del-servidor`, según el manifiesto congelado, mediante una operación registrada con copia previa y solo si su nombre actual todavía es `├・💎│ᴍᴇᴊᴏʀᴀꜱ-ᴅᴇʟ-ꜱᴇʀᴠɪᴅᴏʀ`. Como alternativa, conservar en la versión de reversión la validación compatible con ambos nombres. Si hubo un cambio manual posterior, respetarlo y revisar esa compatibilidad antes de desplegar; no imponer el nombre original. Los demás nombres pueden restaurarse individualmente desde el manifiesto y sus copias previas, solo si todavía coinciden con el nombre aplicado; respetar posteriores cambios manuales. No borrar el canal, tickets o mensajes ni restaurar una base antigua. El canal permanece privado aunque se detenga su actualización.

### Recordatorios privados de tickets de VIce District

El primer aviso llega cuando un ticket lleva dos horas sin su primera respuesta humana del equipo. Después de esa primera respuesta, las nuevas consultas del autor esperan veinticuatro horas. Mientras siga pendiente, se envía como máximo un recordatorio por ticket cada veinticuatro horas; los mensajes adicionales del autor no reinician la espera. Una respuesta del equipo pausa los avisos hasta la siguiente consulta, y cerrar el ticket los detiene. Pulsar Atender no cuenta como respuesta.

El aviso se publica únicamente dentro del ticket privado y menciona al responsable actual. Si no hay asignación, menciona exclusivamente el rol registrado de Soporte. El bot comprueba el historial antes de avisar, valida permisos y estado, y conserva metadatos de espera y recibos de entrega en la base propia de VIce. No almacena el texto privado de las consultas para esta función. Los reinicios conservan la cadencia y no acumulan avisos atrasados. Las comprobaciones periódicas se realizan aproximadamente cada minuto.

Para desactivar esta función, desplegar `05f8676a7998912a6881942d2bf747405b55afe7` en el servicio independiente y conservar la base y sus recibos actuales. Los avisos ya publicados permanecen en el historial; no borrar tickets, restablecer una base antigua ni repetir la instalación. El código anterior conserva las comparaciones visuales de auditoría y el resto del sistema de tickets.

### Comparaciones visuales de VIce District — revisión v7

Las actualizaciones del servidor explican qué cambió: fondo de invitación, banner, icono, nombre, descripción o canal del sistema. Los cambios de imagen se comparan por su identidad real y se describen sin mostrar hashes; los identificadores se distinguen como Usuario y Servidor, con el nombre real de cada uno junto al ID. Los nombres se obtienen de las identidades coincidentes del evento; si Discord no resuelve un nombre, se conserva su ID sin inventarlo. Los permisos conservan su lista por líneas.

La revisión `vice-audit-server-images-v7` añade una comparación ANTES / DESPUÉS de las imágenes reales cuando cambia el icono, banner o fondo de invitación. Mantiene los nombres, IDs y hora de Puerto Rico. Solo procesa cambios del servidor autorizado: obtiene las imágenes del CDN oficial por sus hashes comprobados, sin seguir redirecciones, con límites de tiempo, bytes y píxeles. Distingue una imagen ausente, retirada o ya no disponible. Las dos copias históricas de fondos que Discord dejó de conservar están en `assets/vice-district/audit-history`, con procedencia y SHA-256 verificados.

La caché SQLite conserva las imágenes obtenidas y todas las versiones de comparaciones en `vice_audit_visual_assets` y `vice_audit_visual_files`, antes de publicar. Los archivos se identifican por evento y contenido; solo esas comparaciones registradas pueden reemplazarse. Discord puede omitir de `message.attachments` un archivo usado dentro de una tarjeta: la entrega también comprueba su URL de imagen en el CDN oficial, el canal exacto y su correspondencia con el evento y la copia registrada. Los resultados incompletos pueden reintentarse después de quince minutos cuando el evento vuelva a leerse. La revisión vuelve a leer la auditoría disponible y actualiza los mismos mensajes registrados, conservando fechas originales. No cambia `AUDIT_VERSION`, ni borra mensajes o vuelve a publicar el historial. Antes de editar, valida autor e identificadores de todas las tarjetas y guarda inserciones y metadatos de archivos mediante `AUDIT_RECORD`; los bytes anteriores quedan en la caché durable. Una segunda pasada sin cambios no vuelve a publicar ni editar.

Para volver al formato anterior, conservar la base y caché actuales. Primero, con esta versión compatible con adjuntos, restaurar las tarjetas exactas desde `before_message` mediante nuevas operaciones registradas; retirar solo los adjuntos de comparación registrados, nunca archivos ajenos. Después desplegar `41766a59e0ab41e5829ccd3ae3a9e6fba29adde2` del servicio independiente. No desplegar v6 directamente sobre tarjetas con imágenes: su comprobación anterior rechaza cualquier adjunto y bloquearía esas actualizaciones. Para restaurar una comparación previa, sus bytes se recuperan por filename en `vice_audit_visual_files`. No restaurar una base antigua, purgar registro-staff ni reiniciar la instalación. Studio y el bot original permanecen fuera de este cambio.

Desactivar el servicio nuevo detiene sus funciones sin afectar al otro bot. Conservar el volumen y SQLite actuales. `/studio copia` descarga el estado previo y posterior de cada operación; las tablas esschino_messages y esschino_files guardan las copias anteriores a la retirada de canales. Discord no recupera IDs ni fechas originales de canales eliminados. Nunca restaurar una base vieja sobre pedidos y tickets nuevos.

Para revertir los botones de idiomas, primero restaurar los componentes anteriores de las operaciones `PANEL_LANGUAGES` (sin alterar texto, adjuntos, permisos ni roles) mediante una operación registrada, y después desplegar `23ad8d96b0eaa12cdd058559a7ee237b93b1f11c`. Volver solo al código anterior deja botones de idiomas sin manejador; no restaurar una base antigua ni repetir la instalación del servidor.

Para revertir la bienvenida personalizada, conservar `studio_welcomes`, restaurar solo los componentes anteriores del registro `WELCOME_PANEL` y desplegar `670d61a385e077c24568734ab68b11b9dd8b20f0`. No eliminar tarjetas ya enviadas ni restaurar bases antiguas.

Para revertir el lanzamiento, conservar la base actual y restaurar solo los textos/componentes/temas de las copias `STORE_LAUNCH` mediante una nueva operación registrada; después desplegar `8fb1218ef70a894625ae7027ce165aa7a8d28fb8`. No restaurar una base antigua sobre tickets o pedidos nuevos.
