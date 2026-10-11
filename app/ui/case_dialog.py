from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                               QPushButton, QListWidget, QMessageBox)
from app.ai import prompts
from app.db.repo import Repository, ESTADOS
from app.diagnosis.engine import diagnose
from app.ui.ai_widgets import AiDialog
from app.ui.diagnosis_dialog import DiagnosisDialog
from app.ui.styles import PRIORITY_COLORS


class CaseDialog(QDialog):
    """Detalle de un caso: datos, estado, diagnóstico, IA y casos anteriores del equipo."""

    def __init__(self, repo: Repository, code: str, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.code = code
        self.changed = False
        caso = repo.get_case(code)

        self.setWindowTitle(f"Caso {code}")
        self.setMinimumWidth(580)
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
        self.metodo = QLabel(f'Método de análisis: {caso["method"]}')
        lay.addWidget(self.metodo)

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

        sec_i = QLabel("Asistente de IA local (opcional)")
        sec_i.setObjectName("SectionTitle")
        lay.addWidget(sec_i)
        fila_ia = QHBoxLayout()
        b1 = QPushButton("Resumir historial del equipo")
        b2 = QPushButton("Mensaje para el cliente")
        for b in (b1, b2):
            b.setObjectName("Secondary")
            fila_ia.addWidget(b)
        b1.clicked.connect(self._resumir_historial)
        b2.clicked.connect(self._mensaje_cliente)
        lay.addLayout(fila_ia)

        sec = QLabel("Otros casos del mismo equipo")
        sec.setObjectName("SectionTitle")
        lay.addWidget(sec)
        lista = QListWidget()
        lista.setMaximumHeight(110)
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
        res = d["result"]
        fecha = d["created_at"][:16]
        if not res["causes"]:
            texto = f"Último diagnóstico ({fecha}): sin causas identificadas."
        else:
            texto = (f'Último diagnóstico ({fecha}): {res["causes"][0]["cause"]} '
                     f'— prioridad {res["causes"][0]["priority"]}.')
        if res.get("ai_analysis"):
            texto += f'\nAnálisis de IA local: {res["ai_analysis"]}'
        return texto

    def _diagnosticar(self):
        dlg = DiagnosisDialog(self.repo, self.code, self)
        dlg.exec()
        if dlg.saved:
            self.changed = True
            caso = self.repo.get_case(self.code)
            self._pintar_prio(caso["priority"])
            self.estado.setCurrentText(caso["status"])
            self.metodo.setText(f'Método de análisis: {caso["method"]}')
            self.diag_lbl.setText(self._resumen_diag())

    def _guardar_estado(self):
        self.repo.update_case_status(self.code, self.estado.currentText())
        self.changed = True
        self.ok.setText("Estado actualizado.")

    # ---------- IA ----------
    def _resumir_historial(self):
        caso = self.repo.get_case(self.code)
        historial = self.repo.equipment_history(caso["serial"])
        if len(historial) < 2:
            QMessageBox.information(self, "Resumen del historial",
                                    "Este equipo no tiene casos anteriores que resumir.")
            return
        dlg = AiDialog(self.repo, "Resumen del historial",
                       f'{caso["equipo"]} · Serie {caso["serial"]}',
                       prompts.history_messages(caso, historial), self,
                       nota="Revise el texto: es una asistencia de la IA local.")
        dlg.exec()

    def _mensaje_cliente(self):
        caso = self.repo.get_case(self.code)
        d = self.repo.get_diagnosis(self.code)
        resultado = d["result"] if d else diagnose(caso["problem"], self.repo.get_scan(self.code))
        if not resultado["causes"]:
            QMessageBox.information(self, "Mensaje para el cliente",
                                    "Aún no hay causas identificadas. Ejecute primero el diagnóstico.")
            return
        dlg = AiDialog(self.repo, "Mensaje para el cliente",
                       f'{caso["cliente"] or "Cliente"} · {caso["equipo"]}',
                       prompts.client_messages(caso, resultado), self,
                       nota="Revise y ajuste el texto antes de enviarlo al cliente.")
        dlg.exec()