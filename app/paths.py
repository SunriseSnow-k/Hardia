import os
from pathlib import Path

APP_NAME = "SistemaDiagnostico"


def data_dir() -> Path:
    """C:\\Users\\<usuario>\\AppData\\Roaming\\SistemaDiagnostico"""
    base = Path(os.environ.get("APPDATA", Path.home()))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "diagnostico.db"


def reports_dir() -> Path:
    """Carpeta donde se guardan los reportes PDF."""
    path = data_dir() / "Reportes"
    path.mkdir(parents=True, exist_ok=True)
    return path