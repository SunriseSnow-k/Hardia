from PySide6.QtCore import Qt, QStringListModel, QTimer
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
                               QListWidget, QStackedWidget, QLabel, QFrame,
                               QLineEdit, QCompleter)
from app import backup
from app.ai.config import check_ai
from app.db.repo import Repository
from app.ui.case_dialog import CaseDialog
from app.ui.pages.inicio import InicioPage
from app.ui.pages.recepcion import RecepcionPage
from app.ui.pages.escaneo import EscaneoPage
from app.ui.pages.equipos import EquiposPage
from app.ui.pages.historial import HistorialPage
from app.ui.pages.reportes import ReportesPage
from app.ui.pages.conocimiento import ConocimientoPage
from app.ui.pages.ia_local import IaLocalPage
from app.ui.pages.configuracion import ConfiguracionPage
from app.ui.pages.acerca import AcercaPage

SECCIONES = [
    "Inicio", "Recepción de equipo", "Escanear equipo", "Equipos", "Historial",
    "Reportes", "Base de conocimiento", "IA local", "Configuración",
    "Acerca del sistema",
]
(IDX_INICIO, IDX_RECEPCION, IDX_ESCANEO, IDX_EQUIPOS, IDX_HISTORIAL,
 IDX_REPORTES, IDX_CONOCIMIENTO, IDX_IA, IDX_CONFIG, IDX_ACERCA) = range(10)


