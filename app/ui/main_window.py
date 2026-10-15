import logging

from PySide6.QtCore import Qt, QStringListModel, QTimer, Signal
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
                               QListWidget, QStackedWidget, QLabel, QFrame,
                               QLineEdit, QCompleter, QPushButton)
from app import backup
from app.ai.config import check_ai
from app.db.repo import Repository
from app.db.search_repo import SearchQueries
from app.ui.case_dialog import CaseDialog
from app.ui.pages.inicio import InicioPage
from app.ui.pages.recepcion import RecepcionPage
from app.ui.pages.escaneo import EscaneoPage
from app.ui.pages.salud import SaludPage
from app.ui.pages.equipos import EquiposPage
from app.ui.pages.historial import HistorialPage
from app.ui.pages.reportes import ReportesPage
from app.ui.pages.conocimiento import ConocimientoPage
from app.ui.pages.ia_local import IaLocalPage
from app.ui.pages.configuracion import ConfiguracionPage
from app.ui.pages.acerca import AcercaPage

SECCIONES = [
    "Inicio", "Recepción de equipo", "Escanear equipo", "Salud del equipo", "Equipos",
    "Historial", "Reportes", "Base de conocimiento", "IA local", "Configuración",
    "Acerca del sistema",
]
(IDX_INICIO, IDX_RECEPCION, IDX_ESCANEO, IDX_SALUD, IDX_EQUIPOS, IDX_HISTORIAL,
 IDX_REPORTES, IDX_CONOCIMIENTO, IDX_IA, IDX_CONFIG, IDX_ACERCA) = range(11)
