from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
                               QListWidget, QStackedWidget, QLabel, QFrame)

SECCIONES = [
    "Inicio", "Recepción de equipo", "Escanear equipo", "Equipos", "Historial",
    "Reportes", "Base de conocimiento", "IA local", "Configuración",
    "Acerca del sistema",
]


class MainWindow(QMainWindow):
    def __init__(self, user_id: str):
        super().__init__()
        self.setWindowTitle("Sistema Inteligente Offline")
        self.resize(1200, 720)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Barra superior
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
        user = QLabel(f"Técnico: {user_id}")
        user.setObjectName("Chip")
        tl.addWidget(user)
        outer.addWidget(top)

        # Cuerpo: barra lateral + páginas
        body = QHBoxLayout()
        body.setSpacing(0)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(215)
        self.sidebar.addItems(SECCIONES)
        self.pages = QStackedWidget()
        for nombre in SECCIONES:
            self.pages.addWidget(self._placeholder(nombre))
        self.sidebar.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sidebar.setCurrentRow(0)
        body.addWidget(self.sidebar)
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)

        self.setCentralWidget(central)

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