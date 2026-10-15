"""Copias de seguridad de la base de datos (SQLite). Todo ocurre en este equipo."""
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from app.db.migraciones import comprobar_compatible
from app.paths import backups_dir

REQUIRED_TABLES = {"users", "clients", "equipment", "cases"}
MANUAL_PREFIX = "respaldo_"
AUTO_PREFIX = "auto_"
SAFETY_PREFIX = "antes_de_restaurar_"
MAX_AUTO = 10

_lock = threading.Lock()
_ultimo_sello = datetime.min


def _stamp() -> str:
    """Fecha y hora con microsegundos, estrictamente creciente en este proceso.
    El reloj de Windows tiene resolución gruesa: si repite un valor, se avanza
    1 microsegundo para que el orden alfabético sea siempre el cronológico."""
    global _ultimo_sello
    with _lock:
        ahora = datetime.now()
        if ahora <= _ultimo_sello:
            ahora = _ultimo_sello + timedelta(microseconds=1)
        _ultimo_sello = ahora
        return ahora.strftime("%Y%m%d-%H%M%S-%f")


def _unique(path: Path) -> Path:
    """Nunca sobrescribe un archivo existente."""
    if not path.exists():
        return path
    for n in range(2, 1000):
        candidato = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not candidato.exists():
            return candidato
    raise OSError("No se pudo crear un nombre de archivo único.")


def _db_file(conn):
    for fila in conn.execute("PRAGMA database_list"):
        if fila[1] == "main":
            return fila[2] or None
    return None


def _es_la_base_en_uso(conn, path) -> bool:
    actual = _db_file(conn)
    return bool(actual) and Path(actual).resolve() == Path(path).resolve()


def _uri_lectura(path) -> str:
    return f"{Path(path).resolve().as_uri()}?mode=ro"


def backup_to(conn, path) -> Path:
    """Copia consistente de la base de datos a un archivo (sin cerrar el programa)."""
    path = Path(path)
    if _es_la_base_en_uso(conn, path):
        raise ValueError("No se puede guardar la copia sobre la base de datos en uso.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    destino = sqlite3.connect(str(path))
    ok = False
    try:
        conn.backup(destino)
        ok = True
    finally:
        destino.close()
        if not ok:
            path.unlink(missing_ok=True)
    return path


def create_backup(conn, folder=None, prefix: str = MANUAL_PREFIX) -> Path:
    carpeta = Path(folder) if folder else backups_dir()
    carpeta.mkdir(parents=True, exist_ok=True)
    return backup_to(conn, _unique(carpeta / f"{prefix}{_stamp()}.db"))


def validate_backup(path) -> None:
    """Comprueba que el archivo sea una copia válida de este programa."""
    path = Path(path)
    if not path.is_file():
        raise ValueError("El archivo no existe.")
    con = sqlite3.connect(_uri_lectura(path), uri=True)
    try:
        try:
            integridad = con.execute("PRAGMA integrity_check").fetchone()[0]
            tablas = {f[0] for f in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.DatabaseError as e:
            raise ValueError("El archivo no es una copia de seguridad válida.") from e
    finally:
        con.close()
    if integridad != "ok":
        raise ValueError("La copia de seguridad está dañada.")
    if REQUIRED_TABLES - tablas:
        raise ValueError("El archivo no es una copia de este programa.")
    comprobar_compatible(path)


def restore_backup(conn, path, safety_folder=None) -> Path:
    """Reemplaza los datos actuales por los de la copia. Antes guarda una copia de
    seguridad de los datos actuales y devuelve su ruta."""
    if _es_la_base_en_uso(conn, path):
        raise ValueError("Seleccione una copia distinta de la base de datos en uso.")
    validate_backup(path)
    seguridad = create_backup(conn, safety_folder, SAFETY_PREFIX)
    origen = sqlite3.connect(_uri_lectura(path), uri=True)
    try:
        origen.backup(conn)
    finally:
        origen.close()
    return seguridad


def list_backups(folder=None) -> list[Path]:
    """Copias manuales y automáticas, de la más reciente a la más antigua."""
    carpeta = Path(folder) if folder else backups_dir()
    archivos = [p for p in carpeta.glob("*.db")
                if p.name.startswith((MANUAL_PREFIX, AUTO_PREFIX))]
    return sorted(archivos, key=lambda p: p.stat().st_mtime, reverse=True)


def last_backup_time(folder=None):
    copias = list_backups(folder)
    return datetime.fromtimestamp(copias[0].stat().st_mtime) if copias else None


def _rotar(carpeta: Path, keep: int, nueva: Path) -> None:
    """Conserva las `keep` copias automáticas más recientes.
    Nunca borra la copia que se acaba de crear (`nueva`)."""
    otras = sorted((p for p in carpeta.glob(f"{AUTO_PREFIX}*.db") if p != nueva),
                   key=lambda p: p.name)
    sobran = len(otras) - max(keep - 1, 0)
    for viejo in otras[:max(sobran, 0)]:
        try:
            viejo.unlink()
        except OSError:
            pass


def auto_backup(conn, folder=None, min_hours: float = 20, keep: int = MAX_AUTO):
    """Crea una copia automática si la última tiene más de `min_hours` horas.
    Devuelve la ruta creada, o None si no hizo falta."""
    carpeta = Path(folder) if folder else backups_dir()
    if min_hours > 0:
        ultima = last_backup_time(carpeta)
        if ultima and datetime.now() - ultima < timedelta(hours=min_hours):
            return None
    ruta = create_backup(conn, carpeta, AUTO_PREFIX)
    _rotar(carpeta, keep, ruta)
    return ruta