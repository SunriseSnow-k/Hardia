from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from app.db.repo import ESTADOS, Repository
from app.ui.widgets import ChipEstado, cabecera, fecha_larga, limpiar_layout, tiempo_transcurrido

ACTIVOS = ("Recibido", "En diagnóstico", "Listo")


def _clear(layout):
    limpiar_layout(layout)


def _texto_tiempo(row) -> str:
    """'Ingresó hace 40 min' o 'Reingreso · ingresó hace 2 h'."""
    hace = tiempo_transcurrido(row["created_at"])
    # sqlite3.Row: `in row` busca entre los valores, no entre las columnas; por eso se usa keys()
    reingreso = bool(row["reingreso"]) if "reingreso" in row.keys() else False  # noqa: SIM118
    if reingreso:
        return f"Reingreso · ingresó {hace}" if hace else "Reingreso"
    return f"Ingresó {hace}" if hace else ""


class CaseCard(QFrame):
    clicked = Signal(str)

    def __init__(self, row):
        super().__init__()
        self.code = row["code"]
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f'Abrir el caso {row["code"]}')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        arriba = QHBoxLayout()
        codigo = QLabel(row["code"])
        codigo.setObjectName("Code")
        arriba.addWidget(codigo)
        arriba.addStretch()
        arriba.addWidget(ChipEstado(row["priority"]))

        titulo = QLabel(row["equipo"])
        titulo.setStyleSheet("font-weight:600;")
        titulo.setWordWrap(True)
        sub = QLabel(f'{row["cliente"] or "Sin cliente"} · {row["problem"]}')
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#5f6b77; font-size:13px;")
        tiempo = QLabel(_texto_tiempo(row))
        tiempo.setObjectName("Muted")

        lay.addLayout(arriba)
        lay.addWidget(titulo)
        lay.addWidget(sub)
        lay.addWidget(tiempo)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.code)


class InicioPage(QWidget):
    open_case = Signal(str)
    new_intake = Signal()

    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(14)

        cab = QHBoxLayout()
        textos, _t, self.subtitulo = cabecera("Cola de trabajo")
        self.subtitulo.setWordWrap(False)
        btn = QPushButton("+ Nueva recepción")
        btn.setObjectName("Primary")
        btn.clicked.connect(self.new_intake.emit)
        cab.addLayout(textos)
        cab.addStretch()
        cab.addWidget(btn, alignment=Qt.AlignTop)
        root.addLayout(cab)

        contenedor = QWidget()
        contenedor.setObjectName("ScrollBody")
        self.board = QHBoxLayout(contenedor)
        self.board.setContentsMargins(0, 0, 0, 0)
        self.board.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(contenedor)
        root.addWidget(scroll, 1)

        self.refresh()

    def refresh(self):
        _clear(self.board)
        conteo = self.repo.count_by_status()
        activos = sum(conteo.get(e, 0) for e in ACTIVOS)
        listos = conteo.get("Listo", 0)
        self.subtitulo.setText(f"{fecha_larga(datetime.now())} · {activos} caso(s) activo(s) · "
                               f"{listos} listo(s) para entregar")
        for estado in ESTADOS:
            casos = self.repo.list_cases(estado)
            limite = 8 if estado == "Entregado" else 50

            col = QFrame()
            col.setObjectName("Col")
            v = QVBoxLayout(col)
            v.setContentsMargins(10, 10, 10, 10)
            v.setSpacing(8)
            cab = QHBoxLayout()
            titulo = QLabel(estado.upper())
            titulo.setObjectName("ColTitle")
            contador = QLabel(str(len(casos)))
            contador.setObjectName("Counter")
            contador.setAccessibleName(f"{len(casos)} caso(s) en {estado}")
            cab.addWidget(titulo)
            cab.addWidget(contador)
            cab.addStretch()
            v.addLayout(cab)
            for r in casos[:limite]:
                card = CaseCard(r)
                card.clicked.connect(self.open_case.emit)
                v.addWidget(card)
            if not casos:
                vacio = QLabel("Sin casos.")
                vacio.setObjectName("Muted")
                v.addWidget(vacio)
            if len(casos) > limite:
                mas = QLabel(f"+ {len(casos) - limite} más en Historial")
                mas.setObjectName("Muted")
                v.addWidget(mas)
            v.addStretch()
            self.board.addWidget(col, 1)
