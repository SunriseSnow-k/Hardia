from PySide6.QtCore import Qt, QStringListModel, QTimer
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
                               QListWidget, QStackedWidget, QLabel, QFrame,
                               QLineEdit, QCompleter)
from app.db.repo import Repository
from app.ui.case_dialog import CaseDialog
from app.ui.pages.inicio import InicioPage
from app.ui.pages.recepcion import RecepcionPage
from app.ui.pages.escaneo import EscaneoPage
from app.ui.pages.historial import HistorialPage

SECCIONES = [
    "Inicio", "Recepción de equipo", "Escanear equipo", "Equipos", "Historial",
    "Reportes", "Base de conocimiento", "IA local", "Configuración",
    "Acerca del sistema",
]
IDX_INICIO, IDX_RECEPCION, IDX_ESCANEO, IDX_HISTORIAL = 0, 1, 2, 4


class MainWindow(QMainWindow):
    def __init__(self, repo: Repository, user_id: str):
        super().__init__()
        self.repo = repo
        self._hits: dict[str, str] = {}
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
        self.historial = HistorialPage(repo)
        reales = {
            IDX_INICIO: self.inicio, IDX_RECEPCION: self.recepcion,
            IDX_ESCANEO: self.escaneo, IDX_HISTORIAL: self.historial,
        }
        self.pages = QStackedWidget()
        for i, nombre in enumerate(SECCIONES):
            self.pages.addWidget(reales.get(i) or self._placeholder(nombre))

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
        self.historial.open_case.connect(self.abrir_caso)

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
        for text in ("● Modo Offline", "● IA Local Disponible"):
            chip = QLabel(text)
            chip.setObjectName("Chip")
            tl.addWidget(chip)
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

    def _refrescar_todo(self):
        self.inicio.refresh()
        self.historial.refresh()

    def _usar_escaneo(self, data: dict):
        self.recepcion.set_hardware(data)
        self.sidebar.setCurrentRow(IDX_RECEPCION)

    def abrir_caso(self, code: str):
        dlg = CaseDialog(self.repo, code, self)
        dlg.exec()
        if dlg.changed:
            self._refrescar_todo()

    def closeEvent(self, event):
        w = self.escaneo.worker
        if w and w.isRunning():
            w.wait(15000)  # deja terminar un escaneo en curso
        super().closeEvent(event)

    def _placeholder(self, nombre: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(26, 22, 26, 22)
        t = QLabel(nombre)
        t.setObjectName("PageTitle")
        s = QLabel("Pantalla pendiente de construir.")
        s.setObjectName("Muted")
        lay.addWidget(t)
        lay.addWidget(s)
        lay.addStretch()
        return w