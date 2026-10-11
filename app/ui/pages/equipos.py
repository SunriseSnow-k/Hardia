from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from app.db.equipment_repo import EquipmentRepository
from app.db.repo import Repository

COLUMNAS = ["Serie", "Equipo", "Cliente", "Teléfono", "CPU", "RAM",
            "Almacenamiento", "Sistema", "Casos", "Último ingreso"]


class EquiposPage(QWidget):
    open_case = Signal(str)
    new_intake = Signal(str)

    def __init__(self, repo: Repository):
        super().__init__()
        self.er = EquipmentRepository(repo)
        self._filas = []

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(12)
        t = QLabel("Equipos")
        t.setObjectName("PageTitle")
        s = QLabel("Equipos registrados en este taller. Doble clic para ver su último caso.")
        s.setObjectName("Muted")
        root.addWidget(t)
        root.addWidget(s)

        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText("Buscar por serie, equipo, cliente o teléfono…")
        self.buscar.textChanged.connect(self.refresh)
        root.addWidget(self.buscar)

        self.tabla = QTableWidget(0, len(COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(COLUMNAS)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla.cellDoubleClicked.connect(lambda _f, _c: self._ver_ultimo())
        root.addWidget(self.tabla, 1)

        fila = QHBoxLayout()
        b1 = QPushButton("Ver último caso")
        b2 = QPushButton("Nueva recepción con este equipo")
        b1.setObjectName("Secondary")
        b2.setObjectName("Primary")
        b1.clicked.connect(self._ver_ultimo)
        b2.clicked.connect(self._nueva)
        self.cuenta = QLabel("")
        self.cuenta.setObjectName("Muted")
        fila.addWidget(b1)
        fila.addWidget(b2)
        fila.addStretch()
        fila.addWidget(self.cuenta)
        root.addLayout(fila)
        self.refresh()

    def refresh(self):
        self._filas = self.er.list_equipment(self.buscar.text())
        self.tabla.setRowCount(len(self._filas))
        for i, r in enumerate(self._filas):
            valores = [r["serial"], r["description"], r["cliente"] or "", r["phone"] or "",
                       r["cpu"] or "", r["ram"] or "", r["storage"] or "", r["os"] or "",
                       str(r["n_casos"]), (r["ultimo"] or "")[:10]]
            for j, v in enumerate(valores):
                self.tabla.setItem(i, j, QTableWidgetItem(v))
        self.cuenta.setText(f"{len(self._filas)} equipo(s)")

    def _fila_actual(self):
        i = self.tabla.currentRow()
        return self._filas[i] if 0 <= i < len(self._filas) else None

    def _ver_ultimo(self):
        r = self._fila_actual()
        if r and r["ultimo_code"]:
            self.open_case.emit(r["ultimo_code"])

    def _nueva(self):
        r = self._fila_actual()
        if r:
            self.new_intake.emit(r["serial"])