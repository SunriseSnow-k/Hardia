from datetime import datetime
from pathlib import Path

from app.paths import reports_dir
from .pdf import build_client, build_order, build_technical, load_order_data, load_report_data

KINDS = {"tecnico": "Técnico", "cliente": "Cliente", "orden": "Orden de servicio"}
BUILDERS = {"tecnico": (load_report_data, build_technical), "cliente": (load_report_data, build_client),
            "orden": (load_order_data, build_order)}


def _unico(path: Path) -> Path:
    """Nunca sobrescribe un archivo existente (puede estar abierto en un visor)."""
    if not path.exists():
        return path
    for n in range(2, 1000):
        candidato = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not candidato.exists():
            return candidato
    raise OSError("No se pudo crear un nombre de archivo único.")


def generate_report(repo, reports_repo, code: str, kind: str, tech_id: str = "",
                    out_dir=None) -> Path:
    """Genera el PDF de un caso, lo registra y devuelve su ruta."""
    if kind not in KINDS:
        raise ValueError("Tipo de reporte no válido.")
    cargar, construir = BUILDERS[kind]
    data = cargar(repo, code)
    carpeta = Path(out_dir) if out_dir else reports_dir()
    carpeta.mkdir(parents=True, exist_ok=True)
    path = _unico(carpeta / f"{code}_{kind}_{datetime.now():%Y%m%d-%H%M%S}.pdf")
    construir(data, path, tech_id)
    reports_repo.add(code, kind, str(path))
    return path