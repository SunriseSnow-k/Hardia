import html
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QFrame, QProgressBar, QListWidget, QListWidgetItem,
                               QFileDialog, QStackedWidget)
from app.hardware import diag_file
from app.hardware.inventory import (CATEGORIAS, ESTADO_TEXTO, FALLO, NO_AUTORIZADO, NO_COMPATIBLE,
                                    NO_DISPONIBLE, OK)
from app.hardware.scanner import COLECTORES_NOMBRES, run_scan, COMPONENT_NAMES
from app.ui.inventory_dialog import InventoryDialog
from app.ui.widgets import AreaDesplazable, ChipEstado, cabecera, fecha_corta, muted, panel

ICONOS = {
    "ok": ("✓", "#2f855a"), "warn": ("⚠", "#b7791f"), "error": ("✕", "#c0392b"),
    "pending": ("·", "#5f6b77"), "running": ("…", "#1f6f8b"),
}
# Texto del estado durante la lectura (el icono acompaña, nunca va solo)
TEXTO_PASO = {"ok": "Detectado", "warn": "Parcial", "error": "Falló",
              "pending": "Pendiente", "running": "Leyendo…"}
COLOR_TEXTO = {
    "Detectado": ("#e1f3e8", "#2f855a"), "Parcial": ("#fbf0d9", "#b7791f"),
    "Con alerta": ("#fbf0d9", "#b7791f"), "No aplica": ("#eef1f4", "#5f6b77"),
    "No disponible": ("#fbf0d9", "#b7791f"), "Sin permisos": ("#fbf0d9", "#b7791f"),
    "Falló": ("#fbe6e3", "#c0392b"), "Pendiente": ("#eef1f4", "#5f6b77"),
    "Leyendo…": ("#e1f0f5", "#1f6f8b"),
}
_CLAVE_POR_NOMBRE = dict(COLECTORES_NOMBRES)


def fila_html(nombre: str, detalle: str, estado: str) -> str:
    icono, color = ICONOS.get(estado, ICONOS["pending"])
    return (f'<span style="color:{color};font-weight:600">{icono}</span>&nbsp; '
            f'<b>{html.escape(nombre)}</b><br>'
            f'<span style="color:#5f6b77">{html.escape(detalle)}</span>')


def texto_estado(componente: dict, disponibilidad: dict | None) -> str:
    """Estado escrito de una categoría: Detectado, Parcial, No aplica, No disponible…"""
    if not isinstance(disponibilidad, dict):
        return TEXTO_PASO.get(componente.get("status"), "Pendiente")
    st = disponibilidad.get("status")
    if st == OK:
        if disponibilidad.get("faltantes"):
            return "Parcial"
        return "Con alerta" if componente.get("status") == "warn" else "Detectado"
    return {NO_COMPATIBLE: "No aplica", NO_DISPONIBLE: "No disponible",
            NO_AUTORIZADO: "Sin permisos", FALLO: "Falló"}.get(st, "No disponible")


def no_leido(scan: dict) -> list[tuple[str, str, str]]:
    """(categoría, dato, motivo) de todo lo que no se pudo leer, según availability/faltantes."""
    disp = scan.get("availability") if isinstance(scan, dict) else None
    if not isinstance(disp, dict):
        return []
    filas = []
    for clave, titulo in CATEGORIAS:
        a = disp.get(clave)
        if not isinstance(a, dict):
            continue
        st = a.get("status", OK)
        if st != OK:
            motivo = ESTADO_TEXTO.get(st, st)
            if st != NO_COMPATIBLE:  # "no aplica" no es un faltante: el equipo no tiene ese componente
                filas.append((titulo, "Toda la categoría", f'{motivo}: {a.get("detail", "")}'.rstrip(": ")))
            continue
        for f in a.get("faltantes") or []:
            if isinstance(f, dict):
                m = f.get("motivo", NO_DISPONIBLE)
                filas.append((titulo, f.get("campo", "?"), ESTADO_TEXTO.get(m, m)))
    return filas


