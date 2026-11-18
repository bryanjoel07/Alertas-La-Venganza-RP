# Iconos de roles — VIce District

46 insignias originales para los roles actuales de GTA VI Latino | VIce District,
incluido el rol Server Booster creado después de las cinco mejoras del propietario.
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

**Preparados, todavía no instalados.** Comprobación del 18 de noviembre de 2026:
Discord informa 5 mejoras, nivel 1, y no ofrece la característica ROLE_ICONS.
Los iconos se desbloquean con nivel 2; el beneficio de estilos mejorados por tres
mejoras es independiente. No se han comprado ni reasignado mejoras mediante el bot.

Cuando la función esté disponible, se puede cargar cada imagen desde Ajustes del
servidor → Roles → Visualización → Icono del rol. Debe utilizarse el ID guardado
en manifest.json para comprobar el destino y conservar nombre, color, permisos,
miembros y posición. No se deben recrear roles eliminados.

El bot no debe cambiar roles iguales o superiores a su propio rol. Fundador,
el propio bot y los roles administrados por Discord necesitan comprobación desde
la sesión del propietario. No hay instalador automático ni cambios programados.

Fuentes oficiales:
- https://support.discord.com/hc/en-us/articles/4409571023639-Custom-Role-Icons-FAQ
- https://support.discord.com/hc/en-us/articles/360028038352-Server-Boosting-FAQ
- https://support.discord.com/hc/en-us/articles/31444213087255-Enhanced-Role-Styles
