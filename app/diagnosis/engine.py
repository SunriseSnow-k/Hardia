"""Motor de diagnóstico basado en reglas. Funciona sin Internet."""
import json
import operator
import re
import unicodedata
from pathlib import Path

RULES_PATH = Path(__file__).with_name("rules.json")
PRIORIDAD_ORDEN = {"Alta": 0, "Media": 1, "Baja": 2}
OPERADORES = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}
PESO_CONDICION = 1.5
MAX_CAUSAS = 5
AVISO = ("El resultado es una asistencia para el diagnóstico y debe ser validado "
         "por el técnico mediante pruebas.")


def normalizar(texto: str) -> str:
    """Minúsculas y sin acentos, para comparar textos."""
    t = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower().strip()


def _contiene(texto: str, palabra: str) -> bool:
    """True si `palabra` aparece al inicio de una palabra del texto (ya normalizado).
    Así "ram" no coincide con "programas", pero "calient" sí con "calienta"."""
    p = normalizar(palabra)
    return bool(p) and re.search(r"(?<![a-z0-9])" + re.escape(p), texto) is not None


def load_rules(path=RULES_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _evaluar(cond: dict, metrics: dict, summary: dict):
    """True / False, o None si el dato no está disponible o no es válido."""
    try:
        if "metric" in cond:
            valor = metrics.get(cond["metric"])
            if valor is None or isinstance(valor, bool):
                return None
            return OPERADORES[cond["op"]](float(valor), cond["value"])
        if "field" in cond:
            valor = summary.get(cond["field"])
            if not valor:
                return None
            return re.search(cond["regex"], str(valor), re.IGNORECASE) is not None
    except (TypeError, ValueError):
        return None
    return None


def _etiqueta_confianza(c: float) -> str:
    return "Alta" if c >= 0.7 else "Media" if c >= 0.45 else "Baja"


def _estado_general(causas: list, tiene_scan: bool) -> str:
    if not causas:
        return "SIN HALLAZGOS RELEVANTES" if tiene_scan else "DATOS INSUFICIENTES"
    if any(c["priority"] == "Alta" for c in causas):
        return "ATENCIÓN REQUERIDA"
    return "REVISIÓN RECOMENDADA"


def _dict(valor) -> dict:
    return valor if isinstance(valor, dict) else {}


def diagnose(problema: str, scan: dict | None = None, rules: list | None = None) -> dict:
    rules = rules if rules is not None else load_rules()
    scan = scan if isinstance(scan, dict) else None
    metrics = _dict(scan.get("metrics")) if scan else {}
    summary = _dict(scan.get("summary")) if scan else {}
    texto = normalizar(problema if isinstance(problema, str) else "")

    causas, detectados = [], set()
    for r in rules:
        sintomas = r.get("symptoms", [])
        s_hits = [s["name"] for s in sintomas
                  if any(_contiene(texto, k) for k in s["keywords"])]
        c_hits, c_posibles = [], 0
        for c in r.get("conditions", []):
            res = _evaluar(c, metrics, summary)
            if res is None:
                continue
            c_posibles += 1
            if res:
                c_hits.append(c["label"])

        posible = len(sintomas) + PESO_CONDICION * c_posibles
        if posible == 0:
            continue
        evidencia = len(s_hits) + len(c_hits)
        confianza = (len(s_hits) + PESO_CONDICION * len(c_hits)) / posible
        if evidencia < r.get("min_evidence", 1) or confianza < r.get("min_confidence", 0.3):
            continue

        detectados.update(s_hits)
        causas.append({
            "id": r["id"], "category": r["category"], "cause": r["cause"],
            "priority": r["priority"],
            "confidence": round(confianza, 2),
            "confidence_label": _etiqueta_confianza(confianza),
            "evidence": [f"Síntoma: {n}" for n in s_hits] + [f"Dato del equipo: {n}" for n in c_hits],
            "recommendations": list(r["recommendations"]),
        })

    causas.sort(key=lambda c: (PRIORIDAD_ORDEN.get(c["priority"], 9), -c["confidence"]))
    causas = causas[:MAX_CAUSAS]

    recomendaciones: list[str] = []
    for c in causas:
        for rec in c["recommendations"]:
            if rec not in recomendaciones:
                recomendaciones.append(rec)

    return {
        "status": _estado_general(causas, bool(scan)),
        "causes": causas,
        "recommendations": recomendaciones,
        "symptoms_detected": sorted(detectados),
        "has_scan": bool(scan),
        "disclaimer": AVISO,
    }
