# Panel de ajustes

Usar **`/ajustes panel`** en La Venganza RP, fuera del canal exclusivo de perfiles. La respuesta es privada y solo puede manejarla el administrador que la abrió. El bot comprueba de nuevo en Discord que conserva Administrador antes de guardar. No crea canales ni cambia roles o permisos.

- **📸 Premios de Fotos:** elegir esta semana o la próxima, escribir los premios del primer, segundo y tercer lugar y revisar la fecha y el total. Se admiten enteros entre 1 y 1.000.000, en orden de mayor a menor o iguales. Se mantienen hasta el siguiente cambio programado; no se cambian semanas cerradas ni premios ya pagados.
- **🕒 Hora del Server Up:** acepta `18:30` o `6:30 p. m.`, siempre en Puerto Rico. Solo se revisa el minuto de esa hora. Guardar no envía una prueba ni repite un aviso ya revisado ese día. Si la hora ya pasó, se espera a la siguiente fecha; no se recuperan anuncios perdidos. Sigue requiriendo servidor arriba, estado confirmado y ausencia de mantenimiento.
- **📝 Texto del Server Up:** editar título, cuerpo y pie. Se pueden usar `{enlace}`, `{servidor}` y `{hora}`. El cuerpo debe conservar `{enlace}`. Se comprueban llaves, campos y límites de Discord antes de ofrecer guardar. El banner rojo y la mención a todos del aviso siguen funcionando como estaban.

El formulario solo crea una vista previa: **Guardar cambios** confirma y **Cancelar** descarta. Las vistas previas no mencionan a jugadores ni publican un Server Up. Cada panel dura diez minutos. Si otro administrador guarda antes, una confirmación antigua se rechaza para evitar sobrescribirle. Una confirmación duplicada usa el mismo recibo y no repite la operación.

La configuración se guarda en el SQLite existente, sin reiniciar ni editar variables de Railway. `lv_photo_reward_rates` contiene los premios por fecha de inicio; las claves `daily_server_up_*` guardan horario y textos. `admin_settings_revision` evita cambios antiguos y `bot_setting_ops` conserva autor y valores exactos antes/después. El respaldo completo incluye estas tablas. No se modifican saldos al guardar: el cierre semanal paga con los premios que correspondan a su semana.

Fotos, tienda y guía se refrescan después de confirmar. Si Discord no responde, la configuración ya guardada permanece y los paneles públicos se reintentan en sus ciclos habituales. `ADMIN_SETTINGS` guarda la copia privada de cada operación mediante `ChangeLog.tracked`; no se anuncian cambios en Registro Exclusive.

Para revertir el código, usar `bdc5114e9522d75e298ea5ab1561450b652cc45d`, conservando SQLite. Esa versión ignora los ajustes nuevos y usa 500/300/150, 18:30 y textos originales: revisar primero los premios programados y pausar el concurso si deben mantenerse para un cierre próximo. Conservar tablas y claves nuevas, en particular `daily_server_up_slot`; no restaurar una base antigua ni recalcular premios pagados. Para deshacer un ajuste con esta versión, guardar sus valores anteriores como un cambio nuevo después de revisarlos.

El commit inmediatamente anterior, `c63c8df5b3dc5c7dc85c63158acfb19fa3d28a8c`, conserva los datos y el panel, pero puede registrar un falso error de permisos durante la verificación porque el SDK omite ese campo en `to_dict`. La versión actual verifica la propiedad recibida directamente de Discord.
