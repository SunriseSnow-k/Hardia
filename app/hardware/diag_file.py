"""Archivo .diag: guarda e importa un escaneo (para llevarlo en un USB)."""
import contextlib
import json
import logging
import re
import sys
from pathlib import Path

import psutil

log = logging.getLogger(__name__)

FORMAT = "SD-DIAG"
VERSION = 2  # 2 = incluye inventario y disponibilidad; los archivos de versión 1 se siguen leyendo
_DANADO = "El archivo está incompleto o dañado."
# El colector portátil guarda sus escaneos en <unidad>\Colector\Resultados
CARPETA_COLECTOR = "Colector"
CARPETA_RESULTADOS = "Resultados"


def save_scan(data: dict, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_scan(path) -> dict:
    """Carga y valida un archivo .diag (versión 1 o 2). Lanza ValueError si no es válido."""
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
    for clave in ("inventory", "availability", "benchmark"):
        if clave in data and not isinstance(data[clave], dict):
            raise ValueError(_DANADO)
    return data


def default_filename(data: dict) -> str:
    base = data.get("summary", {}).get("serial") or data.get("host") or "equipo"
    base = re.sub(r"[^A-Za-z0-9_-]", "_", base)
    fecha = str(data.get("scanned_at", ""))[:10] or "sin-fecha"
    return f"{base}_{fecha}.diag"


def removable_drives() -> list[Path]:
    """Unidades extraíbles (USB) conectadas: letras de unidad en Windows, puntos de montaje en Linux."""
    if sys.platform != "win32":
        from .linux import montar_extraibles, unidades_extraibles
        try:
            montar_extraibles()  # Linux: las memorias conectadas sin abrir no tienen carpeta todavía
        except Exception:
            log.warning("No se pudieron montar las memorias USB", exc_info=True)
        return [Path(m) for m in unidades_extraibles()]
    unidades = []
    for p in psutil.disk_partitions(all=False):
        if "removable" in p.opts.lower():
            unidades.append(Path(p.mountpoint))
    return unidades


def find_usb_scans() -> list[Path]:
    """Archivos .diag de las unidades USB conectadas: los del colector (Colector\\Resultados) y
    los guardados en la raíz. Los más recientes primero."""
    archivos: list[Path] = []
    for unidad in removable_drives():
        for carpeta in (unidad / CARPETA_COLECTOR / CARPETA_RESULTADOS, unidad):
            with contextlib.suppress(OSError):
                archivos += carpeta.glob("*.diag")

    def fecha(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0
    return sorted(archivos, key=fecha, reverse=True)
