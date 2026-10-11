from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QComboBox, QPushButton, QListWidget)
from app.db.repo import Repository, ESTADOS
from app.ui.diagnosis_dialog import DiagnosisDialog
from app.ui.styles import PRIORITY_COLORS


class CaseDialog(QDialog):
    """Detalle de un caso: datos, estado, diagnóstico y casos anteriores del equipo."""

    def __init__(self, repo: Repository, code: str, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.code = code
        self.changed = False
        caso = repo.get_case(code)

        self.setWindowTitle(f"Caso {code}")
        self.setMinimumWidth(560)
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

        self.prio = QLabel()
        self._pintar_prio(caso["priority"])
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Prioridad:"))
        fila.addWidget(self.prio)
        fila.addStretch()
        lay.addLayout(fila)

        problema = QLabel(f'Problema: {caso["problem"]}')
        problema.setWordWrap(True)
        lay.addWidget(problema)
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

        sec_d = QLabel("Diagnóstico")
        sec_d.setObjectName("SectionTitle")
        lay.addWidget(sec_d)
        self.diag_lbl = QLabel(self._resumen_diag())
        self.diag_lbl.setWordWrap(True)
        lay.addWidget(self.diag_lbl)
        btn_d = QPushButton("Ejecutar diagnóstico")
        btn_d.setObjectName("Primary")
        btn_d.clicked.connect(self._diagnosticar)
        lay.addWidget(btn_d)

        sec = QLabel("Otros casos del mismo equipo")
        sec.setObjectName("SectionTitle")
        lay.addWidget(sec)
        lista = QListWidget()
        lista.setMaximumHeight(120)
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

    def _pintar_prio(self, prioridad: str):
        bg, fg = PRIORITY_COLORS.get(prioridad, ("#eee", "#333"))
        self.prio.setText(prioridad)
        self.prio.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:3px; padding:2px 8px;"
            "font-size:12px; font-weight:600;"
        )

    def _resumen_diag(self) -> str:
        d = self.repo.get_diagnosis(self.code)
        if not d:
            return "Aún no se ha ejecutado un diagnóstico."
        causas = d["result"]["causes"]
        fecha = d["created_at"][:16]
        if not causas:
            return f"Último diagnóstico ({fecha}): sin causas identificadas."
        return (f'Último diagnóstico ({fecha}): {causas[0]["cause"]} '
                f'— prioridad {causas[0]["priority"]}.')

    def _diagnosticar(self):
        dlg = DiagnosisDialog(self.repo, self.code, self)
        dlg.exec()
        if dlg.saved:
            self.changed = True
            caso = self.repo.get_case(self.code)
            self._pintar_prio(caso["priority"])
            self.estado.setCurrentText(caso["status"])
            self.diag_lbl.setText(self._resumen_diag())

    def _guardar_estado(self):
        self.repo.update_case_status(self.code, self.estado.currentText())
        self.changed = True
        self.ok.setText("Estado actualizado.")