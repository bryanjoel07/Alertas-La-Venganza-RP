# Palabras obscenas

La regla nativa **La Venganza RP · Lenguaje obsceno** bloquea el envío de los términos de `obscenities.py`. Incluye `cbnes`, `cbn`, `cbns`, `cbnas`, `cbrn`, `cbn3s` y variantes explícitas con puntos, espacios, guiones o guiones bajos. Son palabras nativas de AutoMod; no dependen de una nueva expresión que Discord pueda rechazar. Se mantienen límites de palabra para evitar bloquear palabras normales que solo contienen esas letras.

Al arrancar, el bot revisa y actualiza su propia regla aunque ya exista `obscenity_rule_id`. Conserva exactamente los patrones regex ya aceptados por Discord, añade las palabras nuevas y verifica que la regla está activa y tiene acción de bloqueo. No modifica reglas creadas por otra persona o aplicación. Las palabras manuales, lista permitida, exenciones y acciones existentes se conservan; no se añaden expulsiones ni tiempos de espera.

`OBSCENITY_FILTER` guarda la regla antes/después con `ChangeLog.tracked`. El canal Registro Exclusive continúa sin anuncios de versiones. El diagnóstico del mensaje reportado en General consulta hasta cien mensajes recientes y solo registra su ID y si el autor/canal está exento; no borra ni vuelve a publicar mensajes históricos.

Discord exime de AutoMod a quienes tienen **Administrador** o **Gestionar servidor**, además de las exenciones configuradas en la regla. Esto es propio de [AutoMod de Discord](https://support.discord.com/hc/en-us/articles/4421269296535-AutoMod-FAQ), no se cambian permisos de roles para alterarlo.

Para revertir el código, desplegar `515006d53637b97d48c7e84405229b13ef4d6bb4` y conservar SQLite. Para revertir la configuración de AutoMod, consultar el antes/después de `OBSCENITY_FILTER` y restaurar solo los campos de esta operación en el mismo ID, respetando cambios manuales posteriores. Volver al código anterior no revierte la regla de Discord automáticamente.

El commit inmediatamente anterior `aebdaaba8f062892b6b4ab8d6291a7e587cdeacc` puede volver a proponer una expresión que Discord rechazó; no usarlo para restaurar el instalador estable.