MAX_SUGERENCIAS = 20
log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    closed = Signal()  # la ventana terminó de cerrarse (para salir o volver al login)

    def __init__(self, repo: Repository, user_id: str):
        super().__init__()
        self.repo = repo
        self._hits: dict[str, str] = {}
        self._skip_backup = False
        self.logout_requested = False
        self.setWindowTitle("Sistema Inteligente Offline")
        self.resize(1280, 780)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._barra_superior(user_id))

        # Páginas
        self.inicio = InicioPage(repo)
        self.recepcion = RecepcionPage(repo, user_id)
        self.escaneo = EscaneoPage()
        self.salud = SaludPage(repo)
        self.equipos = EquiposPage(repo)
        self.historial = HistorialPage(repo)
        self.reportes = ReportesPage(repo, user_id)
        self.conocimiento = ConocimientoPage()
        self.ia = IaLocalPage(repo)
        self.config = ConfiguracionPage(repo, user_id)
        self.acerca = AcercaPage(repo)
        reales = {
            IDX_INICIO: self.inicio, IDX_RECEPCION: self.recepcion,
            IDX_ESCANEO: self.escaneo, IDX_SALUD: self.salud, IDX_EQUIPOS: self.equipos,
            IDX_HISTORIAL: self.historial, IDX_REPORTES: self.reportes,
            IDX_CONOCIMIENTO: self.conocimiento, IDX_IA: self.ia,
            IDX_CONFIG: self.config, IDX_ACERCA: self.acerca,
        }
        self.pages = QStackedWidget()
        for i in range(len(SECCIONES)):
            self.pages.addWidget(reales[i])

        # Barra lateral con "Cerrar sesión" separado al final
        lateral = QFrame()
        lateral.setObjectName("SidebarBox")
        lateral.setFixedWidth(225)
        lv = QVBoxLayout(lateral)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.addItems(SECCIONES)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar.currentRowChanged.connect(self._cambiar_pagina)
        self.b_logout = QPushButton("←  Cerrar sesión")
        self.b_logout.setObjectName("Logout")
        self.b_logout.setCursor(Qt.PointingHandCursor)
        self.b_logout.setToolTip("Vuelve a la pantalla de inicio de sesión")
        self.b_logout.clicked.connect(self.cerrar_sesion)
        lv.addWidget(self.sidebar, 1)
        lv.addWidget(self.b_logout)

        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(lateral)
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
        self.escaneo.ver_salud.connect(self.abrir_salud_captura)
        self.equipos.ver_salud.connect(self.abrir_salud)
        self.salud.changed.connect(self.equipos.refresh)
        self.equipos.open_case.connect(self.abrir_caso)
        self.equipos.new_intake.connect(self._nueva_recepcion)
        self.historial.open_case.connect(self.abrir_caso)
        self.ia.settings_changed.connect(self.actualizar_ia)
        self.config.restored.connect(self._tras_restaurar)

        self.actualizar_ia()
        self.sidebar.setCurrentRow(IDX_INICIO)

    def mostrar(self):
        """Abre maximizada si la pantalla es más chica que el tamaño preferido (p. ej., 1366×768)."""
        pantalla = self.screen().availableGeometry()
        if pantalla.width() < self.width() + 40 or pantalla.height() < self.height() + 40:
            self.showMaximized()
        else:
            self.show()

    # ---------- Barra superior con búsqueda global ----------
    def _barra_superior(self, user_id: str) -> QFrame:
        top = QFrame()
        top.setObjectName("TopBar")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(18, 10, 18, 10)
        tl.setSpacing(10)
        name = QLabel("Sistema Inteligente Offline")
        name.setObjectName("AppName")
        tl.addWidget(name)
        offline = QLabel("● Modo Offline")
        offline.setObjectName("Chip")
        offline.setStyleSheet("color:#2f855a;")
        offline.setToolTip("El programa funciona sin Internet: los datos se quedan en este equipo.")
        self.chip_ia = QLabel("● IA Local")
        self.chip_ia.setObjectName("Chip")
        tl.addWidget(offline)
        tl.addWidget(self.chip_ia)
        tl.addStretch()

        self.buscador = QLineEdit()
        self.buscador.setPlaceholderText("Buscar cliente, documento, equipo, serie o teléfono…")
        self.buscador.setClearButtonEnabled(True)
        self.buscador.setFixedWidth(380)
        self.modelo = QStringListModel(self)
        self.completer = QCompleter(self)
        self.completer.setModel(self.modelo)
        self.completer.setFilterMode(Qt.MatchContains)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self.buscador.setCompleter(self.completer)
        self.buscador.textChanged.connect(self._al_buscar)
        self.completer.activated[str].connect(self._al_elegir)
        tl.addWidget(self.buscador)

        user = QLabel(f"Técnico: {user_id}")
        user.setObjectName("Chip")
        tl.addWidget(user)
        return top

    def actualizar_ia(self):
        ok, _modelo, msg = check_ai(self.repo)
        if ok:
            self.chip_ia.setText("● IA Local Disponible")
            self.chip_ia.setStyleSheet("color:#2f855a;")
        else:
            self.chip_ia.setText("● IA no disponible · modo reglas")
            self.chip_ia.setStyleSheet("color:#5f6b77;")
        self.chip_ia.setToolTip(msg)

    def _al_buscar(self, texto: str):
        self._hits = {}
        if len(texto.strip()) < 2:
            self.modelo.setStringList([])
            return
        try:  # misma búsqueda que el Historial: incluye documento y marca/modelo de las capturas
            filas = SearchQueries(self.repo.c).search_cases(text=texto, limit=MAX_SUGERENCIAS)["rows"]
        except Exception:
            filas = []
        for r in filas:
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
        if self.pages.currentIndex() == IDX_SALUD:
            self.salud.refresh()

    def _usar_escaneo(self, data: dict):
        self.recepcion.set_hardware(data)
        self.sidebar.setCurrentRow(IDX_RECEPCION)

    def _nueva_recepcion(self, serie: str):
        """Abre la recepción con la serie del equipo (activa el aviso de reingreso)."""
        self.recepcion._limpiar()
        self.recepcion.serie.setText(serie)
        self.sidebar.setCurrentRow(IDX_RECEPCION)

    def abrir_salud(self, code: str):
        """Salud del equipo de un caso (desde Equipos u otras pantallas)."""
        if not code:
            return
        self.sidebar.setCurrentRow(IDX_SALUD)
        self.salud.show_case(code)

    def abrir_salud_captura(self, data: dict):
        """Salud de una captura todavía sin caso (desde Escanear). No se guarda."""
        self.sidebar.setCurrentRow(IDX_SALUD)
        self.salud.show_scan(data)

    def abrir_caso(self, code: str):
        dlg = CaseDialog(self.repo, code, self)
        dlg.exec()
        if dlg.changed:
            self._refrescar_todo()

    # ---------- Sesión y cierre ----------
    def cerrar_sesion(self):
        """Vuelve al login. El cierre pasa por closeEvent: cancela la IA, espera al escaneo
        y hace la copia automática; la base de datos no se cierra."""
        self.logout_requested = True
        if not self.close():
            self.logout_requested = False

    def _tras_restaurar(self):
        self._skip_backup = True  # no se hace copia automática de datos recién restaurados
        self.logout_requested = False
        self.close()

    def closeEvent(self, event):
        self.ia.shutdown()
        w = self.escaneo.worker
        if w and w.isRunning():
            w.wait(15000)  # deja terminar un escaneo en curso
        if not self._skip_backup and self.repo.get_setting("auto_backup", "1") == "1":
            try:
                backup.auto_backup(self.repo.c)
            except Exception:  # una copia automática fallida no debe impedir cerrar el programa
                log.exception("Falló la copia automática al cerrar")
        super().closeEvent(event)
        if event.isAccepted():
            self.closed.emit()
