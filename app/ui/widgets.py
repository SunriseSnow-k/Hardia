"""Componentes visuales reutilizables: chips de estado, barra de porcentaje, indicador de
etapas, paneles y utilidades de fechas en español."""
import html
from datetime import datetime

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from app.ui.styles import (ACCENT, MUTED, NEUTRAL_COLORS, PRIORITY_COLORS, STATUS_COLORS,
                           TRACK)

_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre")


# ---------------- fechas ----------------
def parse_fecha(valor) -> datetime | None:
    """'2026-10-06 09:15:00' o '2026-10-06T09:15:00' (o solo la fecha) -> datetime."""
    t = str(valor or "").strip().replace("T", " ")
    for fmt, largo in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(t[:largo], fmt)
        except ValueError:
            continue
    return None


def fecha_corta(valor, con_hora: bool = True) -> str:
    """'2026-10-06 09:15:00' -> '06/10/2026 09:15'. Si no se reconoce, se devuelve tal cual."""
    dt = parse_fecha(valor)
    if dt is None:
        return str(valor or "")
    return dt.strftime("%d/%m/%Y %H:%M" if con_hora and len(str(valor)) > 10 else "%d/%m/%Y")


def fecha_larga(dt: datetime) -> str:
    """'Martes 13 de octubre de 2026'."""
    texto = f"{_DIAS[dt.weekday()]} {dt.day} de {_MESES[dt.month - 1]} de {dt.year}"
    return texto[0].upper() + texto[1:]


def tiempo_transcurrido(valor, ahora: datetime | None = None) -> str:
    """Texto breve del tiempo desde `valor`: 'hace 40 min', 'hace 3 h', 'hace 2 días'
    o, si pasó más de una semana, 'el 06/10/2026'."""
    dt = parse_fecha(valor)
    if dt is None:
        return ""
    seg = ((ahora or datetime.now()) - dt).total_seconds()
    if seg < 60:
        return "hace un momento"
    minutos = int(seg // 60)
    if minutos < 60:
        return f"hace {minutos} min"
    horas = minutos // 60
    if horas < 24:
        return f"hace {horas} h"
    dias = horas // 24
    if dias < 7:
        return "hace 1 día" if dias == 1 else f"hace {dias} días"
    return f"el {dt:%d/%m/%Y}"


# ---------------- chips ----------------
def colores_de(texto: str) -> tuple[str, str]:
    return PRIORITY_COLORS.get(texto) or STATUS_COLORS.get(texto) or NEUTRAL_COLORS


def chip_css(fondo: str, color: str, grande: bool = False) -> str:
    pad, tam = ("6px 14px", "13px") if grande else ("2px 8px", "12px")
    return (f"background:{fondo}; color:{color}; border:none; border-radius:3px; "
            f"padding:{pad}; font-size:{tam}; font-weight:600;")


def chip_html(texto: str, fondo: str | None = None, color: str | None = None) -> str:
    """Chip para usar dentro de un QLabel con texto enriquecido."""
    if fondo is None:
        fondo, color = colores_de(texto)
    return (f'<span style="background:{fondo};color:{color};font-size:12px;font-weight:600">'
            f'&nbsp;{html.escape(texto)}&nbsp;</span>')


class ChipEstado(QLabel):
    """Rectángulo de radio 3 px con el estado escrito (nunca solo color)."""

    def __init__(self, texto: str = "", fondo: str | None = None, color: str | None = None,
                 grande: bool = False, parent=None):
        super().__init__(parent)
        self._grande = grande
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.set_estado(texto, fondo, color)

    def set_estado(self, texto: str, fondo: str | None = None, color: str | None = None):
        if fondo is None:
            fondo, color = colores_de(texto)
        self.setText(texto)
        self.setStyleSheet(chip_css(fondo, color, self._grande))


# ---------------- barra de porcentaje ----------------
class BarraPorcentaje(QWidget):
    """Carril gris con relleno de color y el número a la derecha ('83 %').
    Sin valor muestra el texto alternativo (por ejemplo 'Sin medición')."""

    def __init__(self, valor: float | None = None, color: str = ACCENT, alto: int = 8,
                 texto_alt: str = "Sin medición", sufijo: str = " %", maximo: float = 100,
                 mostrar_numero: bool = True, parent=None):
        super().__init__(parent)
        self._alto = max(6, min(int(alto), 10))
        self._maximo = maximo
        self._sufijo = sufijo
        self._mostrar = mostrar_numero
        self._valor, self._color, self._alt = None, color, texto_alt
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.set_valor(valor, color, texto_alt)

    def set_valor(self, valor: float | None, color: str | None = None, texto_alt: str | None = None):
        self._valor = None if valor is None else float(valor)
        if color:
            self._color = color
        if texto_alt is not None:
            self._alt = texto_alt
        self.setAccessibleName(self.texto())
        self.setToolTip(self.texto())
        self.update()

    def valor(self) -> float | None:
        return self._valor

    def texto(self) -> str:
        return self._alt if self._valor is None else f"{round(self._valor)}{self._sufijo}"

    def sizeHint(self) -> QSize:
        return QSize(160, 20)

    def minimumSizeHint(self) -> QSize:
        return QSize(80, 20)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fm = self.fontMetrics()
        if self._valor is None:
            p.setPen(QColor(MUTED))
            p.drawText(self.rect(), Qt.AlignVCenter | Qt.AlignLeft, self._alt)
            return
        texto = self.texto()
        ancho_num = (fm.horizontalAdvance("100 %") + 8) if self._mostrar else 0
        carril = QRectF(0, (self.height() - self._alto) / 2, max(10, self.width() - ancho_num), self._alto)
        radio = self._alto / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(TRACK))
        p.drawRoundedRect(carril, radio, radio)
        prop = max(0.0, min(self._valor / self._maximo, 1.0)) if self._maximo else 0
        if prop > 0:
            relleno = QRectF(carril.x(), carril.y(), max(self._alto, carril.width() * prop), self._alto)
            p.setBrush(QColor(self._color))
            p.drawRoundedRect(relleno, radio, radio)
        if self._mostrar:
            p.setPen(QColor("#1b2430"))
            fuente = p.font()
            fuente.setBold(True)
            p.setFont(fuente)
            p.drawText(QRectF(carril.right() + 8, 0, ancho_num - 8, self.height()),
                       Qt.AlignVCenter | Qt.AlignRight, texto)


