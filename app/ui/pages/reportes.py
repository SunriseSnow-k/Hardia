from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.db.repo import ESTADOS, Repository
from app.db.reports_repo import ReportsRepository
from app.db.search_repo import PAGE_SIZE, SearchQueries, pages
from app.paths import reports_dir
from app.reports.service import KINDS, generate_report
from app.ui.case_dialog import CaseDialog
from app.ui.search_widgets import AsyncSearch, DateRangeFilter, PagerBar
from app.ui.widgets import AreaDesplazable, cabecera, fecha_corta, muted, panel

COLUMNAS = ["Código", "Cliente", "Equipo", "Serie", "Tipo", "Fecha", "Archivo"]
MAX_CASOS_COMBO = 50
# Qué incluye cada PDF (según app/reports/tecnico.py y cliente.py)
CONTENIDO_TECNICO = (
    "Inventario completo del equipo por categorías",
    "Datos no disponibles, con su motivo",
    "Cambios desde la inspección anterior",
    "Diagnóstico: causas, evidencia, prioridad y recomendaciones",
    "Salud frente a fábrica: índice, componentes y condiciones de la prueba",
    "Notas del caso (incluidas las observaciones internas)",
)
CONTENIDO_CLIENTE = (
    "Lenguaje simple: qué medimos, qué encontramos y qué significa",
    "Estado de los componentes respecto a fábrica (orientativo)",
    "Recomendaciones y urgencia de cada hallazgo",
    "Trabajo realizado y notas para el cliente",
    "Sin precios, sin plazos y sin notas internas",
)


def _tarjeta(titulo: str, puntos, boton: QPushButton) -> QFrame:
    f = QFrame()
    f.setObjectName("Card")
    v = QVBoxLayout(f)
    v.setContentsMargins(16, 14, 16, 14)
    v.setSpacing(6)
    h = QLabel(titulo)
    h.setObjectName("SectionTitle")
    v.addWidget(h)
    for p in puntos:
        l = QLabel(f"<span style='color:#2f855a'>✓</span>&nbsp; {p}")
        l.setTextFormat(Qt.RichText)
        l.setWordWrap(True)
        v.addWidget(l)
    v.addStretch()
    v.addWidget(boton, alignment=Qt.AlignLeft)
    return f


