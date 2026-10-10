from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QComboBox, QPushButton, QListWidget)
from app.db.repo import Repository, ESTADOS
from app.ui.styles import PRIORITY_COLORS


class CaseDialog(QDialog):
    """Detalle de un caso: datos, cambio de estado y casos anteriores del equipo."""

    def __init__(self, repo: Repository, code: str, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.code = code
        self.changed = False
        caso = repo.get_case(code)

        self.setWindowTitle(f"Caso {code}")
        self.setMinimumWidth(540)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(8)

        titulo = QLabel(f'{code} — {caso["equipo"]}')
        titulo.setObjectName("PageTitle")
        sub = QLabel(
            f'{caso["cliente"] or "Sin cliente"} · {caso["phone"] or "sin teléfono"} '
            f'· Serie {caso["serial"]}'
        )
        sub.setObjectName("Muted")
        lay.addWidget(titulo)
        lay.addWidget(sub)

        bg, fg = PRIORITY_COLORS.get(caso["priority"], ("#eee", "#333"))
        prio = QLabel(caso["priority"])
        prio.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:3px; padding:2px 8px;"
            "font-size:12px; font-weight:600;"
        )
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Prioridad:"))
        fila.addWidget(prio)
        fila.addStretch()
        lay.addLayout(fila)

        lay.addWidget(QLabel(f'Problema: {caso["problem"]}'))
        lay.addWidget(QLabel(f'Fecha de ingreso: {caso["created_at"]}'))
        lay.addWidget(QLabel(f'Método de análisis: {caso["method"]}'))

        fila2 = QHBoxLayout()
        fila2.addWidget(QLabel("Estado:"))
        self.estado = QComboBox()
        self.estado.addItems(ESTADOS)
        self.estado.setCurrentText(caso["status"])
        guardar = QPushButton("Guardar estado")
        guardar.setObjectName("Primary")
        guardar.clicked.connect(self._guardar_estado)
        fila2.addWidget(self.estado, 1)
        fila2.addWidget(guardar)
        lay.addLayout(fila2)

        self.ok = QLabel("")
        self.ok.setObjectName("Ok")
        lay.addWidget(self.ok)

        sec = QLabel("Otros casos del mismo equipo")
        sec.setObjectName("SectionTitle")
        lay.addWidget(sec)
        lista = QListWidget()
        lista.setMaximumHeight(130)
        otros = repo.other_cases(caso["serial"], code)
        if otros:
            for r in otros:
                lista.addItem(f'{r["code"]} · {r["created_at"][:10]} · {r["problem"]} ({r["status"]})')
        else:
            lista.addItem("Sin casos anteriores.")
        lay.addWidget(lista)

        cerrar = QPushButton("Cerrar")
        cerrar.setObjectName("Secondary")
        cerrar.clicked.connect(self.accept)
        lay.addWidget(cerrar)

    def _guardar_estado(self):
        self.repo.update_case_status(self.code, self.estado.currentText())
        self.changed = True
        self.ok.setText("Estado actualizado.")