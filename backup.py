"""Respaldo manual/externamente programable. Nunca ejecuta el bot ni restaura datos.

python backup.py --source /ruta/base.sqlite3 --output /ruta/respaldo.db
Añadir --drive-folder ID para subir usando GOOGLE_APPLICATION_CREDENTIALS.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from contextlib import closing
from backup_meta import atomic_json, record_backup
import sqlite3


def snapshot(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or not source.is_file():
        raise ValueError("El origen debe existir y ser distinto del destino.")
    output.parent.mkdir(parents=True, exist_ok=True)
    # O_EXCL evita reemplazar cualquier respaldo existente.
    fd = os.open(str(output), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=10)) as src:
            with closing(sqlite3.connect(output)) as dst, dst:
                src.backup(dst, pages=256, sleep=0.05)
                if dst.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise RuntimeError("El respaldo no pasó integrity_check.")
                tables = [r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
                counts = {name: dst.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0] for name in tables}
        digest = hashlib.sha256()
        with output.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return {"file": str(output), "source": str(source), "sha256": digest.hexdigest(), "integrity": "ok", "rows": counts, "created_at": datetime.now(timezone.utc).isoformat(), "size_bytes": output.stat().st_size, "drive_state": "not_requested"}
    except Exception:
        output.unlink(missing_ok=True)
        raise


def upload_drive(path, folder):
    # Dependencias opcionales: pip install -r requirements-backup.txt
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive.file"])
    path = Path(path)
    with AuthorizedSession(credentials) as session:
        response = session.post("https://www.googleapis.com/upload/drive/v3/files", params={"uploadType": "resumable", "fields": "id,size,md5Checksum"}, json={"name": path.name, "parents": [folder]}, headers={"X-Upload-Content-Type": "application/vnd.sqlite3", "X-Upload-Content-Length": str(path.stat().st_size)}, timeout=30)
        response.raise_for_status()
        location = response.headers["Location"]
        # No se imprime la URL de sesión ni se guarda en el repositorio.
        with path.open("rb") as data:
            result = session.put(location, data=data, headers={"Content-Type": "application/vnd.sqlite3", "Content-Length": str(path.stat().st_size)}, timeout=180)
        result.raise_for_status()
        info = result.json()
        if int(info.get("size", -1)) != path.stat().st_size:
            raise RuntimeError("Drive no confirmó el tamaño del archivo.")
        digest = hashlib.md5()  # Checksum de transporte de Drive, no autenticación.
        with path.open("rb") as data:
            for chunk in iter(lambda: data.read(1024 * 1024), b""):
                digest.update(chunk)
        if info.get("md5Checksum") != digest.hexdigest():
            raise RuntimeError("Drive no confirmó el checksum del respaldo.")
        return info["id"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--drive-folder")
    args = parser.parse_args()
    manifest = snapshot(args.source, args.output)
    manifest_path = Path(str(args.output) + ".manifest.json")
    manifest["drive_state"] = "pending" if args.drive_folder else "not_requested"
    fd = os.open(str(manifest_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump(manifest, file, indent=2)
    record_backup(args.source, manifest)
    if args.drive_folder:
        try:
            manifest["drive_file_id"] = upload_drive(args.output, args.drive_folder)
            manifest["drive_state"] = "verified"
        except Exception:
            manifest["drive_state"] = "failed"
            atomic_json(manifest_path, manifest)
            record_backup(args.source, manifest)
            raise
        atomic_json(manifest_path, manifest)
        record_backup(args.source, manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