class ReportesPage(QWidget):
    """Generación de reportes PDF y búsqueda de los ya generados."""

    def __init__(self, repo: Repository, user_id: str):
        super().__init__()
        self.repo = repo
        self.user_id = user_id
        self.rr = ReportsRepository(repo)
        self._pagina = 0
        self.busqueda = AsyncSearch(repo, self)
        self.busqueda.resultado.connect(self._on_resultado)
        self.busqueda.error.connect(self._on_error)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self.buscar_ahora)
        self._timer_caso = QTimer(self)
        self._timer_caso.setSingleShot(True)
        self._timer_caso.setInterval(300)
        self._timer_caso.timeout.connect(self._cargar_casos)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(8)
        textos, _t, _s = cabecera("Reportes",
                                  "Genere el reporte técnico o el informe para el cliente en PDF y busque "
                                  "los reportes ya generados.")
        outer.addLayout(textos)

        # Contenido desplazable: sin esto, en ventanas bajas la tabla aplasta el panel de generar
        inner = QWidget()
        inner.setObjectName("ScrollBody")
        root = QVBoxLayout(inner)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(12)
        outer.addWidget(AreaDesplazable(inner), 1)

        # --- Generar ---
        gen, gv = panel("Generar reporte")
        self.buscar_caso = QLineEdit()
        self.buscar_caso.setPlaceholderText("Buscar el caso: cliente, documento, serie, código, equipo…")
        self.buscar_caso.setClearButtonEnabled(True)
        self.buscar_caso.textChanged.connect(lambda _t: self._timer_caso.start())
        self.combo = QComboBox()
        self.info_caso = muted("")
        sel = QHBoxLayout()
        sel.addWidget(self.buscar_caso, 1)
        sel.addWidget(self.combo, 2)
        gv.addLayout(sel)
        gv.addWidget(self.info_caso)
        self.b_tec = QPushButton("Generar reporte técnico")
        self.b_cli = QPushButton("Generar informe para el cliente")
        self.b_tec.setObjectName("Primary")
        self.b_cli.setObjectName("Secondary")
        self.b_tec.clicked.connect(lambda: self._generar("tecnico"))
        self.b_cli.clicked.connect(lambda: self._generar("cliente"))
        tarjetas = QHBoxLayout()
        tarjetas.setSpacing(12)
        tarjetas.addWidget(_tarjeta("Reporte técnico (PDF)", CONTENIDO_TECNICO, self.b_tec), 1)
        tarjetas.addWidget(_tarjeta("Informe para el cliente (PDF)", CONTENIDO_CLIENTE, self.b_cli), 1)
        gv.addLayout(tarjetas)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        gv.addWidget(self.msg)
        root.addWidget(gen)

        # --- Buscar reportes generados ---
        p_gen, pv = panel("Reportes generados", margen=14)
        self.buscar = QLineEdit()
        self.buscar.setClearButtonEnabled(True)
        self.buscar.setPlaceholderText("Buscar por cliente, código del caso, serie, equipo o fecha…")
        self.buscar.textChanged.connect(lambda _t: self._timer.start())
        pv.addWidget(self.buscar)
        ff = QHBoxLayout()
        ff.setSpacing(8)
        self.f_tipo = self._combo(["Todos los tipos", "Técnico", "Cliente", "Orden de servicio"])
        self.f_estado = self._combo(["Todos los estados del caso", *ESTADOS])
        self.fechas = DateRangeFilter()
        self.fechas.changed.connect(self._nueva_busqueda)
        b_limpiar = QPushButton("Limpiar filtros")
        b_limpiar.setObjectName("Secondary")
        b_limpiar.clicked.connect(self.limpiar)
        ff.addWidget(self.f_tipo)
        ff.addWidget(self.f_estado)
        ff.addWidget(self.fechas)
        ff.addWidget(b_limpiar)
        ff.addStretch()
        pv.addLayout(ff)

        self.estado = QLabel("")
        self.estado.setObjectName("Muted")
        self.estado.setStyleSheet("font-weight:600;")
        pv.addWidget(self.estado)

        self.tabla = QTableWidget(0, len(COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(COLUMNAS)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabla.setShowGrid(False)
        self.tabla.setMinimumHeight(260)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(38)
        self.tabla.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.tabla.cellDoubleClicked.connect(lambda fila, _c: self._abrir_fila(fila))
        pv.addWidget(self.tabla, 1)

        self.pager = PagerBar()
        self.pager.cambiar.connect(self._ir_pagina)
        pv.addWidget(self.pager)

        fila2 = QHBoxLayout()
        b1 = QPushButton("Abrir PDF seleccionado")
        b2 = QPushButton("Ver caso")
        b3 = QPushButton("Abrir carpeta de reportes")
        for b in (b1, b2, b3):
            b.setObjectName("Secondary")
            fila2.addWidget(b)
        fila2.addStretch()
        b1.clicked.connect(lambda: self._abrir_fila(self.tabla.currentRow()))
        b2.clicked.connect(self._ver_caso)
        b3.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(reports_dir()))))
        pv.addLayout(fila2)
        root.addWidget(p_gen, 1)

        self.refresh(sync=True)

    def _combo(self, items) -> QComboBox:
        c = QComboBox()
        c.addItems(items)
        c.currentIndexChanged.connect(lambda _i: self._nueva_busqueda())
        return c

    def _set_msg(self, texto: str, ok: bool = True):
        self.msg.setStyleSheet("color:#2f855a;font-weight:600;" if ok else "color:#c0392b;")
        self.msg.setText(texto)

    # ---------- selector de caso para generar ----------
    def _cargar_casos(self):
        self._timer_caso.stop()
        try:
            res = SearchQueries(self.repo.c).search_cases(
                text=self.buscar_caso.text().strip(), limit=MAX_CASOS_COMBO)
        except Exception as e:
            self._set_msg(f"No se pudieron cargar los casos: {e}", ok=False)
            return
        actual = self.combo.currentData()
        self.combo.clear()
        for r in res["rows"]:
            problema = r["problem"] if len(r["problem"]) <= 40 else r["problem"][:37] + "…"
            self.combo.addItem(
                f'{r["code"]} · {r["equipo"]} · {r["cliente"] or "Sin cliente"} · {problema}',
                r["code"])
        if actual:
            i = self.combo.findData(actual)
            if i >= 0:
                self.combo.setCurrentIndex(i)
        hay = self.combo.count() > 0
        self.b_tec.setEnabled(hay)
        self.b_cli.setEnabled(hay)
        total = res["total"]
        if total == 0:
            self.info_caso.setText("No se encontraron casos.")
        elif total > len(res["rows"]):
            self.info_caso.setText(f"Mostrando {len(res['rows'])} de {total} casos. "
                                   "Escriba para buscar otro.")
        else:
            self.info_caso.setText("")

    # ---------- búsqueda de reportes generados ----------
    def _criterios(self) -> dict:
        desde, hasta = self.fechas.values()
        return {
            "text": self.buscar.text().strip(),
            "kind": {1: "tecnico", 2: "cliente", 3: "orden"}.get(self.f_tipo.currentIndex()),
            "case_status": self.f_estado.currentText() if self.f_estado.currentIndex() else None,
            "date_from": desde, "date_to": hasta,
        }

    def _hay_criterios(self) -> bool:
        return any(self._criterios().values())

    def refresh(self, sync: bool = False):
        self._cargar_casos()
        self.estado.setStyleSheet("")
        self.estado.setText("Buscando…")
        kw = self._criterios()
        kw.update(limit=PAGE_SIZE, offset=self._pagina * PAGE_SIZE)
        (self.busqueda.run_sync if sync else self.busqueda.start)("search_reports", **kw)

    def buscar_ahora(self, sync: bool = False):
        self._timer.stop()
        self._pagina = 0
        self.refresh(sync)

    def _nueva_busqueda(self):
        self.buscar_ahora()

    def _ir_pagina(self, pagina: int):
        self._pagina = max(0, pagina)
        self.refresh()

    def limpiar(self):
        for w in (self.buscar, self.f_tipo, self.f_estado):
            w.blockSignals(True)
        self.buscar.clear()
        self.f_tipo.setCurrentIndex(0)
        self.f_estado.setCurrentIndex(0)
        for w in (self.buscar, self.f_tipo, self.f_estado):
            w.blockSignals(False)
        self.fechas.reset()
        self.buscar_ahora()

    def _on_resultado(self, res: dict):
        filas, total = res["rows"], res["total"]
        paginas = pages(total)
        if total and not filas and self._pagina > 0:
            self._pagina = paginas - 1
            self.refresh()
            return
        self.tabla.setRowCount(len(filas))
        for i, r in enumerate(filas):
            valores = [r["case_code"], r["cliente"] or "", r["equipo"], r["serial"],
                       KINDS.get(r["kind"], r["kind"]), fecha_corta(r["created_at"]), Path(r["path"]).name]
            for j, v in enumerate(valores):
                item = QTableWidgetItem(v)
                if j == 0:
                    item.setData(Qt.UserRole, r["path"])
                self.tabla.setItem(i, j, item)
        if total == 0:
            self.estado.setText("Sin resultados para los criterios seleccionados."
                                if self._hay_criterios() else "Aún no se han generado reportes.")
        else:
            self.estado.setText(f"{total} resultado(s)")
        self.pager.set_state(self._pagina, paginas, total)

    def _on_error(self, mensaje: str):
        self.estado.setStyleSheet("color:#c0392b;font-size:13px;")
        self.estado.setText(f"No se pudo completar la búsqueda: {mensaje}")

    # ---------- acciones ----------
    def _generar(self, tipo: str):
        code = self.combo.currentData()
        if not code:
            self._set_msg("Seleccione un caso.", ok=False)
            return
        try:
            ruta = generate_report(self.repo, self.rr, code, tipo, self.user_id)
        except Exception as e:
            self._set_msg(f"No se pudo generar el reporte: {e}", ok=False)
            return
        self._set_msg(f"Reporte guardado en {ruta}")
        self._pagina = 0
        self.refresh(sync=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ruta)))

    def _fila(self, fila: int):
        if fila < 0 or self.tabla.item(fila, 0) is None:
            return None
        item = self.tabla.item(fila, 0)
        return item.text(), item.data(Qt.UserRole)

    def _abrir_fila(self, fila: int):
        datos = self._fila(fila)
        if not datos:
            self._set_msg("Seleccione un reporte de la lista.", ok=False)
            return
        if not Path(datos[1]).exists():
            self._set_msg("El archivo ya no existe. Genere el reporte de nuevo.", ok=False)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(datos[1]))

    def _ver_caso(self):
        datos = self._fila(self.tabla.currentRow())
        if not datos:
            self._set_msg("Seleccione un reporte de la lista.", ok=False)
            return
        CaseDialog(self.repo, datos[0], self).exec()
        self.refresh()
