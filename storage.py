"""Selección conservadora de SQLite. No migra ni crea bases automáticamente."""
import os
import sqlite3
from pathlib import Path


def database_path():
    explicit = os.getenv("DB_PATH")
    directory = os.getenv("DATA_DIR") or os.getenv("RAILWAY_VOLUME_MOUNT_PATH") or "/tmp"
    target = Path(explicit) if explicit else Path(directory) / "lavenganza.sqlite3"
    if not target.is_absolute():
        raise RuntimeError("DB_PATH/DATA_DIR deben usar una ruta absoluta.")
    legacy = Path("/tmp/lavenganza.sqlite3")
    if not explicit and legacy.is_file() and target != legacy and target.is_file():
        raise RuntimeError("Hay dos bases posibles. Verifica respaldos y configura DB_PATH explícitamente; no se elegirá una automáticamente.")
    if not target.is_file() and os.getenv("ALLOW_EMPTY_DB", "0") != "1":
        raise RuntimeError(f"No existe la base esperada en {target}. Arranque detenido para proteger los datos. Restaura una copia verificada o usa ALLOW_EMPTY_DB=1 solo para una instalación nueva.")
    if not target.is_file() and target != legacy and legacy.is_file():
        raise RuntimeError("Existe una base en /tmp. Migra y verifica sus datos antes de usar otra ruta.")
    if target.is_file() and os.getenv("ALLOW_EMPTY_DB", "0") != "1":
        with sqlite3.connect(target.as_uri() + "?mode=ro", uri=True, timeout=5) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"settings", "events", "registrations"}.issubset(tables):
                raise RuntimeError("La base seleccionada está vacía o no tiene el esquema esperado. Verifica el origen antes de iniciar.")
            if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise RuntimeError("La base seleccionada no pasó quick_check. No se modificará.")
    return str(target)
