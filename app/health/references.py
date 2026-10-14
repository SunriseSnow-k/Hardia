"""Base local de referencias de fábrica (sin Qt). Nunca inventa valores: si un modelo no
está en la base, la búsqueda devuelve None y la pantalla muestra "Sin referencia"."""
import json
import os
import re
from pathlib import Path

from app.paths import APP_NAME

PAQUETE = Path(__file__).with_name("references.json")
NOMBRE_TALLER = "references.json"  # copia editable del taller en %APPDATA%\SistemaDiagnostico


def ruta_taller() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home()))
    return base / APP_NAME / NOMBRE_TALLER


def ruta_activa() -> Path:
    """La copia del taller tiene prioridad sobre la que trae el programa."""
    r = ruta_taller()
    return r if r.is_file() else PAQUETE


def load_references(path=None) -> dict:
    """Carga y valida la base. Si la copia del taller está dañada se usa la del programa."""
    rutas = [Path(path)] if path else [ruta_activa(), PAQUETE]
    ultimo_error = None
    for r in rutas:
        try:
            data = json.loads(Path(r).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("formato no válido")
            data.setdefault("cpus", [])
            data.setdefault("discos_por_tipo", [])
            data.setdefault("cpu_puntajes", {"modelos": []})
            data["_ruta"] = str(r)
            return data
        except (OSError, ValueError) as e:
            ultimo_error = e
    raise ValueError(f"No se pudo leer la base de referencias: {ultimo_error}")


def _norm(texto: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\((r|tm)\)", "", str(texto or "").lower())).strip()


def _contiene_modelo(nombre: str, modelo: str) -> bool:
    """'Intel(R) Core(TM) i5-1135G7 @ 2.40GHz' contiene 'i5-1135G7' (y no 'i5-1135G' a secas)."""
    m = _norm(modelo)
    return bool(m) and re.search(r"(?<![a-z0-9])" + re.escape(m) + r"(?![a-z0-9])", _norm(nombre)) is not None


def find_cpu(references: dict, nombre_cpu: str) -> dict | None:
    for c in references.get("cpus", []):
        if isinstance(c, dict) and _contiene_modelo(nombre_cpu, c.get("modelo", "")):
            return c
    return None


def find_cpu_score(references: dict, nombre_cpu: str) -> dict | None:
    for c in (references.get("cpu_puntajes") or {}).get("modelos", []):
        if isinstance(c, dict) and c.get("ops_s") and _contiene_modelo(nombre_cpu, c.get("modelo", "")):
            return c
    return None


def find_disk_type(references: dict, disco: dict) -> dict | None:
    """Referencia por tipo de unidad. Exige que coincidan todos los datos que pide la entrada
    (tipo de medio, bus y rpm): un disco sin esos datos queda sin referencia."""
    for ref in references.get("discos_por_tipo", []):
        if not isinstance(ref, dict) or not ref.get("lectura_mb_s"):
            continue
        if ref.get("media") and ref["media"] != disco.get("media"):
            continue
        if ref.get("bus") and ref["bus"] != disco.get("bus"):
            continue
        if ref.get("rpm") and ref["rpm"] != disco.get("rpm"):
            continue
        return ref
    return None
