from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from app.hardware.inventory import ESTADO_TEXTO, FALLO, NO_AUTORIZADO, NO_COMPATIBLE, NO_DISPONIBLE, OK, inventory_rows
from app.ui.tema import T

_COLOR = {NO_COMPATIBLE: T.texto_suave, NO_DISPONIBLE: T.aviso, NO_AUTORIZADO: T.aviso, FALLO: T.peligro}


class InventoryDialog(QDialog):
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    """Inventario de hardware de una captura, por categorías. Lo no detectado se muestra
    con su motivo (no disponible, no aplica, sin permisos o fallo)."""

    def __init__(self, scan: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Inventario de hardware")
        self.resize(820, 600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(8)
        t = QLabel("Inventario de hardware")
        t.setObjectName("PageTitle")
        fecha = str(scan.get("scanned_at", "")).replace("T", " ")[:16] or "fecha desconocida"
        origen = scan.get("host") or "equipo desconocido"
        s = QLabel(f"{origen} · captura del {fecha}. Los datos que no se pudieron obtener "
                   "aparecen con su motivo.")
        s.setObjectName("Muted")
        s.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(s)

        self.arbol = QTreeWidget()
        self.arbol.setColumnCount(3)
        self.arbol.setHeaderLabels(["Elemento", "Valor", "Estado"])
        self.arbol.setStyleSheet(f"QTreeWidget {{ background: {T.superficie}; border: 1px solid {T.borde}; "
                                 "border-radius: 4px; } QTreeWidget::item { padding: 3px 4px; }")
        grupos: dict[str, QTreeWidgetItem] = {}
        for f in inventory_rows(scan):
            grupo = grupos.get(f["category"])
            if grupo is None:
                grupo = QTreeWidgetItem(self.arbol, [f["category"]])
                fuente = grupo.font(0)
                fuente.setBold(True)
                grupo.setFont(0, fuente)
                grupos[f["category"]] = grupo
            item = QTreeWidgetItem(grupo, [f["label"], f["value"],
                                           "" if f["status"] == OK else ESTADO_TEXTO.get(f["status"], "")])
            if f["status"] != OK:
                brocha = QBrush(QColor(_COLOR.get(f["status"], T.texto_suave)))
                for col in range(3):
                    item.setForeground(col, brocha)
        self.arbol.expandAll()
        self.arbol.resizeColumnToContents(0)
        lay.addWidget(self.arbol, 1)

        fila = QHBoxLayout()
        cerrar = QPushButton("Cerrar")
        cerrar.setObjectName("Secondary")
        cerrar.clicked.connect(self.accept)
        fila.addStretch()
        fila.addWidget(cerrar)
        lay.addLayout(fila)
