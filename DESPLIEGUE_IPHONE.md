# Preparación y despliegue seguro desde iPhone

**No desplegar todavía.** La base activa podría seguir en `/tmp`.
Un redeploy, cambio de volumen o reinicio puede perder ese archivo. Esta entrega no realizó esas acciones.
La ausencia de una base ahora detiene el bot deliberadamente: no activar ALLOW_EMPTY_DB para ocultar el problema.

## 1. Guardar y revisar el código sin afectar Railway

1. Descarga el ZIP de esta entrega y guárdalo en Archivos de iPhone. Descomprímelo tocándolo.
2. Abre GitHub en Safari. En el repositorio, selecciona la rama actual y crea una rama
   `mejoras-reuniones` desde `main`. Verifica que Railway no despliegue esa rama.
3. En esa rama, usa Add file → Upload files. Si no aparece, solicita sitio de escritorio.
   Sube el contenido de la carpeta, no una carpeta adicional encima. Conserva `tests/test_bot.py`
   dentro de `tests`; para archivos individuales puedes usar Add file → Create new file con esa ruta.
4. Revisa cambios y abre un Pull Request hacia `main`. **No lo fusiones**: Railway puede tener
   despliegue automático al actualizar `main`. No cambies el webhook, token ni IDs.
5. Puedes volver a hacer privado el repositorio con Settings → General → Danger Zone →
   Change repository visibility → Private. Este entorno ya tiene una copia local del código;
   eso no garantiza acceso remoto futuro si la conexión de GitHub sigue sin autorización privada.

No subas bases ni respaldos a GitHub. El ZIP de entrega no los incluye.

## 2. Confirmar la situación real (lectura)

En Safari abre Railway → proyecto → servicio del bot. Revisa Variables y Volumes sin guardar
cambios. Anota nombres/rutas, nunca copies los valores de secretos al chat.
La fórmula de la versión anterior es DATA_DIR, después RAILWAY_VOLUME_MOUNT_PATH y, por último, /tmp;
el archivo se llama lavenganza.sqlite3. Un valor configurado no demuestra que exista una base válida.
Confirma en el contenedor la ruta y conteos de tablas. Si la interfaz no ofrece shell o descarga,
no supongas que se puede hacer la migración solo con botones del dashboard.

Puedes usar GitHub Codespaces desde Safari (menú Code → Codespaces → Create codespace),
si tu cuenta dispone de esa función/cuota, y su terminal. Es un entorno externo a Railway:
`/tmp` ahí NO es `/tmp` del bot. Para conectar usa la CLI oficial de Railway:

```sh
npm install -g @railway/cli
railway login --browserless
railway link
railway ssh
```

Verifica cuidadosamente proyecto, entorno y servicio al enlazar. Sigue la autenticación en tu
propio navegador, sin compartir códigos o tokens. Si SSH no está disponible en tu plan,
solicita una vía de exportación a Railway antes de desplegar. No reinicies para habilitarlo
mientras la única copia esté en /tmp.

## 3. Plan de respaldo y migración — requiere tu aprobación antes de ejecutarlo

**Riesgo:** montar el volumen o hacer redeploy puede destruir el único archivo de /tmp.
Una copia previa puede omitir inscripciones nuevas posteriores al respaldo. Se necesita una
ventana coordinada sin escrituras y una copia final externa comprobada antes de recrear el contenedor.
`/mantenimiento iniciar` NO congela las inscripciones: solo suspende alertas. No lo uses como garantía.
La forma de impedir todas las escrituras debe acordarse tras revisar el acceso real y la operación
actual del servicio; nunca detener/eliminar el contenedor para intentar hacer primero el respaldo.

Secuencia propuesta:

1. Crear respaldo consistente desde el contenedor que tiene la base real, usando la API backup de
   SQLite. No copiar directamente un archivo activo ni asumir que `/tmp/respaldo.db` está al día.
2. Descargar esa copia fuera de Railway, verificar `PRAGMA integrity_check`, conteos y SHA-256.
   Guardar otra copia en Drive o almacenamiento externo. Probar su apertura/restauración en un
   directorio de prueba, sin reemplazar la base original.
3. Acordar y autorizar ventana sin escrituras. Crear y exportar una copia final bajo esa condición;
   volver a verificarla. No avanzar mientras solo exista en el contenedor actual.
4. Solo entonces activar/montar volumen en `/data`. Restaurar el respaldo final allí sin sobrescribir
   un archivo existente. Comparar integridad y conteos, especialmente events y registrations.
5. Fijar `DB_PATH=/data/lavenganza.sqlite3`; `ALLOW_EMPTY_DB=0`. Revisar también DATA_DIR.
   Desplegar una sola réplica, evitando solapamiento con otra instancia. La versión actual
   fallará de forma segura si se inicia antes de restaurar la base.
6. Tras arranque, verificar logs, comandos sincronizados, registros y botones antiguos.
   Las tablas nuevas se crean sin alterar las anteriores. Guardar respaldo posterior al cambio.
7. Mantener copias externas. Ante un fallo, detener nuevos cambios y evaluar datos nuevos antes
   de restaurar una copia antigua: restaurarla directamente podría perder actividad posterior.

Ejemplo de respaldo con Python estándar en el **contenedor correcto**, después de autorizarlo:

```python
from pathlib import Path
import sqlite3, hashlib
src = Path('/tmp/lavenganza.sqlite3')  # reemplazar SOLO por la ruta activa verificada
out = Path('/tmp/lavenganza-respaldo-FECHA.db')
assert src.is_file()
with out.open('xb'):
    pass
with sqlite3.connect(src.as_uri() + '?mode=ro', uri=True) as source:
    with sqlite3.connect(out) as target:
        source.backup(target)
        assert target.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
print(out, hashlib.sha256(out.read_bytes()).hexdigest())
```

Para descargar a un Codespace desde su terminal local (sal primero del shell remoto), la CLI
permite ejecutar un comando SSH; comprueba `railway ssh --help` para tu versión:

```sh
railway ssh -- cat /tmp/lavenganza-respaldo-FECHA.db > lavenganza-respaldo-FECHA.db
```

No confíes en la descarga hasta verificar integridad y SHA-256 localmente: mensajes de la CLI,
fallos o truncamiento pueden invalidar el archivo. No imprimas el contenido de la base en el chat
ni la subas al repositorio. Descárgala a Archivos desde el explorador de Codespaces y comprueba
que está disponible fuera del Codespace. Para copias adicionales a Drive usa `backup.py`, OAuth
adecuado y el procedimiento del README, nunca credenciales dentro del ZIP.

## 4. Validación posterior al despliegue autorizado

- Logs: arranque, sincronización de seis comandos raíz y ausencia de errores SQLite.
- Comprobar un evento existente, participantes y contador antes de registrar actividad nueva.
- Crear una reunión de prueba con un rol permitido; comprobar canal Staff y General.
- Verificar que alguien sin acceso al canal Staff no pueda consultar ni responder esa reunión.
- Cambiar una respuesta, registrar presencia real y consultar el informe.
- Editar, cancelar y finalizar reuniones; confirmar que se conservan registros y se bloquean botones.
- Probar anuncios en iPhone y computadora. Probar reinicio solo tras confirmar la persistencia y
  con autorización; revisar después botones de eventos y reuniones.
- Probar alertas únicamente con /testalert o /simular-ciclo, identificadas como simulación.
- Revisar los recordatorios con una reunión de prueba; no modificar fechas/datos de reuniones reales
  para forzarlos. Validar Drive con una copia de prueba y una restauración externa.

Ni la existencia del volumen ni un log de arranque sustituyen verificar los registros anteriores.
