import html

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.db.equipment_repo import EquipmentRepository
from app.db.health_repo import HealthRepository
from app.db.repo import Repository
from app.health import estado_por_pct
from app.ui.tema import T
from app.ui.widgets import BarraPorcentaje, cabecera, celda, color_estado, fecha_corta, item_medida, muted, panel

COLUMNAS = ["Equipo", "Serie", "Cliente", "Casos", "Último caso", "Rendimiento", "Acciones"]
COL_RENDIMIENTO, COL_ACCIONES = 5, 6


class EquiposPage(QWidget):
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    open_case = Signal(str)
    new_intake = Signal(str)
    ver_salud = Signal(str)  # código del último caso del equipo

    def __init__(self, repo: Repository):
        super().__init__()
        self.er = EquipmentRepository(repo)
        self.hr = HealthRepository(repo)
        self._filas = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(12)
        textos, _t, _s = cabecera("Equipos",
                                  "Equipos registrados en este taller. Doble clic en una fila para ver "
                                  "su último caso. El rendimiento es el último índice de salud (orientativo).")
        root.addLayout(textos)

        p, pv = panel()
        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText("Buscar por serie, cliente, documento, marca o modelo…")
        self.buscar.setClearButtonEnabled(True)
        self.buscar.textChanged.connect(lambda _t: self._timer.start())
        pv.addWidget(self.buscar)
        root.addWidget(p)

        self.cuenta = muted("")
        root.addWidget(self.cuenta)

        self.tabla = QTableWidget(0, len(COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(COLUMNAS)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(54)
        cab = self.tabla.horizontalHeader()
        cab.setSectionResizeMode(QHeaderView.ResizeToContents)
        cab.setSectionResizeMode(0, QHeaderView.Stretch)
        cab.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tabla.cellDoubleClicked.connect(lambda _f, _c: self._ver_ultimo())
        root.addWidget(self.tabla, 1)

        fila = QHBoxLayout()
        b1 = QPushButton("Ver último caso")
        b1.setObjectName("Secondary")
        b1.clicked.connect(self._ver_ultimo)
        fila.addWidget(b1)
        fila.addStretch()
        root.addLayout(fila)
        self.refresh()

    def refresh(self):
        self._timer.stop()
        self._filas = self.er.list_equipment(self.buscar.text())
        indices = self.hr.latest_index_by_equipment()
        self.tabla.setRowCount(len(self._filas))
        for i, r in enumerate(self._filas):
            hw = " · ".join(x for x in (r["cpu"], r["ram"], r["storage"], r["os"]) if x) or "Sin datos de hardware"
            fecha = fecha_corta(r["ultimo"], con_hora=False) if r["ultimo"] else ""
            ultimo = (f'<span style="color:{T.acento};font-weight:600">{html.escape(r["ultimo_code"])}</span>'
                      f' · {html.escape(fecha)}' if r["ultimo_code"] else "Sin casos")
            cliente = r["cliente"] or "Sin cliente"
            ultimo_txt = f'{r["ultimo_code"]} · {fecha}' if r["ultimo_code"] else "Sin casos"
            celdas = [
                (r["description"], celda(html.escape(r["description"]), hw, rico=True), (r["description"],)),
                (r["serial"], None, ()),
                (r["cliente"] or "", celda(html.escape(cliente), r["phone"] or "", rico=True),
                 (cliente, r["phone"] or "")),
                (str(r["n_casos"]), None, ()),
                (r["ultimo_code"] or "", celda(ultimo, r["ultimo_status"] or "", rico=True),
                 (ultimo_txt, r["ultimo_status"] or "")),
            ]
            for j, (texto, widget, medidas) in enumerate(celdas):
                item = item_medida(*medidas) if widget else QTableWidgetItem(texto)
                item.setData(Qt.UserRole, texto)
                item.setToolTip(texto)
                self.tabla.setItem(i, j, item)
                if widget:
                    self.tabla.setCellWidget(i, j, widget)
            salud = indices.get(r["equipment_id"])
            valor = salud["indice"] if salud else None
            self.tabla.setItem(i, COL_RENDIMIENTO, item_medida("x" * 26))
            self.tabla.setCellWidget(i, COL_RENDIMIENTO, self._rendimiento(valor, salud))
            self.tabla.setItem(i, COL_ACCIONES, item_medida("Salud     Nueva recepción    "))  # enlaces en negrita
            self.tabla.setCellWidget(i, COL_ACCIONES, self._acciones(r["serial"], r["ultimo_code"]))
        self.cuenta.setText(f"{len(self._filas)} equipo(s)")

    @staticmethod
    def _rendimiento(valor, salud) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 0, 8, 0)
        barra = BarraPorcentaje(valor, color=color_estado(estado_por_pct(valor)), texto_alt="Sin medición")
        if salud:
            barra.setToolTip(f'Índice de salud del caso {salud["case_code"]} '
                             f'({fecha_corta(salud["created_at"], con_hora=False)}); orientativo'
                             if valor is not None else "Ningún componente tiene referencia de fábrica")
        else:
            barra.setToolTip("Aún no se evaluó la salud de este equipo")
        h.addWidget(barra)
        return w

    def _acciones(self, serie: str, ultimo_code) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(6, 0, 6, 0)
        h.setSpacing(12)
        b_salud = QPushButton("Salud")
        b_salud.setObjectName("Link")
        b_salud.setCursor(Qt.PointingHandCursor)
        b_salud.setEnabled(bool(ultimo_code))
        b_salud.setToolTip("Ver la salud del equipo en su último caso")
        b_salud.clicked.connect(lambda _=False, c=ultimo_code: self.ver_salud.emit(c))
        b = QPushButton("Nueva recepción")
        b.setObjectName("Link")
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(f"Registrar un nuevo ingreso del equipo {serie}")
        b.clicked.connect(lambda _=False, s=serie: self.new_intake.emit(s))
        h.addWidget(b_salud)
        h.addWidget(b)
        return w

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
