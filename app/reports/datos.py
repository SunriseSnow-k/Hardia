"""Datos de los reportes técnico y para el cliente: salen de la misma fuente (última captura,
diagnóstico guardado y notas). Nunca se inventan datos: lo que no se pudo leer aparece con su motivo."""


from app.db.clients_repo import ClientsRepository
from app.db.hardware_repo import HardwareRepository
from app.db.health_repo import HealthRepository
from app.db.notes_repo import NotesRepository
from app.diagnosis.engine import diagnose
from app.hardware.inventory import CATEGORIAS, OK, compare_captures, inventory_rows


def _agrupar(filas: list[dict]) -> tuple[list, list]:
    """Separa el inventario en (categorías con datos, datos no disponibles)."""
    orden = [t for _k, t in CATEGORIAS]
    grupos: dict[str, list] = {}
    faltan = []
    for f in filas:
        if f["status"] == OK:
            grupos.setdefault(f["category"], []).append(f)
        else:
            faltan.append(f)
    claves = sorted(grupos, key=lambda c: orden.index(c) if c in orden else len(orden))
    return [(c, grupos[c]) for c in claves], faltan


def load_report_data(repo, code: str) -> dict:
    """Reúne todo lo necesario para ambos reportes. Si el caso no tiene diagnóstico
    guardado, se calcula con las reglas en ese momento (y así se indica)."""
    caso = repo.get_case(code)
    if caso is None:
        raise ValueError(f"No existe el caso {code}.")
    hw = HardwareRepository(repo)
    capturas = hw.captures_for_case(code)
    captura = hw.get_capture(capturas[0]["id"]) if capturas else None
    scan = captura["payload"] if captura else repo.get_scan(code)
    if not isinstance(scan, dict):
        scan = None

    anterior, cambios = None, []
    eq = repo.equipment_id_of_case(code)
    previa = hw.latest_capture(eq, exclude_case=code)
    if previa and scan and isinstance(previa.get("payload"), dict):
        anterior = {"case_code": previa["case_code"], "captured_at": previa["captured_at"]}
        cambios = compare_captures(previa["payload"], scan)

    d = repo.get_diagnosis(code)
    if d:
        result, method, fecha, saved = d["result"], d["method"], d["created_at"], True
    else:
        result, method, fecha, saved = diagnose(caso["problem"], scan), "Reglas", None, False

    filas = inventory_rows(scan) if scan else []
    categorias, no_disponible = _agrupar(filas)
    hr = HealthRepository(repo)
    try:  # mismos datos que la pantalla Salud del equipo; aquí no se guarda una evaluación nueva
        sal = hr.evaluate_case(code, guardar=False)
        salud = {"resultado": sal["resultado"], "benchmark": sal.get("benchmark"),
                 "incluidos": hr.included_for_case(code)}
    except Exception as e:  # la salud nunca debe impedir generar el reporte
        salud = {"resultado": None, "benchmark": None, "incluidos": [], "error": str(e)}
    return {
        "caso": caso, "doc_id": ClientsRepository(repo).doc_for_case(code),
        "scan": scan,
        "capture": ({"id": captura["id"], "captured_at": captura["captured_at"],
                     "source": captura["source"], "source_file": captura["source_file"],
                     "count": len(capturas)} if captura else None),
        "categories": categorias, "unavailable": no_disponible,
        "previous": anterior, "changes": cambios,
        "result": result, "method": method, "diag_date": fecha, "diag_saved": saved,
        "notes": [dict(n) for n in NotesRepository(repo).for_case(code)],
        "health": salud,
        "business": repo.get_setting("business_name", "Mi taller"),
        "phone": repo.get_setting("business_phone", ""),
    }
