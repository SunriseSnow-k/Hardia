"""Archivo .diag: guarda e importa un escaneo (para llevarlo en un USB)."""
import json
import re
from pathlib import Path

import psutil

FORMAT = "SD-DIAG"
VERSION = 1
_DANADO = "El archivo está incompleto o dañado."


def save_scan(data: dict, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_scan(path) -> dict:
    """Carga y valida un archivo .diag. Lanza ValueError si no es válido."""
    texto = Path(path).read_text(encoding="utf-8")
    data = json.loads(texto)
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("El archivo no es un escaneo válido del sistema.")
    if not isinstance(data.get("summary"), dict) or not isinstance(data.get("components"), list):
        raise ValueError(_DANADO)
    if not all(isinstance(c, dict) for c in data["components"]):
        raise ValueError(_DANADO)
    if not isinstance(data.setdefault("metrics", {}), dict):
        raise ValueError(_DANADO)
    return data


def default_filename(data: dict) -> str:
    base = data.get("summary", {}).get("serial") or data.get("host") or "equipo"
    base = re.sub(r"[^A-Za-z0-9_-]", "_", base)
    fecha = str(data.get("scanned_at", ""))[:10] or "sin-fecha"
    return f"{base}_{fecha}.diag"


def removable_drives() -> list[Path]:
    """Unidades extraíbles (USB) detectadas por Windows."""
    unidades = []
    for p in psutil.disk_partitions(all=False):
        if "removable" in p.opts.lower():
            unidades.append(Path(p.mountpoint))
    return unidades


def find_usb_scans() -> list[Path]:
    """Archivos .diag en la raíz de las unidades USB conectadas."""
    archivos: list[Path] = []
    for unidad in removable_drives():
        try:
            archivos += sorted(unidad.glob("*.diag"))
        except OSError:
            pass
    return archivos