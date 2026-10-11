import html
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QFrame, QProgressBar, QListWidget, QListWidgetItem,
                               QFileDialog, QStackedWidget)
from app.hardware import diag_file
from app.hardware.scanner import run_scan, COMPONENT_NAMES

ICONOS = {
    "ok": ("✓", "#2f855a"), "warn": ("⚠", "#b7791f"), "error": ("✕", "#c0392b"),
    "pending": ("·", "#66727f"), "running": ("…", "#1f6f8b"),
}


def fila_html(nombre: str, detalle: str, estado: str) -> str:
    icono, color = ICONOS.get(estado, ICONOS["pending"])
    return (f'<span style="color:{color};font-weight:600">{icono}</span>&nbsp; '
            f'<b>{html.escape(nombre)}</b><br>'
            f'<span style="color:#66727f">{html.escape(detalle)}</span>')


class ScanWorker(QThread):
    step = Signal(int, str, str, str)
    finished_scan = Signal(dict)
    failed = Signal(str)

    def run(self):
        try:
            data = run_scan(lambda i, n, d, s: self.step.emit(i, n, d, s))
            self.finished_scan.emit(data)
        except Exception as e:  # pragma: no cover
            self.failed.emit(str(e))


class EscaneoPage(QWidget):
    use_data = Signal(dict)

    def __init__(self):
        super().__init__()
        self.data = None
        self.worker = None
        self.filas: list[QLabel] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(12)
        t = QLabel("Escaneo del equipo")
        t.setObjectName("PageTitle")
        s = QLabel("Lea el hardware de esta computadora o importe el escaneo de otra desde un USB. "
                   "Funciona sin Internet.")
        s.setObjectName("Muted")
        s.setWordWrap(True)
        root.addWidget(t)
        root.addWidget(s)

        # Selector de modo
        sel = QHBoxLayout()
        self.b_local = QPushButton("Escanear este equipo")
        self.b_usb = QPushButton("Importar desde USB")
        for i, b in enumerate((self.b_local, self.b_usb)):
            b.setObjectName("ChipBtn")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self._modo(i))
            sel.addWidget(b)
        sel.addStretch()
        self.b_local.setChecked(True)
        root.addLayout(sel)

        self.modo = QStackedWidget()

        # --- Modo local ---
        loc = QWidget()
        lv = QVBoxLayout(loc)
        lv.setContentsMargins(0, 0, 0, 0)
        fila = QHBoxLayout()
        self.b_scan = QPushButton("Iniciar escaneo")
        self.b_scan.setObjectName("Primary")
        self.b_scan.clicked.connect(self._iniciar)
        self.estado = QLabel("Listo para escanear.")
        self.estado.setObjectName("Muted")
        fila.addWidget(self.b_scan)
        fila.addWidget(self.estado, 1)
        self.bar = QProgressBar()
        self.bar.setRange(0, len(COMPONENT_NAMES))
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setStyleSheet(
            "QProgressBar{background:#e6eaee;border:1px solid #d9dfe5;border-radius:4px;}"
            "QProgressBar::chunk{background:#1f6f8b;border-radius:3px;}")
        lv.addLayout(fila)
        lv.addWidget(self.bar)
        self.modo.addWidget(loc)

        # --- Modo USB ---
        usb = QWidget()
        uv = QVBoxLayout(usb)
        uv.setContentsMargins(0, 0, 0, 0)
        info = QLabel("En el PC del cliente se ejecuta el programa portable, que guarda un archivo .diag "
                      "en el USB. Conéctelo aquí e impórtelo.")
        info.setObjectName("Muted")
        info.setWordWrap(True)
        self.lista = QListWidget()
        self.lista.setMaximumHeight(110)
        bt = QHBoxLayout()
        b1 = QPushButton("Actualizar")
        b2 = QPushButton("Buscar archivo…")
        b3 = QPushButton("Importar seleccionado")
        for b in (b1, b2):
            b.setObjectName("Secondary")
        b3.setObjectName("Primary")
        b1.clicked.connect(self.refresh_usb)
        b2.clicked.connect(self._buscar_archivo)
        b3.clicked.connect(self._importar_seleccion)
        for b in (b1, b2, b3):
            bt.addWidget(b)
        bt.addStretch()
        uv.addWidget(info)
        uv.addWidget(self.lista)
        uv.addLayout(bt)
        self.modo.addWidget(usb)
        root.addWidget(self.modo)

        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        root.addWidget(self.msg)

        # --- Resultados ---
        panel = QFrame()
        panel.setObjectName("Panel")
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(16, 14, 16, 14)
        pv.setSpacing(8)
        h = QLabel("Componentes")
        h.setObjectName("SectionTitle")
        pv.addWidget(h)
        self.filas_lay = QVBoxLayout()
        self.filas_lay.setSpacing(8)
        pv.addLayout(self.filas_lay)
        acciones = QHBoxLayout()
        self.b_usar = QPushButton("Usar estos datos en la recepción")
        self.b_usar.setObjectName("Primary")
        self.b_usar.clicked.connect(self._usar)
        self.b_guardar = QPushButton("Guardar escaneo en USB/archivo…")
        self.b_guardar.setObjectName("Secondary")
        self.b_guardar.clicked.connect(self._guardar_copia)
        acciones.addWidget(self.b_usar)
        acciones.addWidget(self.b_guardar)
        acciones.addStretch()
        pv.addLayout(acciones)
        root.addWidget(panel, 1)

        self._preparar_filas(COMPONENT_NAMES)
        self._botones_resultado(False)

    # ---------- utilidades ----------
    def _msg(self, texto: str, ok: bool = True):
        color = "#2f855a;font-weight:600" if ok else "#c0392b"
        self.msg.setStyleSheet(f"color:{color};")
        self.msg.setText(texto)

    def _botones_resultado(self, activo: bool):
        self.b_usar.setEnabled(activo)
        self.b_guardar.setEnabled(activo)

    def _preparar_filas(self, nombres):
        while self.filas_lay.count():
            w = self.filas_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.filas = []
        for n in nombres:
            lbl = QLabel(fila_html(n, "Pendiente", "pending"))
            lbl.setTextFormat(Qt.RichText)
            lbl.setWordWrap(True)
            self.filas_lay.addWidget(lbl)
            self.filas.append(lbl)

    def _set_fila(self, i: int, nombre: str, detalle: str, estado: str):
        if 0 <= i < len(self.filas):
            self.filas[i].setText(fila_html(nombre, detalle, estado))

    def _modo(self, i: int):
        self.modo.setCurrentIndex(i)
        self.b_local.setChecked(i == 0)
        self.b_usb.setChecked(i == 1)
        self._msg("")
        if i == 1:
            self.refresh_usb()

    def refresh(self):
        if self.modo.currentIndex() == 1:
            self.refresh_usb()

    # ---------- escaneo local ----------
    def _iniciar(self):
        if self.worker and self.worker.isRunning():
            return
        self.data = None
        self._botones_resultado(False)
        self._msg("")
        self._preparar_filas(COMPONENT_NAMES)
        self._set_fila(0, COMPONENT_NAMES[0], "Leyendo…", "running")
        self.bar.setValue(0)
        self.b_scan.setEnabled(False)
        self.estado.setText("Leyendo componentes…")
        self.worker = ScanWorker()
        self.worker.step.connect(self._paso)
        self.worker.finished_scan.connect(self._fin)
        self.worker.failed.connect(self._fallo)
        self.worker.start()

    def _paso(self, i: int, nombre: str, detalle: str, estado: str):
        self._set_fila(i, nombre, detalle, estado)
        self.bar.setValue(i + 1)
        if i + 1 < len(COMPONENT_NAMES):
            self._set_fila(i + 1, COMPONENT_NAMES[i + 1], "Leyendo…", "running")

    def _fin(self, data: dict):
        self.data = data
        ok = sum(1 for c in data["components"] if c["status"] == "ok")
        self.estado.setText(f'Escaneo completado: {ok} de {len(data["components"])} componentes leídos.')
        self.b_scan.setText("Volver a escanear")
        self.b_scan.setEnabled(True)
        self._botones_resultado(True)

    def _fallo(self, texto: str):
        self.b_scan.setEnabled(True)
        self.estado.setText("")
        self._msg(f"El escaneo falló: {texto}", ok=False)

    # ---------- importar / exportar ----------
    def refresh_usb(self):
        self.lista.clear()
        archivos = diag_file.find_usb_scans()
        if not archivos:
            texto = ("No se encontraron archivos .diag en la unidad USB."
                     if diag_file.removable_drives() else "No se detectó ninguna unidad USB.")
            item = QListWidgetItem(texto)
            item.setFlags(Qt.NoItemFlags)
            self.lista.addItem(item)
            return
        for p in archivos:
            item = QListWidgetItem(f"{p.name}   ·   {p.parent}")
            item.setData(Qt.UserRole, str(p))
            self.lista.addItem(item)
        self.lista.setCurrentRow(0)

    def _buscar_archivo(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Seleccionar escaneo", "", "Escaneo (*.diag)")
        if ruta:
            self._importar(Path(ruta))

    def _importar_seleccion(self):
        item = self.lista.currentItem()
        ruta = item.data(Qt.UserRole) if item else None
        if not ruta:
            self._msg("Seleccione un archivo de la lista.", ok=False)
            return
        self._importar(Path(ruta))

    def _importar(self, ruta: Path):
        try:
            data = diag_file.load_scan(ruta)
        except (ValueError, OSError) as e:
            self._msg(f"No se pudo importar: {e}", ok=False)
            return
        self.data = data
        comps = data["components"]
        self._preparar_filas([c.get("name", "?") for c in comps])
        for i, c in enumerate(comps):
            self._set_fila(i, c.get("name", "?"), c.get("detail", ""), c.get("status", "ok"))
        self._botones_resultado(True)
        fecha = str(data.get("scanned_at", "")).replace("T", " ")[:16]
        self._msg(f"Importado desde {ruta.name} (escaneado el {fecha}).")

    def _guardar_copia(self):
        if not self.data:
            return
        unidades = diag_file.removable_drives()
        base = unidades[0] if unidades else Path.home()
        sugerido = str(base / diag_file.default_filename(self.data))
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar escaneo", sugerido, "Escaneo (*.diag)")
        if not ruta:
            return
        try:
            diag_file.save_scan(self.data, ruta)
        except OSError as e:
            self._msg(f"No se pudo guardar: {e}", ok=False)
            return
        self._msg(f"Escaneo guardado en {ruta}")

    def _usar(self):
        if self.data:
            self.use_data.emit(self.data)