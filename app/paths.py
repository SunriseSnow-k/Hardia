import os
import sys
from pathlib import Path

APP_NAME = "SistemaDiagnostico"
# Variable de entorno con la carpeta base de los datos (las pruebas la cambian por una temporal)
VAR_DATOS = "APPDATA" if sys.platform == "win32" else "XDG_DATA_HOME"


def _base_datos() -> Path:
    otra = os.environ.get(VAR_DATOS)
    if otra:
        return Path(otra)
    if sys.platform == "win32":
        return Path.home()
    return Path.home() / ".local" / "share"  # estándar XDG


def data_dir() -> Path:
    """Windows: C:\\Users\\<usuario>\\AppData\\Roaming\\SistemaDiagnostico
    Linux: ~/.local/share/SistemaDiagnostico"""
    path = _base_datos() / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "diagnostico.db"


def reports_dir() -> Path:
    """Carpeta donde se guardan los reportes PDF."""
    path = data_dir() / "Reportes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backups_dir() -> Path:
    """Carpeta donde se guardan las copias de seguridad."""
    path = data_dir() / "Copias"
    path.mkdir(parents=True, exist_ok=True)
    return path

def recurso(*partes: str) -> Path:
    """Archivo incluido con el programa (app/assets, …), también cuando está empaquetado."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base.joinpath("app", *partes)