class _FilaCategoria(QFrame):
    """Icono de estado, nombre, detalle y estado escrito de una categoría."""

    def __init__(self, nombre: str):
        super().__init__()
        self.setObjectName("Row")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 8, 4, 8)
        self.lbl = QLabel()
        self.lbl.setTextFormat(Qt.RichText)
        self.lbl.setWordWrap(True)
        self.chip = ChipEstado("Pendiente")
        lay.addWidget(self.lbl, 1)
        lay.addWidget(self.chip, alignment=Qt.AlignVCenter)
        self.set(nombre, "Pendiente", "pending")

    def set(self, nombre: str, detalle: str, estado: str, texto: str | None = None):
        self.lbl.setText(fila_html(nombre, detalle, estado))
        t = texto or TEXTO_PASO.get(estado, "Pendiente")
        self.chip.set_estado(t, *COLOR_TEXTO.get(t, ("#eef1f4", "#5f6b77")))
        self.setAccessibleName(f"{nombre}: {t}. {detalle}")

    def text(self) -> str:
        return self.lbl.text()


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
    ver_salud = Signal(dict)

    def __init__(self):
        super().__init__()
        self.data = None
        self.worker = None
        self.filas: list[_FilaCategoria] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(12)
        textos, _t, _s = cabecera("Escanear equipo",
                                  "Lea el hardware de esta computadora o importe el escaneo de otra "
                                  "desde un USB. Funciona sin Internet.")
        root.addLayout(textos)

        # Selector de modo
        sel = QHBoxLayout()
        self.b_local = QPushButton("Este equipo")
        self.b_usb = QPushButton("Importar desde USB (.diag)")
        for i, b in enumerate((self.b_local, self.b_usb)):
            b.setObjectName("ChipBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
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
            "QProgressBar{background:#e6eaee;border:none;border-radius:4px;}"
            "QProgressBar::chunk{background:#1f6f8b;border-radius:4px;}")
        lv.addLayout(fila)
        lv.addWidget(self.bar)
        self.modo.addWidget(loc)

        # --- Modo USB ---
        usb = QWidget()
        uv = QVBoxLayout(usb)
        uv.setContentsMargins(0, 0, 0, 0)
        info = muted("En el PC del cliente se ejecuta el programa portable, que guarda un archivo .diag "
                     "en el USB. Conéctelo aquí e impórtelo.")
        self.lista = QListWidget()
        self.lista.setMaximumHeight(110)
        bt = QHBoxLayout()
        b1 = QPushButton("Actualizar")
        b2 = QPushButton("Buscar archivo…")
        b3 = QPushButton("Importar seleccionado")
        for b in (b1, b2, b3):
            b.setObjectName("Secondary")
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
        self._ajustar_modo()

        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        root.addWidget(self.msg)

        # --- Resultados: categorías a la izquierda, acciones y faltantes a la derecha ---
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(16)
        p_cat, pv = panel("Categorías leídas")
        filas_w = QWidget()
        filas_w.setObjectName("ScrollBody")
        self.filas_lay = QVBoxLayout(filas_w)
        self.filas_lay.setContentsMargins(0, 0, 0, 0)
        self.filas_lay.setSpacing(0)
        sc = AreaDesplazable(filas_w)
        pv.addWidget(sc, 1)
        cuerpo.addWidget(p_cat, 3)

        derecha = QVBoxLayout()
        derecha.setSpacing(12)
        p_acc, av = panel("Acciones")
        self.b_usar = QPushButton("Usar datos en la recepción")
        self.b_usar.setObjectName("Primary")
        self.b_usar.clicked.connect(self._usar)
        self.b_salud = QPushButton("Ver salud del equipo")
        self.b_salud.setObjectName("Secondary")
        self.b_salud.clicked.connect(self._ver_salud)
        self.b_inv = QPushButton("Ver inventario detallado")
        self.b_inv.setObjectName("Secondary")
        self.b_inv.clicked.connect(self._ver_inventario)
        self.b_guardar = QPushButton("Guardar archivo .diag en USB")
        self.b_guardar.setObjectName("Secondary")
        self.b_guardar.clicked.connect(self._guardar_copia)
        for b in (self.b_usar, self.b_salud, self.b_inv, self.b_guardar):
            av.addWidget(b)
        derecha.addWidget(p_acc)

        p_nl, nv = panel("Lo que no se pudo leer")
        self.no_leido_lbl = QLabel()
        self.no_leido_lbl.setTextFormat(Qt.RichText)
        self.no_leido_lbl.setWordWrap(True)
        nv.addWidget(self.no_leido_lbl)
        nv.addStretch()
        derecha.addWidget(p_nl, 1)
        cuerpo.addLayout(derecha, 2)
        root.addLayout(cuerpo, 1)

        self._preparar_filas(COMPONENT_NAMES)
        self._botones_resultado(False)
        self._mostrar_no_leido()

    # ---------- utilidades ----------
    def _msg(self, texto: str, ok: bool = True):
        color = "#2f855a;font-weight:600" if ok else "#c0392b"
        self.msg.setStyleSheet(f"color:{color};")
        self.msg.setText(texto)

    @staticmethod
    def _rol(boton: QPushButton, nombre: str):
        boton.setObjectName(nombre)
        boton.style().unpolish(boton)
        boton.style().polish(boton)

    def _tiene_inventario(self) -> bool:
        return bool(self.data) and isinstance(self.data.get("inventory"), dict)

    def _botones_resultado(self, activo: bool):
        self.b_usar.setEnabled(activo)
        self.b_guardar.setEnabled(activo)
        self.b_inv.setEnabled(activo and self._tiene_inventario())
        self.b_salud.setEnabled(activo and self._tiene_inventario())
        self.b_inv.setToolTip("" if self._tiene_inventario() or not activo else
                              "Este archivo es de una versión anterior y no incluye inventario detallado.")
        self.b_salud.setToolTip(self.b_inv.toolTip())

    def _preparar_filas(self, nombres):
        while self.filas_lay.count():
            item = self.filas_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.filas = []
        for n in nombres:
            f = _FilaCategoria(n)
            self.filas_lay.addWidget(f)
            self.filas.append(f)
        self.filas_lay.addStretch()

    def _set_fila(self, i: int, nombre: str, detalle: str, estado: str, texto: str | None = None):
        if 0 <= i < len(self.filas):
            self.filas[i].set(nombre, detalle, estado, texto)

    def _pintar_resultado(self):
        """Filas finales con el estado escrito según la disponibilidad de cada categoría."""
        comps = self.data.get("components", [])
        disp = self.data.get("availability") if isinstance(self.data.get("availability"), dict) else None
        self._preparar_filas([c.get("name", "?") for c in comps])
        for i, c in enumerate(comps):
            clave = _CLAVE_POR_NOMBRE.get(c.get("name"))
            a = disp.get(clave) if disp and clave else None
            self._set_fila(i, c.get("name", "?"), c.get("detail", ""), c.get("status", "ok"),
                           texto_estado(c, a))
        self._mostrar_no_leido()

    def _mostrar_no_leido(self):
        if not self.data:
            self.no_leido_lbl.setText("<span style='color:#5f6b77'>Aparecerá aquí al terminar el escaneo "
                                      "o la importación.</span>")
            return
        if not isinstance(self.data.get("availability"), dict):
            self.no_leido_lbl.setText("<span style='color:#5f6b77'>Archivo de una versión anterior: no "
                                      "incluye el detalle de lo que no se pudo leer.</span>")
            return
        filas = no_leido(self.data)
        if not filas:
            self.no_leido_lbl.setText("<span style='color:#2f855a'>✓ Se leyeron todos los datos "
                                      "disponibles.</span>")
            return
        self.no_leido_lbl.setText("<br>".join(
            f"<b>{html.escape(cat)}</b> · {html.escape(dato)}<br>"
            f"<span style='color:#5f6b77'>{html.escape(motivo)}</span>" for cat, dato, motivo in filas))

    def _ajustar_modo(self):
        """El QStackedWidget toma la altura de la página más alta: se ajusta a la visible."""
        self.modo.setFixedHeight(self.modo.currentWidget().sizeHint().height())

    def _modo(self, i: int):
        self.modo.setCurrentIndex(i)
        self._ajustar_modo()
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
        self._mostrar_no_leido()
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
        data["provenance"] = {"how": "local_scan", "file": None}
        self.data = data
        ok = sum(1 for c in data["components"] if c["status"] == "ok")
        self.estado.setText(f'Escaneo completado: {ok} de {len(data["components"])} categorías sin novedades.')
        self.b_scan.setText("Volver a escanear")
        self.b_scan.setEnabled(True)
        self._rol(self.b_scan, "Secondary")  # ahora la acción principal es usar los datos
        self._pintar_resultado()
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
        data["provenance"] = {"how": "imported_file", "file": ruta.name,
                              "imported_at": datetime.now().isoformat(timespec="seconds")}
        self.data = data
        self._pintar_resultado()
        self._botones_resultado(True)
        fecha = fecha_corta(data.get("scanned_at", ""))
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

    def _ver_inventario(self):
        if self._tiene_inventario():
            InventoryDialog(self.data, self).exec()

    def _ver_salud(self):
        if self._tiene_inventario():
            self.ver_salud.emit(self.data)

    def _usar(self):
        if self.data:
            self.use_data.emit(self.data)
