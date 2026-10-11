"""Generación de reportes en PDF (ReportLab). Funciona sin Internet."""
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

from app.diagnosis.engine import diagnose

AZUL = colors.HexColor("#1f6f8b")
GRIS = colors.HexColor("#66727f")
LINEA = colors.HexColor("#d9dfe5")
TEXTO = colors.HexColor("#1b2430")
PRIO_HEX = {"Alta": "#c0392b", "Media": "#b7791f", "Baja": "#2f855a"}
URGENCIA = {"Alta": "Conviene atenderlo pronto", "Media": "Conviene revisarlo",
            "Baja": "No es urgente"}
ESTADO_SCAN = {"ok": "Leído", "warn": "Parcial o no disponible", "error": "No se pudo leer"}


# ---------------- Datos ----------------
def load_report_data(repo, code: str) -> dict:
    """Reúne todo lo necesario para un reporte. Si el caso no tiene diagnóstico
    guardado, se calcula con las reglas en ese momento."""
    caso = repo.get_case(code)
    if caso is None:
        raise ValueError(f"No existe el caso {code}.")
    scan = repo.get_scan(code)
    d = repo.get_diagnosis(code)
    if d:
        result, method, fecha, saved = d["result"], d["method"], d["created_at"], True
    else:
        result, method, fecha, saved = diagnose(caso["problem"], scan), "Reglas", None, False
    return {
        "caso": caso, "scan": scan, "result": result, "method": method,
        "diag_date": fecha, "diag_saved": saved,
        "business": repo.get_setting("business_name", "Mi taller"),
        "phone": repo.get_setting("business_phone", ""),
    }


def client_summary(result: dict, max_items: int = 3) -> list[tuple[str, str]]:
    """Causas en lenguaje simple para el cliente: (causa, urgencia)."""
    return [(c["cause"], URGENCIA.get(c["priority"], ""))
            for c in result.get("causes", [])[:max_items]]


# ---------------- Estilos y utilidades ----------------
def _styles() -> dict:
    base = dict(fontName="Helvetica", fontSize=10, leading=14, textColor=TEXTO)

    def est(nombre, **extra):
        return ParagraphStyle(nombre, **{**base, **extra})

    return {
        "body": est("body"),
        "cell": est("cell", fontSize=9, leading=12),
        "small": est("small", fontSize=8.5, leading=11, textColor=GRIS),
        "label": est("label", fontSize=9, leading=12, textColor=GRIS, fontName="Helvetica-Bold"),
        "head": est("head", fontSize=9, leading=12, textColor=colors.white, fontName="Helvetica-Bold"),
        "biz": est("biz", fontSize=10, textColor=GRIS, fontName="Helvetica-Bold"),
        "h1": est("h1", fontSize=17, leading=21, textColor=AZUL, fontName="Helvetica-Bold"),
        "h2": est("h2", fontSize=12, leading=16, fontName="Helvetica-Bold",
                  spaceBefore=12, spaceAfter=5),
    }


def _e(texto) -> str:
    return escape(str(texto if texto is not None else ""))


def _p(texto, estilo, raw: bool = False) -> Paragraph:
    return Paragraph(texto if raw else _e(texto), estilo)


def _prio(p: str) -> str:
    return f'<font color="{PRIO_HEX.get(p, "#1b2430")}"><b>{_e(p)}</b></font>'


