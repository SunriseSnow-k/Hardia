from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                               QPushButton, QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QWidget)
from app.ai import prompts
from app.db.clients_repo import ClientsRepository
from app.db.health_repo import HealthRepository
from app.db.notes_repo import MAX_TEXTO, TIPOS, NotesRepository
from app.db.repo import Repository, ESTADOS
from app.db.reports_repo import ReportsRepository
from app.diagnosis.engine import diagnose
from app.reports.service import KINDS, generate_report
from app.ui.ai_widgets import AiDialog
from app.ui.diagnosis_dialog import DiagnosisDialog
from app.ui.widgets import (AreaDesplazable, BarraPorcentaje, ChipEstado, IndicadorEtapas, color_estado,
                            fecha_corta, limpiar_layout, muted, panel)


class CaseDialog(QDialog):
    """Detalle de un caso: datos, estado, diagnóstico, IA, notas, reportes y casos anteriores."""

    def __init__(self, repo: Repository, code: str, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.code = code
        self.changed = False
        self.tech_id = getattr(repo, "session_tech", "") or ""
        self.notes = NotesRepository(repo)
        self.health = HealthRepository(repo)
        caso = repo.get_case(code)
        documento = ClientsRepository(repo).doc_for_case(code)

        self.setWindowTitle(f"Caso {code}")
        self.setMinimumWidth(860)
        self.resize(1060, 800)
        exterior = QVBoxLayout(self)
        exterior.setContentsMargins(0, 0, 0, 12)
        contenido = QWidget()
        contenido.setObjectName("ScrollBody")
        scroll = AreaDesplazable(contenido)
        exterior.addWidget(scroll, 1)
        lay = QVBoxLayout(contenido)
        lay.setContentsMargins(24, 20, 24, 8)
        lay.setSpacing(10)

        # ---------- Cabecera ----------
        fila_t = QHBoxLayout()
        fila_t.setSpacing(10)
        titulo = QLabel(f'{code} — {caso["equipo"]}')
        titulo.setObjectName("PageTitle")
        titulo.setWordWrap(True)
        self.prio = ChipEstado(caso["priority"])
        fila_t.addWidget(titulo)
        fila_t.addWidget(self.prio)
        if caso["reingreso"]:
            reing = ChipEstado("Reingreso", "#e1f0f5", "#1f6f8b")
            reing.setToolTip("Este equipo ya tuvo casos anteriores en el taller.")
            fila_t.addWidget(reing)
        fila_t.addStretch()
        lay.addLayout(fila_t)
        partes = [caso["cliente"] or "Sin cliente", caso["phone"] or "sin teléfono"]
        if documento:
            partes.append(f"Doc. {documento}")
        partes += [f'Serie {caso["serial"]}', f'Ingresó el {fecha_corta(caso["created_at"])}']
        sub = muted(" · ".join(partes))
        sub.setStyleSheet("font-size:13px;")
        lay.addWidget(sub)

        # ---------- Etapas y estado ----------
        p_est, ve = panel(margen=14)
        fila2 = QHBoxLayout()
        fila2.setSpacing(10)
        self.etapas = IndicadorEtapas(ESTADOS, caso["status"])
        fila2.addWidget(self.etapas, 1)
        fila2.addWidget(QLabel("Estado:"))
        self.estado = QComboBox()
        self.estado.addItems(ESTADOS)
        self.estado.setCurrentText(caso["status"])
        self.estado.setMinimumWidth(170)
        guardar = QPushButton("Guardar estado")
        guardar.setObjectName("Secondary")
        guardar.clicked.connect(self._guardar_estado)
        fila2.addWidget(self.estado)
        fila2.addWidget(guardar)
        ve.addLayout(fila2)
        self.ok = QLabel("")
        self.ok.setObjectName("Ok")
        self.ok.setWordWrap(True)
        self.ok.hide()  # solo ocupa espacio cuando hay un mensaje
        ve.addWidget(self.ok)
        lay.addWidget(p_est)

        columnas = QHBoxLayout()
        columnas.setSpacing(14)
        izq = QVBoxLayout()
        izq.setSpacing(12)
        der = QVBoxLayout()
        der.setSpacing(12)
        columnas.addLayout(izq, 1)
        columnas.addLayout(der, 1)
        lay.addLayout(columnas)

        # ---------- Izquierda: problema, diagnóstico e IA ----------
        p_prob, vp = panel("Problema reportado")
        problema = QLabel(caso["problem"])
        problema.setWordWrap(True)
        problema.setTextInteractionFlags(Qt.TextSelectableByMouse)
        vp.addWidget(problema)
        self.metodo = muted(f'Método de análisis: {caso["method"]}')
        vp.addWidget(self.metodo)
        izq.addWidget(p_prob)

        p_diag, vd = panel("Diagnóstico")
        self.diag_lbl = QLabel(self._resumen_diag())
        self.diag_lbl.setWordWrap(True)
        vd.addWidget(self.diag_lbl)
        btn_d = QPushButton("Ver o ejecutar diagnóstico")
        btn_d.setObjectName("Primary")
        btn_d.clicked.connect(self._diagnosticar)
        vd.addWidget(btn_d, alignment=Qt.AlignLeft)
        izq.addWidget(p_diag)

        p_sal, vs = panel("Salud del equipo")
        self.salud_box = QVBoxLayout()
        self.salud_box.setSpacing(6)
        vs.addLayout(self.salud_box)
        b_sal = QPushButton("Ver salud del equipo")
        b_sal.setObjectName("Link")
        b_sal.setCursor(Qt.PointingHandCursor)
        b_sal.clicked.connect(self._ver_salud)
        vs.addWidget(b_sal, alignment=Qt.AlignLeft)
        izq.addWidget(p_sal)
        self._pintar_salud()

        p_ia, vi = panel("Asistente de IA local (opcional)")
        vi.addWidget(muted("Redacta y resume con los datos del caso. No decide el diagnóstico."))
        fila_ia = QHBoxLayout()
        b1 = QPushButton("Resumir historial del equipo")
        b2 = QPushButton("Mensaje para el cliente")
        for b in (b1, b2):
            b.setObjectName("Secondary")
            fila_ia.addWidget(b)
        fila_ia.addStretch()
        b1.clicked.connect(self._resumir_historial)
        b2.clicked.connect(self._mensaje_cliente)
        vi.addLayout(fila_ia)
        izq.addWidget(p_ia)
        izq.addStretch()

        # ---------- Derecha: notas, reportes y otros casos ----------
        p_n, vn = panel("Notas del caso")
        self.lista_notas = QListWidget()
        self.lista_notas.setMinimumHeight(110)
        self.lista_notas.setMaximumHeight(160)
        self.lista_notas.setWordWrap(True)
        vn.addWidget(self.lista_notas)
        fila_n = QHBoxLayout()
        self.tipo_nota = QComboBox()
        for clave, texto in TIPOS.items():
            self.tipo_nota.addItem(texto, clave)
        fila_n.addWidget(QLabel("Tipo:"))
        fila_n.addWidget(self.tipo_nota, 1)
        vn.addLayout(fila_n)
        self.texto_nota = QPlainTextEdit()
        self.texto_nota.setPlaceholderText(
            "Escriba la nota. Las observaciones técnicas solo salen en el reporte técnico; "
            "el trabajo realizado y las notas para el cliente salen en ambos.")
        self.texto_nota.setMaximumHeight(70)
        vn.addWidget(self.texto_nota)
        fila_n2 = QHBoxLayout()
        self.msg_nota = QLabel("")
        self.msg_nota.setWordWrap(True)
        b_nota = QPushButton("Agregar nota")
        b_nota.setObjectName("Secondary")
        b_nota.clicked.connect(self._agregar_nota)
        fila_n2.addWidget(self.msg_nota, 1)
        fila_n2.addWidget(b_nota)
        vn.addLayout(fila_n2)
        self._cargar_notas()
        der.addWidget(p_n)

        p_r, vr = panel("Reportes de este caso")
        fila_r = QHBoxLayout()
        self.b_rep_tec = QPushButton("Reporte técnico (PDF)")
        self.b_rep_cli = QPushButton("Informe para el cliente (PDF)")
        for b in (self.b_rep_tec, self.b_rep_cli):
            b.setObjectName("Secondary")
            fila_r.addWidget(b)
        fila_r.addStretch()
        self.b_rep_tec.clicked.connect(lambda: self._generar_reporte("tecnico"))
        self.b_rep_cli.clicked.connect(lambda: self._generar_reporte("cliente"))
        vr.addLayout(fila_r)
        self.lista_reportes = QListWidget()
        self.lista_reportes.setMaximumHeight(100)
        self.lista_reportes.setToolTip("Doble clic para abrir el PDF")
        self.lista_reportes.itemDoubleClicked.connect(self._abrir_reporte)
        vr.addWidget(self.lista_reportes)
        self._cargar_reportes()
        der.addWidget(p_r)

        p_o, vo = panel("Otros casos del mismo equipo")
        lista = QListWidget()
        lista.setMaximumHeight(120)
        otros = repo.other_cases(caso["serial"], code)
        if otros:
            for r in otros:
                indice = self.health.latest_index_for_case(r["code"])
                salud = f" · salud {indice:.0f} %" if indice is not None else ""
                lista.addItem(f'{r["code"]} · {fecha_corta(r["created_at"], con_hora=False)} · '
                              f'{r["problem"]} ({r["status"]}){salud}')
        else:
            vacio = QListWidgetItem("Sin casos anteriores.")
            vacio.setFlags(Qt.NoItemFlags)
            lista.addItem(vacio)
        vo.addWidget(lista)
        der.addWidget(p_o)
        der.addStretch()
        lay.addStretch()

        cerrar = QPushButton("Cerrar")
        cerrar.setObjectName("Secondary")
        cerrar.clicked.connect(self.accept)
        fila_c = QHBoxLayout()
        fila_c.setContentsMargins(24, 0, 24, 0)
        fila_c.addStretch()
        fila_c.addWidget(cerrar)
        exterior.addLayout(fila_c)

    # ---------- salud ----------
    def _pintar_salud(self):
        limpiar_layout(self.salud_box)
        try:
            res = self.health.evaluate_case(self.code)["resultado"]
        except Exception as e:  # la salud nunca debe impedir abrir el caso
            self.salud_box.addWidget(muted(f"No se pudo evaluar la salud: {e}"))
            return
        if not res["componentes"]:
            self.salud_box.addWidget(muted(res.get("aviso") or "Sin datos de salud."))
            return
        ind = res["indice"]
        fila = QHBoxLayout()
        valor = QLabel(f'{ind["valor"]:.0f} %' if ind["valor"] is not None else "—")
        valor.setStyleSheet(f"font-size:22px; font-weight:600; color:{color_estado(ind['estado'])};")
        fila.addWidget(valor)
        fila.addWidget(ChipEstado(ind["estado"]))
        fila.addWidget(BarraPorcentaje(ind["valor"], color=color_estado(ind["estado"]),
                                       texto_alt="Sin componentes con referencia"), 1)
        self.salud_box.addLayout(fila)
        hall = res.get("hallazgo")
        self.salud_box.addWidget(muted("Índice orientativo respecto a fábrica. " +
                                       (f"Lo más importante: {hall['texto']}" if hall else
                                        "Sin componentes que requieran atención con los datos disponibles.")))

    def _ver_salud(self):
        from app.ui.pages.salud import SaludDialog
        SaludDialog(self.repo, self.code, self).exec()
        self._pintar_salud()
        self.changed = True

    def _pintar_prio(self, prioridad: str):
        self.prio.set_estado(prioridad)

    def _resumen_diag(self) -> str:
        d = self.repo.get_diagnosis(self.code)
        if not d:
            return "Aún no se ha ejecutado un diagnóstico."
        res = d["result"]
        fecha = fecha_corta(d["created_at"])
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
            self.etapas.set_actual(caso["status"])
            self.metodo.setText(f'Método de análisis: {caso["method"]}')
            self.diag_lbl.setText(self._resumen_diag())

    def _guardar_estado(self):
        self.repo.update_case_status(self.code, self.estado.currentText())
        self.etapas.set_actual(self.estado.currentText())
        self.changed = True
        self._msg(self.ok, "Estado actualizado.")

    # ---------- notas ----------
    def _cargar_notas(self):
        self.lista_notas.clear()
        notas = self.notes.for_case(self.code)
        if not notas:
            vacio = QListWidgetItem("Aún no hay notas.")
            vacio.setFlags(Qt.NoItemFlags)
            self.lista_notas.addItem(vacio)
            return
        for n in notas:
            autor = f' · {n["author"]}' if n["author"] else ""
            self.lista_notas.addItem(
                f'{fecha_corta(n["created_at"])} · {TIPOS.get(n["kind"], n["kind"])}{autor}\n{n["text"]}')
        self.lista_notas.scrollToBottom()

    def _msg(self, etiqueta: QLabel, texto: str, ok: bool = True):
        etiqueta.setStyleSheet("color:#2f855a;font-weight:600;" if ok else "color:#c0392b;")
        etiqueta.setText(texto)
        etiqueta.setVisible(bool(texto))

    def _agregar_nota(self):
        texto = self.texto_nota.toPlainText().strip()
        if len(texto) > MAX_TEXTO:
            self._msg(self.msg_nota, f"La nota supera los {MAX_TEXTO} caracteres.", ok=False)
            return
        try:
            self.notes.add(self.code, self.tipo_nota.currentData(), texto, self.tech_id)
        except ValueError as e:
            self._msg(self.msg_nota, str(e), ok=False)
            return
        self.texto_nota.clear()
        self._cargar_notas()
        self.changed = True
        self._msg(self.msg_nota, "Nota guardada.")

    # ---------- reportes del caso ----------
    def _generar_reporte(self, tipo: str):
        try:
            ruta = generate_report(self.repo, ReportsRepository(self.repo), self.code, tipo, self.tech_id)
        except Exception as e:
            self._msg(self.ok, f"No se pudo generar el reporte: {e}", ok=False)
            return
        self._cargar_reportes()
        self.changed = True
        self._msg(self.ok, f"Reporte guardado: {Path(ruta).name}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ruta)))

    def _cargar_reportes(self):
        self.lista_reportes.clear()
        reportes = ReportsRepository(self.repo).for_case(self.code)
        if not reportes:
            vacio = QListWidgetItem("Aún no hay reportes de este caso.")
            vacio.setFlags(Qt.NoItemFlags)
            self.lista_reportes.addItem(vacio)
            return
        for r in reportes:
            item = QListWidgetItem(
                f'{KINDS.get(r["kind"], r["kind"])} · {fecha_corta(r["created_at"])} · {Path(r["path"]).name}')
            item.setData(Qt.UserRole, r["path"])
            self.lista_reportes.addItem(item)

    def _abrir_reporte(self, item: QListWidgetItem):
        ruta = item.data(Qt.UserRole)
        if not ruta:
            return
        if not Path(ruta).exists():
            self._msg(self.ok, "El archivo del reporte ya no existe.", ok=False)
            return
        self._msg(self.ok, "")
        QDesktopServices.openUrl(QUrl.fromLocalFile(ruta))

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