class MainWindow(QMainWindow):
    def __init__(self, repo: Repository, user_id: str):
        super().__init__()
        self.repo = repo
        self._hits: dict[str, str] = {}
        self._skip_backup = False
        self.setWindowTitle("Sistema Inteligente Offline")
        self.resize(1200, 720)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._barra_superior(user_id))

        # Páginas
        self.inicio = InicioPage(repo)
        self.recepcion = RecepcionPage(repo)
        self.escaneo = EscaneoPage()
        self.equipos = EquiposPage(repo)
        self.historial = HistorialPage(repo)
        self.reportes = ReportesPage(repo, user_id)
        self.conocimiento = ConocimientoPage()
        self.ia = IaLocalPage(repo)
        self.config = ConfiguracionPage(repo, user_id)
        self.acerca = AcercaPage(repo)
        reales = {
            IDX_INICIO: self.inicio, IDX_RECEPCION: self.recepcion,
            IDX_ESCANEO: self.escaneo, IDX_EQUIPOS: self.equipos,
            IDX_HISTORIAL: self.historial, IDX_REPORTES: self.reportes,
            IDX_CONOCIMIENTO: self.conocimiento, IDX_IA: self.ia,
            IDX_CONFIG: self.config, IDX_ACERCA: self.acerca,
        }
        self.pages = QStackedWidget()
        for i in range(len(SECCIONES)):
            self.pages.addWidget(reales[i])

        # Barra lateral
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(215)
        self.sidebar.addItems(SECCIONES)
        self.sidebar.currentRowChanged.connect(self._cambiar_pagina)

        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(self.sidebar)
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)
        self.setCentralWidget(central)

        # Conexiones entre páginas
        self.inicio.open_case.connect(self.abrir_caso)
        self.inicio.new_intake.connect(lambda: self.sidebar.setCurrentRow(IDX_RECEPCION))
        self.recepcion.open_case.connect(self.abrir_caso)
        self.recepcion.case_created.connect(lambda _c: self._refrescar_todo())
        self.recepcion.go_scan.connect(lambda: self.sidebar.setCurrentRow(IDX_ESCANEO))
        self.escaneo.use_data.connect(self._usar_escaneo)
        self.equipos.open_case.connect(self.abrir_caso)
        self.equipos.new_intake.connect(self._nueva_recepcion)
        self.historial.open_case.connect(self.abrir_caso)
        self.ia.settings_changed.connect(self.actualizar_ia)
        self.config.restored.connect(self._tras_restaurar)

        self.actualizar_ia()
        self.sidebar.setCurrentRow(IDX_INICIO)

    # ---------- Barra superior con búsqueda global ----------
    def _barra_superior(self, user_id: str) -> QFrame:
        top = QFrame()
        top.setObjectName("TopBar")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(16, 8, 16, 8)
        name = QLabel("Sistema Inteligente Offline")
        name.setStyleSheet("font-weight:600;")
        tl.addWidget(name)
        offline = QLabel("● Modo Offline")
        offline.setObjectName("Chip")
        self.chip_ia = QLabel("● IA Local")
        self.chip_ia.setObjectName("Chip")
        tl.addWidget(offline)
        tl.addWidget(self.chip_ia)
        tl.addStretch()

        self.buscador = QLineEdit()
        self.buscador.setPlaceholderText("Buscar cliente, equipo, serie o teléfono…")
        self.buscador.setFixedWidth(320)
        self.modelo = QStringListModel(self)
        self.completer = QCompleter(self)
        self.completer.setModel(self.modelo)
        self.completer.setFilterMode(Qt.MatchContains)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.buscador.setCompleter(self.completer)
        self.buscador.textChanged.connect(self._al_buscar)
        self.completer.activated[str].connect(self._al_elegir)
        tl.addWidget(self.buscador)

        user = QLabel(f"Técnico: {user_id}")
        user.setObjectName("Chip")
        tl.addWidget(user)
        return top

    def actualizar_ia(self):
        ok, _modelo, _msg = check_ai(self.repo)
        if ok:
            self.chip_ia.setText("● IA Local Disponible")
            self.chip_ia.setStyleSheet("color:#2f855a;")
        else:
            self.chip_ia.setText("● IA no disponible · modo reglas")
            self.chip_ia.setStyleSheet("color:#66727f;")

    def _al_buscar(self, texto: str):
        if len(texto.strip()) < 2:
            self._hits = {}
            self.modelo.setStringList([])
            return
        self._hits = {}
        for r in self.repo.search(texto):
            etiqueta = (f'{r["code"]} · {r["cliente"] or "Sin cliente"} · {r["equipo"]} '
                        f'· {r["serial"]} · {r["phone"] or ""}')
            self._hits[etiqueta] = r["code"]
        self.modelo.setStringList(list(self._hits))
        self.completer.complete()

    def _al_elegir(self, etiqueta: str):
        code = self._hits.get(etiqueta)
        QTimer.singleShot(0, self.buscador.clear)
        if code:
            self.abrir_caso(code)

    # ---------- Navegación y refresco ----------
    def _cambiar_pagina(self, i: int):
        self.pages.setCurrentIndex(i)
        pagina = self.pages.widget(i)
        if hasattr(pagina, "refresh"):
            pagina.refresh()
        if i == IDX_IA:
            self.actualizar_ia()

    def _refrescar_todo(self):
        self.inicio.refresh()
        self.historial.refresh()
        self.reportes.refresh()
        self.equipos.refresh()

    def _usar_escaneo(self, data: dict):
        self.recepcion.set_hardware(data)
        self.sidebar.setCurrentRow(IDX_RECEPCION)

    def _nueva_recepcion(self, serie: str):
        """Abre la recepción con la serie del equipo (activa el aviso de reingreso)."""
        self.recepcion._limpiar()
        self.recepcion.serie.setText(serie)
        self.sidebar.setCurrentRow(IDX_RECEPCION)

    def abrir_caso(self, code: str):
        dlg = CaseDialog(self.repo, code, self)
        dlg.exec()
        if dlg.changed:
            self._refrescar_todo()

    def _tras_restaurar(self):
        self._skip_backup = True  # no se hace copia automática de datos recién restaurados
        self.close()

    def closeEvent(self, event):
        self.ia.shutdown()
        w = self.escaneo.worker
        if w and w.isRunning():
            w.wait(15000)  # deja terminar un escaneo en curso
        if not self._skip_backup and self.repo.get_setting("auto_backup", "1") == "1":
            try:
                backup.auto_backup(self.repo.c)
            except Exception:
                pass  # una copia automática fallida no debe impedir cerrar el programa
        super().closeEvent(event)