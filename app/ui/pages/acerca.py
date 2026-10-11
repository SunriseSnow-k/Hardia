import html
import platform
import sqlite3

import PySide6
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QFrame, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)
from app.ai.config import check_ai
from app.db.repo import Repository
from app.diagnosis.engine import load_rules
from app.paths import data_dir, db_path
from app.ui.welcome import WelcomeDialog
from app.version import APP_NAME, VERSION

TECNOLOGIAS = ("Python · PySide6 (Qt) · SQLite · psutil y WMI (lectura de hardware) · "
               "motor de reglas propio · IA local con Ollama · ReportLab (PDF) · "
               "PyInstaller e Inno Setup (instalador)")


class AcercaPage(QWidget):
    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        self._texto = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(8)
        t = QLabel("Acerca del sistema")
        t.setObjectName("PageTitle")
        s = QLabel(f"{APP_NAME} · versión {VERSION}")
        s.setObjectName("Muted")
        outer.addWidget(t)
        outer.addWidget(s)

        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        p0, v0 = self._panel("Qué es")
        desc = QLabel("Sistema de diagnóstico asistido por IA local para talleres de mantenimiento de "
                      "computadoras. Funciona sin conexión a Internet y propone posibles causas, "
                      "prioridad y recomendaciones. La validación final siempre la realiza el técnico.")
        desc.setWordWrap(True)
        v0.addWidget(desc)
        lay.addWidget(p0)

        p1, v1 = self._panel("Información del sistema")
        self.info = QLabel()
        self.info.setTextFormat(Qt.RichText)
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        b_copiar = QPushButton("Copiar información (para soporte)")
        b_copiar.setObjectName("Secondary")
        b_copiar.clicked.connect(self._copiar)
        self.ok = QLabel("")
        self.ok.setObjectName("Ok")
        v1.addWidget(self.info)
        v1.addWidget(b_copiar)
        v1.addWidget(self.ok)
        lay.addWidget(p1)

        p2, v2 = self._panel("Tecnologías")
        tec = QLabel(TECNOLOGIAS)
        tec.setWordWrap(True)
        v2.addWidget(tec)
        lay.addWidget(p2)

        p3, v3 = self._panel("Evolución prevista")
        evo = QLabel("<b>1.0</b> (actual): recepción, escaneo, reglas, IA local acotada, reportes y copias.<br>"
                     "<b>1.1</b>: más cobertura de componentes. <i>Próximamente</i><br>"
                     "<b>2.0</b>: aprendizaje automático local. <i>Próximamente</i><br>"
                     "<b>2.5</b>: predicción de fallas. <i>Próximamente</i>")
        evo.setTextFormat(Qt.RichText)
        evo.setWordWrap(True)
        v3.addWidget(evo)
        lay.addWidget(p3)

        p4, v4 = self._panel("Configuración inicial")
        b = QPushButton("Abrir el asistente de configuración inicial")
        b.setObjectName("Secondary")
        b.clicked.connect(lambda: WelcomeDialog(self.repo, self).exec())
        v4.addWidget(b, alignment=Qt.AlignLeft)
        lay.addWidget(p4)
        lay.addStretch()
        self.refresh()

    @staticmethod
    def _panel(titulo: str):
        f = QFrame()
        f.setObjectName("Panel")
        v = QVBoxLayout(f)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)
        h = QLabel(titulo)
        h.setObjectName("SectionTitle")
        v.addWidget(h)
        return f, v

    def _datos(self) -> list[tuple[str, str]]:
        try:
            tam = f"{db_path().stat().st_size / 1024:.0f} KB"
        except OSError:
            tam = "s/d"
        _ok, _modelo, msg = check_ai(self.repo)
        return [
            ("Versión", VERSION),
            ("Python", platform.python_version()),
            ("PySide6", PySide6.__version__),
            ("SQLite", sqlite3.sqlite_version),
            ("Sistema operativo", platform.platform()),
            ("Carpeta de datos", str(data_dir())),
            ("Tamaño de la base de datos", tam),
            ("Reglas de diagnóstico", str(len(load_rules()))),
            ("IA local", msg),
        ]

    def refresh(self):
        datos = self._datos()
        self._texto = "\n".join(f"{k}: {v}" for k, v in datos)
        self.info.setText("<br>".join(
            f"<b>{html.escape(k)}:</b> {html.escape(v)}" for k, v in datos))
        self.ok.setText("")

    def _copiar(self):
        QApplication.clipboard().setText(f"{APP_NAME}\n{self._texto}")
        self.ok.setText("Información copiada.")