def _kv(filas, st) -> Table:
    datos = [[_p(k, st["label"]), _p(v or "—", st["cell"])] for k, v in filas]
    t = Table(datos, colWidths=[40 * mm, 130 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINEA),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _tabla(encabezado, filas, anchos_mm, st) -> Table:
    datos = [[_p(h, st["head"]) for h in encabezado]] + filas
    t = Table(datos, colWidths=[a * mm for a in anchos_mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("GRID", (0, 0), (-1, -1), 0.4, LINEA),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _aviso(texto: str, st) -> Table:
    t = Table([[_p(texto, st["cell"])]], colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbf0d9")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#b7791f")),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _cabecera(data: dict, st: dict, titulo: str) -> list:
    caso = data["caso"]
    return [
        _p(data["business"], st["biz"]), _p(titulo, st["h1"]), Spacer(1, 4 * mm),
        _kv([("Caso", caso["code"]),
             ("Fecha de ingreso", caso["created_at"][:16]),
             ("Reporte generado", datetime.now().strftime("%d/%m/%Y %H:%M"))], st),
    ]


def _pie(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(LINEA)
    canvas.line(20 * mm, 14 * mm, A4[0] - 20 * mm, 14 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GRIS)
    canvas.drawString(20 * mm, 10 * mm, "Sistema Inteligente Offline · Documento generado localmente")
    canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Página {doc.page}")
    canvas.restoreState()


def _construir(story: list, path, titulo: str, autor: str) -> None:
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm, title=titulo, author=autor or "Sistema Inteligente Offline",
    )
    doc.build(story, onFirstPage=_pie, onLaterPages=_pie)


# ---------------- Reporte técnico ----------------
def build_technical(data: dict, path, tech_id: str = "") -> None:
    st = _styles()
    caso, scan, res = data["caso"], data["scan"], data["result"]
    story = _cabecera(data, st, "Reporte técnico de diagnóstico")

    story.append(_p("Cliente y equipo", st["h2"]))
    story.append(_kv([
        ("Cliente", caso["cliente"]), ("Teléfono", caso["phone"]),
        ("Equipo", caso["equipo"]), ("N.º de serie", caso["serial"]),
        ("Estado del caso", caso["status"]), ("Prioridad", caso["priority"]),
    ], st))

    story.append(_p("Problema reportado", st["h2"]))
    story.append(_p(caso["problem"], st["body"]))

    story.append(_p("Datos del equipo (escaneo)", st["h2"]))
    if scan and scan.get("components"):
        filas = [[_p(c.get("name", "?"), st["cell"]), _p(c.get("detail", ""), st["cell"]),
                  _p(ESTADO_SCAN.get(c.get("status", "ok"), ""), st["cell"])]
                 for c in scan["components"]]
        story.append(_tabla(["Componente", "Detalle", "Estado"], filas, [35, 100, 35], st))
        story.append(Spacer(1, 1.5 * mm))
        fecha = str(scan.get("scanned_at", "")).replace("T", " ")[:16]
        story.append(_p(f"Escaneado el {fecha}", st["small"]))
    else:
        story.append(_p("Este caso no tiene escaneo de hardware.", st["small"]))

    story.append(_p("Resultado del diagnóstico", st["h2"]))
    origen = (f'Diagnóstico guardado el {data["diag_date"][:16]}.' if data["diag_saved"]
              else "El diagnóstico se calculó al generar este reporte (no se había guardado).")
    story.append(_p(f'Estado general: <b>{_e(res.get("status", ""))}</b> · '
                    f'Método de análisis: {_e(data["method"])}', st["body"], raw=True))
    story.append(_p(origen, st["small"]))
    story.append(Spacer(1, 2 * mm))
    causas = res.get("causes", [])
    if causas:
        filas = []
        for i, c in enumerate(causas, 1):
            ev = "; ".join(c.get("evidence", []))
            filas.append([
                _p(str(i), st["cell"]), _p(c["cause"], st["cell"]),
                _p(_prio(c["priority"]), st["cell"], raw=True),
                _p(f'{c.get("confidence_label", "")} ({round(c.get("confidence", 0) * 100)} %)', st["cell"]),
                _p(ev, st["cell"]),
            ])
        story.append(_tabla(["N.º", "Posible causa", "Prioridad", "Confianza", "Evidencia"],
                            filas, [9, 52, 20, 22, 67], st))
    else:
        story.append(_p("No se identificaron causas con los datos disponibles.", st["body"]))

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

    story.append(Spacer(1, 5 * mm))
    story.append(KeepTogether([
        _aviso(res.get("disclaimer", "El resultado es una asistencia y debe ser validado por el técnico."), st),
        Spacer(1, 12 * mm),
        _p("Técnico responsable: ______________________________", st["body"]),
        _p(f"ID de técnico: {tech_id or '—'}", st["small"]),
    ]))
    _construir(story, path, f'Reporte técnico {caso["code"]}', tech_id)


# ---------------- Reporte para el cliente ----------------
def build_client(data: dict, path, tech_id: str = "") -> None:
    st = _styles()
    caso, res = data["caso"], data["result"]
    story = _cabecera(data, st, "Informe de revisión de su equipo")

    story.append(Spacer(1, 4 * mm))
    story.append(_p(f'Estimado/a {caso["cliente"] or "cliente"}:', st["body"]))
    story.append(Spacer(1, 2 * mm))
    story.append(_p("Gracias por confiarnos su equipo. Este es el resumen de nuestra revisión.", st["body"]))
    story.append(Spacer(1, 3 * mm))
    story.append(_kv([("Equipo", caso["equipo"]), ("N.º de serie", caso["serial"])], st))

    story.append(_p("Lo que nos comentó", st["h2"]))
    story.append(_p(caso["problem"], st["body"]))

    story.append(_p("Lo que encontramos", st["h2"]))
    hallazgos = client_summary(res)
    if hallazgos:
        story.append(_p("Estas son las causas más probables de la falla:", st["body"]))
        for causa, urgencia in hallazgos:
            story.append(_p(f"• <b>{_e(causa)}</b> — {_e(urgencia)}", st["body"], raw=True))
        story.append(Spacer(1, 1 * mm))
        story.append(_p("Se trata de posibles causas: nuestro técnico las confirmará con pruebas.", st["small"]))
    else:
        story.append(_p("Todavía no identificamos una causa con los datos disponibles. "
                        "Necesitamos revisar el equipo con más detalle en el taller.", st["body"]))

    recs = res.get("recommendations", [])[:5]
    if recs:
        story.append(_p("Lo que recomendamos", st["h2"]))
        for i, r in enumerate(recs, 1):
            story.append(_p(f"{i}. {r}", st["body"]))

    contacto = data["business"] + (f' · Teléfono: {data["phone"]}' if data["phone"] else "")
    story.append(Spacer(1, 6 * mm))
    story.append(KeepTogether([
        _aviso("Este informe es una orientación y no incluye precios ni plazos. "
               "Nos comunicaremos con usted para acordarlos antes de realizar cualquier trabajo.", st),
        Spacer(1, 6 * mm),
        _p("Atentamente,", st["body"]),
        _p(contacto, st["body"]),
        _p(f"Técnico: {tech_id or '—'}", st["small"]),
    ]))
    _construir(story, path, f'Informe para el cliente {caso["code"]}', tech_id)