# ---------------- indicador de etapas ----------------
class IndicadorEtapas(QWidget):
    """Recibido → En diagnóstico → Listo → Entregado, con la etapa actual resaltada."""

    def __init__(self, etapas, actual: str = "", parent=None):
        super().__init__(parent)
        self.etapas = list(etapas)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._labels = []
        for i, e in enumerate(self.etapas):
            if i:
                flecha = QLabel("→")
                flecha.setObjectName("Muted")
                lay.addWidget(flecha)
            lbl = QLabel()
            self._labels.append(lbl)
            lay.addWidget(lbl)
        lay.addStretch()
        self.set_actual(actual)

    def set_actual(self, actual: str):
        idx = self.etapas.index(actual) if actual in self.etapas else -1
        for i, (lbl, e) in enumerate(zip(self._labels, self.etapas)):
            if i < idx:
                lbl.setText(f"✓ {e}")
                lbl.setStyleSheet("color:#2f855a; font-size:13px;")
            elif i == idx:
                lbl.setText(f"● {e}")
                lbl.setStyleSheet(f"color:white; background:{ACCENT}; border-radius:3px; "
                                  "padding:3px 8px; font-size:13px; font-weight:600;")
            else:
                lbl.setText(f"○ {e}")
                lbl.setStyleSheet(f"color:{MUTED}; font-size:13px;")
        self.setAccessibleName(f"Etapa actual: {actual}")


