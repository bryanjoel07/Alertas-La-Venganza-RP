# Iconos de roles — VIce District

46 insignias originales para los roles actuales de GTA VI Latino | VIce District,
incluido el rol Server Booster.
Todas comparten el emblema VI, palmera, puesta de sol y la paleta ciruela, rosa,
cian y marfil del servidor. El símbolo central corresponde al rol existente.
Las banderas permanecen en los nombres de los roles; los emblemas de las imágenes
son versiones gráficas simplificadas para su lectura en pequeño.

## Archivos

- `png/`: imágenes de 64 × 64 píxeles, transparentes, listas para Discord.
- `masters/`: copias de 256 × 256 píxeles.
- `preview.png`: hoja completa a tres tamaños.
- `manifest.json`: correspondencia exacta entre archivo, clave e ID del rol.
- `render.py`, `render_countries.py`, `render_symbols.py`: arte original dibujado
  con primitivas, siguiendo el sistema gráfico ya usado en los emojis del servidor.

Los archivos son estáticos. Ninguno supera 256 KB. Las 46 imágenes son distintas.
No hay imagen para @everyone, que es el rol predeterminado de Discord.

## Estado de instalación

**46 iconos instalados y verificados el 18 de noviembre de 2026.** Se aplicaron
**43 mediante el bot** y **3 mediante la interfaz de Discord en la sesión del
propietario**: Fundador, el propio bot y Server Booster. La comprobación final
confirmó los iconos de ambos grupos en los roles exactos del manifiesto.

`vice_role_icons.py` aplica el grupo permitido al bot usando los IDs exactos y
las imágenes del manifiesto, con registro de cambios. Los otros tres se gestionan
desde Ajustes del servidor → Roles → Visualización → Icono del rol. Se conservan
nombre, color, permisos, miembros y posición. No se recrean roles eliminados.

El instalador de iconos no cambia roles iguales o superiores al del bot ni los
administrados por Discord. El manifiesto y los registros conservan la
correspondencia entre cada archivo, rol y vía de instalación. La imagen del rol
Booster se conserva durante su personalización posterior como VIP del Distrito.

Fuentes oficiales:
- https://support.discord.com/hc/en-us/articles/4409571023639-Custom-Role-Icons-FAQ
- https://support.discord.com/hc/en-us/articles/360028038352-Server-Boosting-FAQ
- https://support.discord.com/hc/en-us/articles/31444213087255-Enhanced-Role-Styles
