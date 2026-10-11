import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QLabel, QLineEdit, QComboBox, QPushButton, QFrame)
from app.db.repo import Repository, PRIORIDADES
from app.ui.pages.escaneo import fila_html


class RecepcionPage(QWidget):
    case_created = Signal(str)
    open_case = Signal(str)
    go_scan = Signal()

    CHIPS = ["Lento", "Se apaga", "No enciende", "Se calienta", "Disco lleno", "Pantalla azul"]

    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        self._prev_code = None
        self.hw: dict | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(12)
        t = QLabel("Recepción de equipo")
        t.setObjectName("PageTitle")
        s = QLabel("Registro rápido en una sola pantalla.")
        s.setObjectName("Muted")
        root.addWidget(t)
        root.addWidget(s)

        # Aviso de reingreso
        self.alert = QFrame()
        self.alert.setObjectName("Alert")
        al = QHBoxLayout(self.alert)
        self.alert_text = QLabel()
        self.alert_text.setWordWrap(True)
        btn_prev = QPushButton("Ver caso anterior")
        btn_prev.setObjectName("Secondary")
        btn_prev.clicked.connect(self._ver_anterior)
        al.addWidget(self.alert_text, 1)
        al.addWidget(btn_prev)
        self.alert.hide()
        root.addWidget(self.alert)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(16)

        # --- Panel del formulario ---
        form = QFrame()
        form.setObjectName("Panel")
        fv = QVBoxLayout(form)
        fv.setContentsMargins(16, 14, 16, 14)
        fv.setSpacing(10)
        h1 = QLabel("Cliente y equipo")
        h1.setObjectName("SectionTitle")
        fv.addWidget(h1)

        self.cliente = QLineEdit()
        self.telefono = QLineEdit()
        self.equipo = QLineEdit()
        self.equipo.setPlaceholderText("Ej.: Laptop HP 15")
        self.serie = QLineEdit()
        self.serie.setPlaceholderText("Ej.: SN-48213")
        self.serie.textChanged.connect(self._on_serie)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.addWidget(self._campo("Cliente", self.cliente), 0, 0)
        grid.addWidget(self._campo("Teléfono", self.telefono), 0, 1)
        grid.addWidget(self._campo("Equipo", self.equipo), 1, 0)
        grid.addWidget(self._campo("N.º de serie", self.serie), 1, 1)
        fv.addLayout(grid)

        h2 = QLabel("Problema reportado")
        h2.setObjectName("SectionTitle")
        fv.addWidget(h2)
        self.problema = QLineEdit()
        self.problema.setPlaceholderText("Describa el problema en una línea")
        fv.addWidget(self.problema)

        chips = QGridLayout()
        chips.setHorizontalSpacing(8)
        chips.setVerticalSpacing(8)
        self.chips = []
        for i, texto in enumerate(self.CHIPS):
            b = QPushButton(texto)
            b.setObjectName("ChipBtn")
            b.setCheckable(True)
            self.chips.append(b)
            chips.addWidget(b, i // 3, i % 3)
        fv.addLayout(chips)

        self.prioridad = QComboBox()
        self.prioridad.addItems(PRIORIDADES)
        self.prioridad.setCurrentText("Media")
        fv.addWidget(self._campo("Prioridad", self.prioridad))

        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.ok = QLabel("")
        self.ok.setObjectName("Ok")
        fv.addWidget(self.error)
        fv.addWidget(self.ok)

        botones = QHBoxLayout()
        guardar = QPushButton("Guardar recepción")
        guardar.setObjectName("Primary")
        guardar.clicked.connect(self._guardar)
        limpiar = QPushButton("Limpiar")
        limpiar.setObjectName("Secondary")
        limpiar.clicked.connect(self._limpiar)
        botones.addWidget(guardar)
        botones.addWidget(limpiar)
        botones.addStretch()
        fv.addLayout(botones)

        # --- Panel de datos del equipo (escaneo) ---
        lado = QFrame()
        lado.setObjectName("Panel")
        lv = QVBoxLayout(lado)
        lv.setContentsMargins(16, 14, 16, 14)
        lv.setSpacing(10)
        h3 = QLabel("Datos del equipo")
        h3.setObjectName("SectionTitle")
        lv.addWidget(h3)
        self.hw_box = QVBoxLayout()
        self.hw_box.setSpacing(8)
        lv.addLayout(self.hw_box)
        scan = QPushButton("Escanear o importar datos")
        scan.setObjectName("Secondary")
        scan.clicked.connect(self.go_scan.emit)
        lv.addWidget(scan)
        lv.addStretch()

        cuerpo.addWidget(form, 3)
        cuerpo.addWidget(lado, 2)
        root.addLayout(cuerpo)
        root.addStretch()
        self._render_hw()

    @staticmethod
    def _campo(etiqueta: str, widget: QWidget) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        lbl = QLabel(etiqueta)
        lbl.setObjectName("Muted")
        v.addWidget(lbl)
        v.addWidget(widget)
        return w

    # ---------- Datos de hardware ----------
    def set_hardware(self, data: dict):
        """Recibe un escaneo (local o importado desde USB)."""
        self.hw = data
        resumen = data.get("summary", {})
        if resumen.get("serial") and not self.serie.text().strip():
            self.serie.setText(resumen["serial"])
        if resumen.get("description") and not self.equipo.text().strip():
            self.equipo.setText(resumen["description"])
        self._render_hw()

    def _render_hw(self):
        while self.hw_box.count():
            w = self.hw_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not self.hw:
            lbl = QLabel("Sin datos de hardware.\nUse el escaneo para completarlos automáticamente.")
            lbl.setObjectName("Muted")
            lbl.setWordWrap(True)
            self.hw_box.addWidget(lbl)
            return
        for c in self.hw.get("components", []):
            lbl = QLabel(fila_html(c.get("name", "?"), c.get("detail", ""), c.get("status", "ok")))
            lbl.setTextFormat(Qt.RichText)
            lbl.setWordWrap(True)
            self.hw_box.addWidget(lbl)
        fecha = str(self.hw.get("scanned_at", "")).replace("T", " ")[:16]
        nota = QLabel(f"Escaneado el {html.escape(fecha)}")
        nota.setObjectName("Muted")
        self.hw_box.addWidget(nota)

    # ---------- Reingreso ----------
    def _on_serie(self, texto: str):
        texto = texto.strip()
        self._prev_code = None
        if len(texto) < 3:
            self.alert.hide()
            return
        previos = self.repo.previous_cases(texto)
        if not previos:
            self.alert.hide()
            return
        ultimo = previos[0]
        self._prev_code = ultimo["code"]
        self.alert_text.setText(
            f'<b>Reingreso detectado:</b> este equipo ({ultimo["serial"]}) fue atendido el '
            f'{ultimo["created_at"][:10]} — {ultimo["problem"]}.'
        )
        self.alert.show()
        if not self.cliente.text().strip():
            self.cliente.setText(ultimo["cliente"] or "")
        if not self.telefono.text().strip():
            self.telefono.setText(ultimo["phone"] or "")
        if not self.equipo.text().strip():
            self.equipo.setText(ultimo["equipo"] or "")

    def _ver_anterior(self):
        if self._prev_code:
            self.open_case.emit(self._prev_code)

    # ---------- Guardar ----------
    def _guardar(self):
        self.ok.setText("")
        cliente = self.cliente.text().strip()
        telefono = self.telefono.text().strip()
        equipo = self.equipo.text().strip()
        serie = self.serie.text().strip()
        partes = [c.text() for c in self.chips if c.isChecked()]
        escrito = self.problema.text().strip()
        if escrito:
            partes.append(escrito)
        problema = ", ".join(partes)
        if not (cliente and equipo and serie and problema):
            self.error.setText("Complete cliente, equipo, serie y problema.")
            return
        self.error.setText("")
        code = self.repo.register_intake(
            cliente, telefono, serie, equipo, problema, self.prioridad.currentText(),
        )
        if self.hw:  # guarda el hardware escaneado en el equipo
            r = self.hw.get("summary", {})
            cid = self.repo.add_client(cliente, telefono)
            self.repo.upsert_equipment(
                serie, equipo, cid, cpu=r.get("cpu", ""), ram=r.get("ram", ""),
                storage=r.get("storage", ""), os_name=r.get("os", ""),
            )
        self._limpiar()
        self.ok.setText(f"Caso {code} registrado en la cola de trabajo.")
        self.case_created.emit(code)

    def _limpiar(self):
        for campo in (self.cliente, self.telefono, self.equipo, self.serie, self.problema):
            campo.clear()
        for c in self.chips:
            c.setChecked(False)
        self.prioridad.setCurrentText("Media")
        self.error.setText("")
        self.ok.setText("")
        self.alert.hide()
        self.hw = None
        self._render_hw()