# ---------------- contenedores ----------------
class AreaDesplazable(QScrollArea):
    """QScrollArea vertical que respeta la altura de los textos con salto de línea.

    Con setWidgetResizable(True), Qt no usa heightForWidth para la altura mínima del
    contenido y aplasta las etiquetas en lugar de mostrar la barra de desplazamiento.
    Aquí se calcula esa altura con el ancho visible cada vez que cambia el tamaño o el
    contenido."""

    def __init__(self, contenido: QWidget | None = None, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._pendiente = False
        if contenido is not None:
            self.setWidget(contenido)

    def setWidget(self, w: QWidget):
        super().setWidget(w)
        w.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.widget() and event.type() == QEvent.LayoutRequest and not self._pendiente:
            self._pendiente = True
            QTimer.singleShot(0, self, self._ajustar)  # con contexto: se cancela si el área se destruye
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ajustar()

    def _ajustar(self):
        self._pendiente = False
        w = self.widget()
        lay = w.layout() if w is not None else None
        if lay is None:
            return
        ancho = self.viewport().width()
        alto = lay.totalHeightForWidth(ancho) if lay.hasHeightForWidth() else lay.totalMinimumSize().height()
        alto = max(alto, lay.totalMinimumSize().height())
        if w.minimumHeight() != alto:
            w.setMinimumHeight(alto)


def panel(titulo: str | None = None, margen: int = 16) -> tuple[QFrame, QVBoxLayout]:
    """Panel blanco con borde y título de sección opcional."""
    f = QFrame()
    f.setObjectName("Panel")
    v = QVBoxLayout(f)
    v.setContentsMargins(margen, 14, margen, 14)
    v.setSpacing(8)
    if titulo:
        h = QLabel(titulo)
        h.setObjectName("SectionTitle")
        v.addWidget(h)
    return f, v


def campo(etiqueta: str, widget: QWidget) -> QWidget:
    """Etiqueta pequeña encima del control."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(3)
    lbl = QLabel(etiqueta)
    lbl.setObjectName("Muted")
    lbl.setBuddy(widget)
    v.addWidget(lbl)
    v.addWidget(widget)
    return w


def muted(texto: str = "", wrap: bool = True) -> QLabel:
    lbl = QLabel(texto)
    lbl.setObjectName("Muted")
    lbl.setWordWrap(wrap)
    return lbl


def cabecera(titulo: str, subtitulo: str = "") -> tuple[QVBoxLayout, QLabel, QLabel]:
    """Título de página (20 px) y subtítulo gris."""
    v = QVBoxLayout()
    v.setSpacing(2)
    t = QLabel(titulo)
    t.setObjectName("PageTitle")
    s = muted(subtitulo)
    s.setStyleSheet("font-size:13px;")
    v.addWidget(t)
    v.addWidget(s)
    return v, t, s


def ruta_cortable(ruta) -> str:
    """Ruta con cortes de línea permitidos después de cada barra (las rutas no tienen espacios)."""
    return str(ruta).replace("\\", "\\\u200b")


def lista_dato_valor(filas, columnas: int = 1) -> QWidget:
    """Lista 'dato — valor' en una cuadrícula (dato en gris, valor normal)."""
    w = QWidget()
    g = QGridLayout(w)
    g.setContentsMargins(0, 0, 0, 0)
    g.setHorizontalSpacing(12)
    g.setVerticalSpacing(6)
    for i, (dato, valor) in enumerate(filas):
        fila, col = divmod(i, columnas)
        a = muted(dato, wrap=False)
        a.setStyleSheet("font-size:13px;")
        a.setMinimumHeight(a.fontMetrics().height())
        b = QLabel(str(valor))
        # Solo los textos largos llevan salto de línea: en un QScrollArea, Qt calcula mal la
        # altura mínima de muchas etiquetas con salto y las aplasta.
        b.setWordWrap(len(str(valor)) > 50)
        b.setMinimumHeight(b.fontMetrics().height())
        b.setTextInteractionFlags(Qt.TextSelectableByMouse)
        g.addWidget(a, fila, col * 2, Qt.AlignTop)
        g.addWidget(b, fila, col * 2 + 1)
    for c in range(columnas):
        g.setColumnStretch(c * 2 + 1, 1)
    return w


def celda(principal: str, secundario: str = "", rico: bool = False, wrap: bool = False) -> QWidget:
    """Celda de tabla de dos líneas: dato principal y detalle en gris."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(8, 4, 8, 4)
    v.setSpacing(0)
    a = QLabel(principal)
    a.setWordWrap(wrap)
    if rico:
        a.setTextFormat(Qt.RichText)
    v.addWidget(a)
    if secundario:
        v.addWidget(muted(secundario, wrap=wrap))
    return w


def vaciar_tabla(tabla):
    """Quita filas y widgets de celda ocultándolos ya (deleteLater los destruye después)."""
    for r in range(tabla.rowCount()):
        for c in range(tabla.columnCount()):
            w = tabla.cellWidget(r, c)
            if w is not None:
                w.hide()
    tabla.clearContents()
    tabla.setRowCount(0)


def ajustar_alto_tabla(tabla):
    """Alto exacto para mostrar todas las filas sin barra interna (la página ya se desplaza)."""
    tabla.resizeRowsToContents()
    minimo = tabla.verticalHeader().defaultSectionSize()
    for r in range(tabla.rowCount()):
        tabla.setRowHeight(r, max(tabla.rowHeight(r), minimo))
    alto = tabla.horizontalHeader().height() + 2 * tabla.frameWidth()
    alto += sum(tabla.rowHeight(r) for r in range(tabla.rowCount()))
    tabla.setFixedHeight(alto + 2)


def item_medida(*textos: str) -> QTableWidgetItem:
    """Ítem vacío que solo indica el tamaño del texto más largo de la celda: así la columna
    toma el ancho correcto aunque el contenido visible sea un widget.

    No lleva texto: un texto "invisible" se volvía visible al seleccionar la fila (la regla
    QTableWidget::item:selected de la hoja de estilos cambia su color) y se pintaba debajo
    del widget, encimándose con los datos."""
    fm = QFontMetrics(_FUENTE_TABLA)
    texto = max(textos, key=len) + "    "
    item = QTableWidgetItem()
    item.setData(Qt.SizeHintRole, QSize(fm.horizontalAdvance(texto) + 16, fm.height() + 8))
    return item


_FUENTE_TABLA = QFont("Segoe UI")  # la misma que la hoja de estilos (QWidget, 14 px)
_FUENTE_TABLA.setPixelSize(14)


def color_estado(estado: str) -> str:
    """Color del texto de un estado (Buen estado, Revisar, Atención…)."""
    return colores_de(estado)[1]


def limpiar_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()  # se oculta ya: deleteLater lo destruye en el siguiente ciclo
            item.widget().deleteLater()
        elif item.layout():
            limpiar_layout(item.layout())
