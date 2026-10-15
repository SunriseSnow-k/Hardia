"""Componentes compartidos de búsqueda: consulta en segundo plano, fechas y paginación."""
import sqlite3
from pathlib import Path

from PySide6.QtCore import QDate, QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import QCheckBox, QDateEdit, QHBoxLayout, QLabel, QPushButton, QWidget

from app.db.repo import Repository
from app.db.search_repo import SearchQueries


def _db_file(conn):
    for fila in conn.execute("PRAGMA database_list"):
        if fila[1] == "main":
            return fila[2] or None
    return None


class _Senales(QObject):
    listo = Signal(int, object)
    fallo = Signal(int, str)


class _Tarea(QRunnable):
    """Ejecuta una consulta en un hilo del pool, con su propia conexión de SOLO LECTURA."""

    def __init__(self, archivo, metodo, kwargs, run_id, senales):
        super().__init__()
        self.archivo, self.metodo, self.kwargs = archivo, metodo, kwargs
        self.run_id, self.senales = run_id, senales

    def run(self):
        try:
            uri = f"{Path(self.archivo).resolve().as_uri()}?mode=ro"
            con = sqlite3.connect(uri, uri=True, timeout=5)
            try:
                con.row_factory = sqlite3.Row
                res = getattr(SearchQueries(con), self.metodo)(**self.kwargs)
            finally:
                con.close()
            self.senales.listo.emit(self.run_id, res)
        except Exception as e:  # nunca debe cerrar el programa
            self.senales.fallo.emit(self.run_id, str(e))


class AsyncSearch(QObject):
    """Lanza consultas de búsqueda sin bloquear la interfaz. Solo se entrega el
    resultado de la última consulta: las anteriores se descartan."""
    resultado = Signal(object)
    error = Signal(str)

    def __init__(self, repo: Repository, parent=None):
        super().__init__(parent)
        self.repo = repo
        self._archivo = _db_file(repo.c)
        self._run = 0
        self._senales = _Senales()
        self._senales.listo.connect(self._on_listo)
        self._senales.fallo.connect(self._on_fallo)

    def start(self, metodo: str, **kwargs):
        self._run += 1
        if not self._archivo:  # base en memoria: no hay archivo que abrir aparte
            self._sync(self._run, metodo, kwargs)
            return
        QThreadPool.globalInstance().start(
            _Tarea(self._archivo, metodo, kwargs, self._run, self._senales))

    def run_sync(self, metodo: str, **kwargs):
        self._run += 1
        self._sync(self._run, metodo, kwargs)

    def _sync(self, rid, metodo, kwargs):
        try:
            res = getattr(SearchQueries(self.repo.c), metodo)(**kwargs)
        except Exception as e:
            self._on_fallo(rid, str(e))
            return
        self._on_listo(rid, res)

    def _on_listo(self, rid: int, res):
        if rid == self._run:
            self.resultado.emit(res)

    def _on_fallo(self, rid: int, mensaje: str):
        if rid == self._run:
            self.error.emit(mensaje)


class DateRangeFilter(QWidget):
    """Filtro opcional por rango de fechas."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.chk = QCheckBox("Fechas:")
        self.desde = QDateEdit()
        self.hasta = QDateEdit()
        for w in (self.desde, self.hasta):
            w.setCalendarPopup(True)
            w.setDisplayFormat("dd/MM/yyyy")
            w.setEnabled(False)
        hoy = QDate.currentDate()
        self.desde.setDate(hoy.addDays(-30))
        self.hasta.setDate(hoy)
        lay.addWidget(self.chk)
        lay.addWidget(self.desde)
        lay.addWidget(QLabel("a"))
        lay.addWidget(self.hasta)
        self.chk.toggled.connect(self._toggle)
        self.desde.dateChanged.connect(lambda _d: self.changed.emit())
        self.hasta.dateChanged.connect(lambda _d: self.changed.emit())

    def _toggle(self, activo: bool):
        self.desde.setEnabled(activo)
        self.hasta.setEnabled(activo)
        self.changed.emit()

    def values(self):
        """(desde, hasta) en formato ISO, o (None, None) si el filtro está apagado."""
        if not self.chk.isChecked():
            return None, None
        a, b = self.desde.date(), self.hasta.date()
        if a > b:
            a, b = b, a
        return a.toString("yyyy-MM-dd"), b.toString("yyyy-MM-dd")

    def reset(self):
        self.chk.blockSignals(True)
        self.chk.setChecked(False)
        self.chk.blockSignals(False)
        self.desde.setEnabled(False)
        self.hasta.setEnabled(False)
        hoy = QDate.currentDate()
        self.desde.blockSignals(True)
        self.hasta.blockSignals(True)
        self.desde.setDate(hoy.addDays(-30))
        self.hasta.setDate(hoy)
        self.desde.blockSignals(False)
        self.hasta.blockSignals(False)


class PagerBar(QWidget):
    """Navegación por páginas."""
    cambiar = Signal(int)

    def __init__(self):
        super().__init__()
        self._pagina = 0
        self._total_paginas = 1
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.b_prev = QPushButton("‹ Anterior")
        self.b_next = QPushButton("Siguiente ›")
        for b in (self.b_prev, self.b_next):
            b.setObjectName("Secondary")
        self.lbl = QLabel("")
        self.lbl.setObjectName("Muted")
        self.b_prev.clicked.connect(lambda: self.cambiar.emit(self._pagina - 1))
        self.b_next.clicked.connect(lambda: self.cambiar.emit(self._pagina + 1))
        lay.addWidget(self.b_prev)
        lay.addWidget(self.b_next)
        lay.addWidget(self.lbl)
        lay.addStretch()
        self.set_state(0, 1, 0)

    def set_state(self, pagina: int, total_paginas: int, total: int):
        self._pagina, self._total_paginas = pagina, total_paginas
        self.lbl.setText(f"Página {pagina + 1} de {total_paginas} · {total} resultado(s)")
        self.b_prev.setEnabled(pagina > 0)
        self.b_next.setEnabled(pagina + 1 < total_paginas)