import html
import platform
import sqlite3

import PySide6
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)
from app.ai.config import check_ai
from app.db.repo import Repository
from app.diagnosis.engine import load_rules
from app.paths import data_dir, db_path
from app.ui.welcome import WelcomeDialog
from app.ui.widgets import AreaDesplazable, cabecera, limpiar_layout, lista_dato_valor, panel, ruta_cortable
from app.version import APP_NAME, VERSION

TECNOLOGIAS = ("Python · PySide6 (Qt) · SQLite · psutil y WMI (lectura de hardware) · "
               "motor de reglas propio · IA local con Ollama · ReportLab (PDF) · "
               "PyInstaller e Inno Setup (instalador)")
LIMITACIONES = (
    "Las temperaturas dependen de LibreHardwareMonitor o de permisos de administrador; sin ellos "
    "se usa un sensor general (aproximado) o no se muestran.",
    "La salud de los discos es la que informa Windows Storage; el programa no lee SMART por su cuenta.",
    "WMI no informa la memoria gráfica de 4 GB o más.",
    "El diagnóstico por reglas solo reconoce los síntomas y datos definidos en sus reglas.",
    "La IA local es opcional, puede tardar en equipos modestos y su texto debe revisarse.",
    "Sin Internet no hay recuperación de contraseña: solo se puede restaurar una copia de seguridad.",
    "La salud frente a fábrica depende de la base local de referencias: solo incluye pocos modelos "
    "documentados y lo que no está en ella aparece como «Sin referencia».",
    "El puntaje de CPU usa una unidad propia del programa: solo se compara con referencias medidas por el "
    "taller con esta misma prueba. La lectura de discos requiere permisos de administrador.",
)
# (tabla, etiqueta). Las tablas opcionales pueden no existir en una base recién creada.
CONTEOS = (("cases", "Casos registrados"), ("equipment", "Equipos"), ("clients", "Clientes"),
           ("hardware_captures", "Capturas de hardware"), ("diagnoses", "Diagnósticos guardados"),
           ("health_results", "Evaluaciones de salud"), ("health_benchmarks", "Pruebas de rendimiento"),
           ("reports", "Reportes generados"), ("case_notes", "Notas de casos"), ("users", "Técnicos"))


class AcercaPage(QWidget):
    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        self._texto = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(8)
        textos, _t, _s = cabecera("Acerca del sistema", f"{APP_NAME} · versión {VERSION}")
        outer.addLayout(textos)

        inner = QWidget()
        inner.setObjectName("ScrollBody")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(12)
        scroll = AreaDesplazable(inner)
        outer.addWidget(scroll, 1)

        p0, v0 = panel("Qué es")
        desc = QLabel("Sistema de diagnóstico asistido por IA local para talleres de mantenimiento de "
                      "computadoras. Funciona sin conexión a Internet y propone posibles causas, "
                      "prioridad y recomendaciones. La validación final siempre la realiza el técnico.")
        desc.setWordWrap(True)
        v0.addWidget(desc)
        lay.addWidget(p0)

        fila = QHBoxLayout()  # una QGridLayout aquí no respeta la altura de los textos con salto de línea
        fila.setSpacing(12)
        p1, v1 = panel("Versión y datos del sistema")
        self.info_box = QVBoxLayout()
        v1.addLayout(self.info_box)
        b_copiar = QPushButton("Copiar información (para soporte)")
        b_copiar.setObjectName("Secondary")
        b_copiar.clicked.connect(self._copiar)
        self.ok = QLabel("")
        self.ok.setObjectName("Ok")
        v1.addWidget(b_copiar, alignment=Qt.AlignLeft)
        v1.addWidget(self.ok)
        fila.addWidget(p1, 1)

        p_l, vl = panel("Limitaciones conocidas")
        lim = QLabel("<br>".join(f"• {html.escape(t)}" for t in LIMITACIONES))
        lim.setTextFormat(Qt.RichText)
        lim.setWordWrap(True)
        vl.addWidget(lim)
        vl.addStretch()
        fila.addWidget(p_l, 1)
        lay.addLayout(fila)

        p2, v2 = panel("Tecnologías")
        tec = QLabel(TECNOLOGIAS)
        tec.setWordWrap(True)
        v2.addWidget(tec)
        lay.addWidget(p2)

        p3, v3 = panel("Evolución prevista")
        evo = QLabel("<b>1.0</b> (actual): recepción, escaneo, reglas, IA local acotada, reportes y copias.<br>"
                     "<b>1.1</b>: más cobertura de componentes. <i>Próximamente</i><br>"
                     "<b>2.0</b>: aprendizaje automático local. <i>Próximamente</i><br>"
                     "<b>2.5</b>: predicción de fallas. <i>Próximamente</i>")
        evo.setTextFormat(Qt.RichText)
        evo.setWordWrap(True)
        v3.addWidget(evo)
        lay.addWidget(p3)

        p4, v4 = panel("Configuración inicial")
        b = QPushButton("Abrir el asistente de configuración inicial")
        b.setObjectName("Secondary")
        b.clicked.connect(lambda: WelcomeDialog(self.repo, self).exec())
        fila_b = QHBoxLayout()
        fila_b.addWidget(b)
        fila_b.addStretch()
        v4.addLayout(fila_b)
        lay.addWidget(p4)
        lay.addStretch()
        self.refresh()

    def _contar(self, tabla: str) -> str:
        try:
            return str(self.repo.c.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0])
        except sqlite3.Error:
            return "0"

    def _datos(self) -> list[tuple[str, str]]:
        try:
            tam = f"{db_path().stat().st_size / 1024:.0f} KB"
        except OSError:
            tam = "s/d"
        _ok, _modelo, msg = check_ai(self.repo)
        datos = [
            ("Versión", VERSION),
            ("Python", platform.python_version()),
            ("PySide6", PySide6.__version__),
            ("SQLite", sqlite3.sqlite_version),
            ("Sistema operativo", platform.platform()),
            ("Carpeta de datos", str(data_dir())),
            ("Tamaño de la base de datos", tam),
            ("Reglas de diagnóstico", str(len(load_rules()))),
        ]
        datos += [(etiqueta, self._contar(tabla)) for tabla, etiqueta in CONTEOS]
        datos.append(("IA local", msg))
        return datos

    def refresh(self):
        datos = self._datos()
        self._texto = "\n".join(f"{k}: {v}" for k, v in datos)
        limpiar_layout(self.info_box)
        self.info_box.addWidget(lista_dato_valor(
            [(k, ruta_cortable(v) if k == "Carpeta de datos" else v) for k, v in datos]))
        self.ok.setText("")

    def _copiar(self):
        QApplication.clipboard().setText(f"{APP_NAME}\n{self._texto}")
        self.ok.setText("Información copiada.")
