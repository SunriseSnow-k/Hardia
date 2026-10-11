from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)
from app.db.repo import Repository
from app.db.reports_repo import ReportsRepository
from app.paths import reports_dir
from app.reports.service import KINDS, generate_report

COLUMNAS = ["Código", "Equipo", "Cliente", "Tipo", "Fecha", "Archivo"]


class ReportesPage(QWidget):
    def __init__(self, repo: Repository, user_id: str):
        super().__init__()
        self.repo = repo
        self.user_id = user_id
        self.rr = ReportsRepository(repo)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(12)
        t = QLabel("Reportes")
        t.setObjectName("PageTitle")
        s = QLabel("Genere el reporte técnico o el informe para el cliente en PDF. "
                   "Se guardan en este equipo y se abren automáticamente.")
        s.setObjectName("Muted")
        s.setWordWrap(True)
        root.addWidget(t)
        root.addWidget(s)

        # --- Generar ---
        gen = QFrame()
        gen.setObjectName("Panel")
        gv = QVBoxLayout(gen)
        gv.setContentsMargins(16, 14, 16, 14)
        gv.setSpacing(8)
        h = QLabel("Generar reporte")
        h.setObjectName("SectionTitle")
        gv.addWidget(h)
        etq = QLabel("Caso")
        etq.setObjectName("Muted")
        self.combo = QComboBox()
        gv.addWidget(etq)
        gv.addWidget(self.combo)
        fila = QHBoxLayout()
        self.b_tec = QPushButton("Reporte técnico (PDF)")
        self.b_cli = QPushButton("Reporte para el cliente (PDF)")
        self.b_tec.setObjectName("Primary")
        self.b_cli.setObjectName("Primary")
        self.b_tec.clicked.connect(lambda: self._generar("tecnico"))
        self.b_cli.clicked.connect(lambda: self._generar("cliente"))
        fila.addWidget(self.b_tec)
        fila.addWidget(self.b_cli)
        fila.addStretch()
        gv.addLayout(fila)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        gv.addWidget(self.msg)
        root.addWidget(gen)

        # --- Recientes ---
        h2 = QLabel("Reportes recientes")
        h2.setObjectName("SectionTitle")
        root.addWidget(h2)
        self.tabla = QTableWidget(0, len(COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(COLUMNAS)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.tabla.cellDoubleClicked.connect(lambda fila, _c: self._abrir_fila(fila))
        root.addWidget(self.tabla, 1)

        fila2 = QHBoxLayout()
        b1 = QPushButton("Abrir seleccionado")
        b2 = QPushButton("Abrir carpeta de reportes")
        b1.setObjectName("Secondary")
        b2.setObjectName("Secondary")
        b1.clicked.connect(lambda: self._abrir_fila(self.tabla.currentRow()))
        b2.clicked.connect(self._abrir_carpeta)
        fila2.addWidget(b1)
        fila2.addWidget(b2)
        fila2.addStretch()
        root.addLayout(fila2)

        self.refresh()

    # ---------- utilidades ----------
    def _set_msg(self, texto: str, ok: bool = True):
        self.msg.setStyleSheet("color:#2f855a;font-weight:600;" if ok else "color:#c0392b;")
        self.msg.setText(texto)

    def refresh(self):
        actual = self.combo.currentData()
        self.combo.clear()
        for r in self.repo.list_cases()[:200]:
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
        self._llenar_tabla()

    def _llenar_tabla(self):
        filas = self.rr.recent()
        self.tabla.setRowCount(len(filas))
        for i, r in enumerate(filas):
            valores = [r["case_code"], r["equipo"], r["cliente"] or "",
                       KINDS.get(r["kind"], r["kind"]), r["created_at"][:16], Path(r["path"]).name]
            for j, v in enumerate(valores):
                item = QTableWidgetItem(v)
                if j == 0:
                    item.setData(Qt.UserRole, r["path"])
                self.tabla.setItem(i, j, item)

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
        self._llenar_tabla()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ruta)))

    def _abrir_fila(self, fila: int):
        if fila < 0 or self.tabla.item(fila, 0) is None:
            self._set_msg("Seleccione un reporte de la lista.", ok=False)
            return
        ruta = self.tabla.item(fila, 0).data(Qt.UserRole)
        if not Path(ruta).exists():
            self._set_msg("El archivo ya no existe. Genere el reporte de nuevo.", ok=False)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(ruta))

    def _abrir_carpeta(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(reports_dir())))