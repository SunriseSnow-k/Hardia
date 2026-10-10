from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QFrame, QScrollArea)
from app.db.repo import Repository, ESTADOS
from app.ui.styles import PRIORITY_COLORS


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear(item.layout())


class CaseCard(QFrame):
    clicked = Signal(str)

    def __init__(self, row):
        super().__init__()
        self.code = row["code"]
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(3)

        titulo = QLabel(row["equipo"])
        titulo.setStyleSheet("font-weight:600;")
        sub = QLabel(f'{row["cliente"] or "Sin cliente"} · {row["code"]}')
        sub.setObjectName("Muted")
        problema = QLabel(row["problem"])
        problema.setWordWrap(True)

        bg, fg = PRIORITY_COLORS.get(row["priority"], ("#eee", "#333"))
        tag = QLabel(row["priority"])
        tag.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:3px; padding:2px 8px;"
            "font-size:12px; font-weight:600;"
        )
        fila = QHBoxLayout()
        fila.addWidget(tag)
        fila.addStretch()

        lay.addWidget(titulo)
        lay.addWidget(sub)
        lay.addWidget(problema)
        lay.addLayout(fila)

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
        root.setSpacing(12)

        cab = QHBoxLayout()
        textos = QVBoxLayout()
        t = QLabel("Cola de trabajo")
        t.setObjectName("PageTitle")
        s = QLabel("Equipos que están hoy en el taller.")
        s.setObjectName("Muted")
        textos.addWidget(t)
        textos.addWidget(s)
        btn = QPushButton("+ Nueva recepción")
        btn.setObjectName("Primary")
        btn.clicked.connect(self.new_intake.emit)
        cab.addLayout(textos)
        cab.addStretch()
        cab.addWidget(btn, alignment=Qt.AlignTop)
        root.addLayout(cab)

        contenedor = QWidget()
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
        for estado in ESTADOS:
            casos = self.repo.list_cases(estado)
            limite = 8 if estado == "Entregado" else 50

            col = QFrame()
            col.setObjectName("Col")
            v = QVBoxLayout(col)
            v.setContentsMargins(10, 10, 10, 10)
            v.setSpacing(8)
            titulo = QLabel(f"{estado.upper()} ({len(casos)})")
            titulo.setObjectName("ColTitle")
            v.addWidget(titulo)
            for r in casos[:limite]:
                card = CaseCard(r)
                card.clicked.connect(self.open_case.emit)
                v.addWidget(card)
            if len(casos) > limite:
                mas = QLabel(f"+ {len(casos) - limite} más en Historial")
                mas.setObjectName("Muted")
                v.addWidget(mas)
            v.addStretch()
            self.board.addWidget(col, 1)