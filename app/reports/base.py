"""Piezas comunes de los PDF: colores, estilos, tablas, fechas y el pie con 'Página X de N'."""
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

AZUL = colors.HexColor("#1f6f8b")


AZUL_CLARO = colors.HexColor("#e1f0f5")


GRIS = colors.HexColor("#66727f")


LINEA = colors.HexColor("#d9dfe5")


TEXTO = colors.HexColor("#1b2430")


PRIO_HEX = {"Alta": "#c0392b", "Media": "#b7791f", "Baja": "#2f855a"}


ESTADO_HEX = {"Atención": "#c0392b", "Revisar": "#b7791f", "Buen estado": "#2f855a", "Sin referencia": "#5f6b77"}


ANCHO = 170  # mm útiles en A4 con márgenes de 20 mm


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v) -> list:
    return v if isinstance(v, list) else []


def _fecha(valor, largo: int = 16) -> str:
    """'2026-10-06T09:15:00' -> '06/10/2026 09:15' (largo 10 -> solo la fecha).
    Si el texto no tiene el formato esperado se muestra tal cual, recortado."""
    t = str(valor or "").replace("T", " ")
    try:
        dt = datetime.strptime(t[:16], "%Y-%m-%d %H:%M") if len(t) >= 16 else datetime.strptime(t[:10], "%Y-%m-%d")
    except ValueError:
        return t[:largo]
    return dt.strftime("%d/%m/%Y" if largo <= 10 or len(t) < 16 else "%d/%m/%Y %H:%M")


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
        "cat": est("cat", fontSize=9.5, leading=12, textColor=AZUL, fontName="Helvetica-Bold"),
        "biz": est("biz", fontSize=10, textColor=GRIS, fontName="Helvetica-Bold"),
        "h1": est("h1", fontSize=17, leading=21, textColor=AZUL, fontName="Helvetica-Bold"),
        "h2": est("h2", fontSize=12, leading=16, fontName="Helvetica-Bold",
                  spaceBefore=12, spaceAfter=5, keepWithNext=1),
        "h3": est("h3", fontSize=10.5, leading=14, fontName="Helvetica-Bold",
                  spaceBefore=6, spaceAfter=2, keepWithNext=1),
    }


def _e(texto) -> str:
    return escape(str(texto if texto is not None else ""))


def _p(texto, estilo, raw: bool = False) -> Paragraph:
    return Paragraph(texto if raw else _e(texto), estilo)


def _prio(p: str) -> str:
    return f'<font color="{PRIO_HEX.get(p, "#1b2430")}"><b>{_e(p)}</b></font>'


def _kv(filas, st) -> Table:
    datos = [[_p(k, st["label"]), _p(v or "—", st["cell"])] for k, v in filas]
    t = Table(datos, colWidths=[40 * mm, (ANCHO - 40) * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINEA),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _estilo_tabla(extra=()) -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("GRID", (0, 0), (-1, -1), 0.4, LINEA),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        *extra,
    ])


def _tabla(encabezado, filas, anchos_mm, st) -> Table:
    datos = [[_p(h, st["head"]) for h in encabezado]] + filas
    t = Table(datos, colWidths=[a * mm for a in anchos_mm], repeatRows=1)
    t.setStyle(_estilo_tabla())
    return t


def _tabla_categoria(titulo: str, filas: list[dict], st) -> Table:
    """Tabla de una categoría: el título y el encabezado se repiten si cambia de página."""
    datos = [[_p(titulo, st["cat"]), ""],
             [_p("Dato", st["head"]), _p("Valor", st["head"])]]
    datos += [[_p(f["label"], st["cell"]), _p(f["value"], st["cell"])] for f in filas]
    t = Table(datos, colWidths=[52 * mm, (ANCHO - 52) * mm], repeatRows=2)
    t.setStyle(TableStyle([
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, 0), AZUL_CLARO),
        ("BACKGROUND", (0, 1), (-1, 1), AZUL),
        ("GRID", (0, 1), (-1, -1), 0.4, LINEA),
        ("BOX", (0, 0), (-1, 0), 0.4, LINEA),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _aviso(texto: str, st) -> Table:
    t = Table([[_p(texto, st["cell"])]], colWidths=[ANCHO * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbf0d9")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#b7791f")),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _canvas_numerado(pie: str):
    """Canvas que escribe 'Página X de N' (necesita conocer el total al final)."""

    class MMAE__Canvas(rl_canvas.Canvas):
        # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._estados = []

        def showPage(self):
            self._estados.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._estados)
            for estado in self._estados:
                self.__dict__.update(estado)
                self._pie(total)
                super().showPage()
            super().save()

        def _pie(self, total: int):
            self.saveState()
            self.setStrokeColor(LINEA)
            self.line(20 * mm, 14 * mm, A4[0] - 20 * mm, 14 * mm)
            self.setFont("Helvetica", 8)
            self.setFillColor(GRIS)
            self.drawString(20 * mm, 10 * mm, pie)
            self.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Página {self._pageNumber} de {total}")
            self.restoreState()

    return MMAE__Canvas


def _construir(story: list, path, titulo: str, autor: str, code: str) -> None:
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm, title=titulo,
        author=autor or "Hardia",
    )
    pie = f"Hardia · Caso {code} · Documento generado localmente"
    doc.build(story, canvasmaker=_canvas_numerado(pie))
