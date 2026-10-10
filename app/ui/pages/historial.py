from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QComboBox, QTableWidget, QTableWidgetItem,
                               QHeaderView, QAbstractItemView)
from app.db.repo import Repository, ESTADOS
from app.ui.styles import PRIORITY_COLORS

COLUMNAS = ["Fecha", "Cliente", "Equipo", "Problema", "Prioridad", "Estado", "Método de análisis"]


class HistorialPage(QWidget):
    open_case = Signal(str)

    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(12)

        t = QLabel("Historial")
        t.setObjectName("PageTitle")
        s = QLabel("Todos los casos guardados en este equipo. Doble clic para ver el detalle.")
        s.setObjectName("Muted")
        root.addWidget(t)
        root.addWidget(s)

        filtro = QHBoxLayout()
        filtro.addWidget(QLabel("Estado:"))
        self.filtro = QComboBox()
        self.filtro.addItems(["Todos", *ESTADOS])
        self.filtro.currentIndexChanged.connect(self.refresh)
        filtro.addWidget(self.filtro)
        filtro.addStretch()
        root.addLayout(filtro)

        self.tabla = QTableWidget(0, len(COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(COLUMNAS)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tabla.cellDoubleClicked.connect(self._doble_clic)
        root.addWidget(self.tabla, 1)

        self.refresh()

    def refresh(self):
        sel = self.filtro.currentText()
        filas = self.repo.list_cases(None if sel == "Todos" else sel)
        self.tabla.setRowCount(len(filas))
        for i, r in enumerate(filas):
            valores = [r["created_at"][:10], r["cliente"] or "", r["equipo"], r["problem"],
                       r["priority"], r["status"], r["method"]]
            for j, v in enumerate(valores):
                item = QTableWidgetItem(v)
                if j == 0:
                    item.setData(Qt.UserRole, r["code"])
                if j == 4:
                    bg, fg = PRIORITY_COLORS.get(v, ("#eee", "#333"))
                    item.setBackground(QColor(bg))
                    item.setForeground(QColor(fg))
                self.tabla.setItem(i, j, item)

    def _doble_clic(self, fila: int, _col: int):
        code = self.tabla.item(fila, 0).data(Qt.UserRole)
        if code:
            self.open_case.emit(code)