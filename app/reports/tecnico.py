"""Reporte técnico de diagnóstico (PDF)."""

from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Spacer

from . import base
from .base import _aviso, _e, _fecha, _kv, _p, _prio, _styles, _tabla
from .secciones import _cabecera, _seccion_cambios, _seccion_inventario, _seccion_notas, _seccion_salud


def build_technical(data: dict, path, tech_id: str = "") -> None:
    st = _styles()
    caso, res = data["caso"], data["result"]
    story = _cabecera(data, st, "Reporte técnico de diagnóstico")

    story.append(_p("Cliente y equipo", st["h2"]))
    story.append(_kv([
        ("Cliente", caso["cliente"]), ("Documento", data["doc_id"]), ("Teléfono", caso["phone"]),
        ("Equipo", caso["equipo"]), ("N.º de serie", caso["serial"]),
        ("Estado del caso", caso["status"]), ("Prioridad", caso["priority"]),
    ], st))

    story.append(_p("Problema reportado", st["h2"]))
    story.append(_p(caso["problem"], st["body"]))

    story += _seccion_inventario(data, st)
    story += _seccion_cambios(data, st)
    story += _seccion_salud(data, st)

    bloque = [_p("Resultado del diagnóstico", st["h2"])]
    origen = (f'Diagnóstico guardado el {_fecha(data["diag_date"])}.' if data["diag_saved"]
              else "El diagnóstico se calculó al generar este reporte (no se había guardado).")
    bloque.append(_p(f'Estado general: <b>{_e(res.get("status", ""))}</b> · '
                     f'Método de análisis: {_e(data["method"])}', st["body"], raw=True))
    bloque.append(_p(origen, st["small"]))
    bloque.append(Spacer(1, 2 * mm))
    causas = res.get("causes", [])
    if causas:
        filas = []
        for i, c in enumerate(causas, 1):
            filas.append([
                _p(str(i), st["cell"]), _p(c["cause"], st["cell"]),
                _p(_prio(c["priority"]), st["cell"], raw=True),
                _p(f'{c.get("confidence_label", "")} ({round(c.get("confidence", 0) * 100)} %)', st["cell"]),
                _p("; ".join(c.get("evidence", [])), st["cell"]),
            ])
        bloque.append(_tabla(["N.º", "Posible causa", "Prioridad", "Confianza", "Evidencia"],
                             filas, [9, 52, 20, 22, 67], st))
    else:
        bloque.append(_p("No se identificaron causas con los datos disponibles.", st["body"]))
    story.append(KeepTogether(bloque))

    recs = res.get("recommendations", [])
    if recs:
        story.append(_p("Recomendaciones", st["h2"]))
        for i, r in enumerate(recs, 1):
            story.append(_p(f"{i}. {r}", st["body"]))

    if res.get("ai_analysis"):
        story.append(_p("Análisis de IA local (asistencia)", st["h2"]))
        story.append(_p(res["ai_analysis"], st["body"]))
        if res.get("ai_model"):
            story.append(_p(f'Modelo local utilizado: {res["ai_model"]}', st["small"]))

    story.append(_p("Notas del caso", st["h2"]))
    if data["notes"]:
        story += _seccion_notas(data["notes"], st)
    else:
        story.append(_p("No hay notas registradas.", st["small"]))

    story.append(Spacer(1, 5 * mm))
    story.append(KeepTogether([
        _aviso(res.get("disclaimer", "El resultado es una asistencia y debe ser validado por el técnico."), st),
        Spacer(1, 12 * mm),
        _p("Técnico responsable: ______________________________", st["body"]),
        _p(f"ID de técnico: {tech_id or '—'}", st["small"]),
    ]))
    base._construir(story, path, f'Reporte técnico {caso["code"]}', tech_id, caso["code"])
