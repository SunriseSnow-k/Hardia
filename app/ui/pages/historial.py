from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)
from app.db.repo import ESTADOS, PRIORIDADES, Repository
from app.db.search_repo import PAGE_SIZE, pages
from app.ui.search_widgets import AsyncSearch, DateRangeFilter, PagerBar
from app.ui.styles import ACCENT
from app.ui.widgets import ChipEstado, cabecera, fecha_corta, panel

COLUMNAS = ["Código", "Fecha", "Cliente", "Equipo", "Serie", "Problema",
            "Prioridad", "Estado", "Método de análisis"]
COL_PRIORIDAD = 6


def _chip_celda(texto: str) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(8, 0, 8, 0)
    h.addWidget(ChipEstado(texto))
    h.addStretch()
    return w


class HistorialPage(QWidget):
    """Historial de casos con búsqueda, filtros combinables y paginación."""
    open_case = Signal(str)

    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        self._pagina = 0
        self.busqueda = AsyncSearch(repo, self)
        self.busqueda.resultado.connect(self._on_resultado)
        self.busqueda.error.connect(self._on_error)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self.buscar_ahora)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(12)
        textos, _t, _s = cabecera(
            "Historial",
            "Busque por cliente, teléfono, documento, código, serie, equipo, problema o fecha "
            "(2026-10-06 o 06/10/2026). Doble clic para ver el detalle del caso.")
        root.addLayout(textos)

        p_filtros, pv = panel("Filtros", margen=14)
        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText("Buscar en el historial…")
        self.buscar.setClearButtonEnabled(True)
        self.buscar.textChanged.connect(lambda _t: self._timer.start())
        pv.addWidget(self.buscar)

        fila = QHBoxLayout()
        fila.setSpacing(8)
        self.f_estado = self._combo(["Todos los estados", *ESTADOS])
        self.f_prio = self._combo(["Todas las prioridades", *PRIORIDADES])
        self.f_diag = self._combo(["Con o sin diagnóstico", "Con diagnóstico", "Sin diagnóstico"])
        self.f_metodo = self._combo(["Todos los métodos", "Reglas", "Reglas + IA local"])
        self.fechas = DateRangeFilter()
        self.fechas.changed.connect(self._nueva_busqueda)
        b_limpiar = QPushButton("Limpiar filtros")
        b_limpiar.setObjectName("Secondary")
        b_limpiar.clicked.connect(self.limpiar)
        for w in (self.f_estado, self.f_prio, self.f_diag, self.f_metodo):
            fila.addWidget(w)
        fila.addStretch()
        pv.addLayout(fila)
        fila2 = QHBoxLayout()  # en otra fila para que la ventana quepa en pantallas de 1366 px
        fila2.setSpacing(8)
        fila2.addWidget(self.fechas)
        fila2.addWidget(b_limpiar)
        fila2.addStretch()
        pv.addLayout(fila2)
        root.addWidget(p_filtros)

        self.estado = QLabel("")
        self.estado.setObjectName("Muted")
        self.estado.setStyleSheet("font-weight:600;")
        root.addWidget(self.estado)

        self.tabla = QTableWidget(0, len(COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(COLUMNAS)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(40)
        self.tabla.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.tabla.cellDoubleClicked.connect(self._doble_clic)
        root.addWidget(self.tabla, 1)

        self.pager = PagerBar()
        self.pager.cambiar.connect(self._ir_pagina)
        root.addWidget(self.pager)

        self.refresh(sync=True)

    def _combo(self, items) -> QComboBox:
        c = QComboBox()
        c.addItems(items)
        c.currentIndexChanged.connect(lambda _i: self._nueva_busqueda())
        return c

    # ---------- criterios y consulta ----------
    def _criterios(self) -> dict:
        desde, hasta = self.fechas.values()
        return {
            "text": self.buscar.text().strip(),
            "status": self.f_estado.currentText() if self.f_estado.currentIndex() else None,
            "priority": self.f_prio.currentText() if self.f_prio.currentIndex() else None,
            "diagnosis": {1: "con", 2: "sin"}.get(self.f_diag.currentIndex()),
            "method": self.f_metodo.currentText() if self.f_metodo.currentIndex() else None,
            "date_from": desde, "date_to": hasta,
        }

    def _hay_criterios(self) -> bool:
        return any(self._criterios().values())

    def refresh(self, sync: bool = False):
        """Vuelve a consultar con los criterios actuales (se conservan al cambiar de pantalla)."""
        self.estado.setStyleSheet("")
        self.estado.setText("Buscando…")
        kw = self._criterios()
        kw.update(limit=PAGE_SIZE, offset=self._pagina * PAGE_SIZE)
        (self.busqueda.run_sync if sync else self.busqueda.start)("search_cases", **kw)

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
        for w in (self.buscar, self.f_estado, self.f_prio, self.f_diag, self.f_metodo):
            w.blockSignals(True)
        self.buscar.clear()
        for c in (self.f_estado, self.f_prio, self.f_diag, self.f_metodo):
            c.setCurrentIndex(0)
        for w in (self.buscar, self.f_estado, self.f_prio, self.f_diag, self.f_metodo):
            w.blockSignals(False)
        self.fechas.reset()
        self.buscar_ahora()

    # ---------- resultados ----------
    def _on_resultado(self, res: dict):
        filas, total = res["rows"], res["total"]
        paginas = pages(total)
        if total and not filas and self._pagina > 0:  # la página ya no existe
            self._pagina = paginas - 1
            self.refresh()
            return
        self.tabla.setRowCount(len(filas))
        for i, r in enumerate(filas):
            valores = [r["code"], fecha_corta(r["created_at"], con_hora=False), r["cliente"] or "",
                       r["equipo"], r["serial"], r["problem"], r["priority"], r["status"], r["method"]]
            for j, v in enumerate(valores):
                item = QTableWidgetItem(v)
                item.setToolTip(v)
                if j == 0:
                    item.setData(Qt.UserRole, r["code"])
                    item.setForeground(QColor(ACCENT))
                    fuente = item.font()
                    fuente.setBold(True)
                    item.setFont(fuente)
                if j == COL_PRIORIDAD:  # el chip se pinta encima; el texto solo da el ancho
                    item.setText(v + "    ")
                    item.setForeground(QColor(0, 0, 0, 0))
                self.tabla.setItem(i, j, item)
            self.tabla.setCellWidget(i, COL_PRIORIDAD, _chip_celda(r["priority"]))
        if total == 0:
            self.estado.setText("Sin resultados para los criterios seleccionados."
                                if self._hay_criterios() else "Aún no hay casos registrados.")
        else:
            self.estado.setText(f"{total} resultado(s)")
        self.pager.set_state(self._pagina, paginas, total)

    def _on_error(self, mensaje: str):
        self.estado.setStyleSheet("color:#c0392b;font-size:13px;")
        self.estado.setText(f"No se pudo completar la búsqueda: {mensaje}")

    def _doble_clic(self, fila: int, _col: int):
        item = self.tabla.item(fila, 0)
        code = item.data(Qt.UserRole) if item else None
        if code:
            self.open_case.emit(code)