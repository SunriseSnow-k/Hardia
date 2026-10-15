import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)
from app.ai.config import check_ai, nombre_modelo
from app.db.repo import Repository
from app.paths import data_dir


class WelcomeDialog(QDialog):
    """Asistente de configuración inicial (2 pasos)."""

    def __init__(self, repo: Repository, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.setWindowTitle("Configuración inicial")
        self.setMinimumWidth(500)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(10)
        self.paso = QLabel()
        self.paso.setObjectName("Muted")
        self.titulo = QLabel()
        self.titulo.setObjectName("PageTitle")
        lay.addWidget(self.paso)
        lay.addWidget(self.titulo)

        self.stack = QStackedWidget()
        lay.addWidget(self.stack)

        # Paso 1: datos del negocio
        p1 = QWidget()
        v1 = QVBoxLayout(p1)
        v1.setContentsMargins(0, 0, 0, 0)
        v1.setSpacing(6)
        self.nombre = QLineEdit(repo.get_setting("business_name", ""))
        self.nombre.setPlaceholderText("Ej.: Taller TecnoPC")
        self.telefono = QLineEdit(repo.get_setting("business_phone", ""))
        for etiqueta, campo in (("Nombre del negocio", self.nombre),
                                ("Teléfono del negocio (opcional)", self.telefono)):
            l = QLabel(etiqueta)
            l.setObjectName("Muted")
            v1.addWidget(l)
            v1.addWidget(campo)
        nota = QLabel("Estos datos aparecen en los reportes. Puede cambiarlos después "
                      "en Configuración.")
        nota.setObjectName("Muted")
        nota.setWordWrap(True)
        v1.addWidget(nota)
        self.stack.addWidget(p1)

        # Paso 2: resumen
        p2 = QWidget()
        v2 = QVBoxLayout(p2)
        v2.setContentsMargins(0, 0, 0, 0)
        self.info = QLabel()
        self.info.setTextFormat(Qt.RichText)
        self.info.setWordWrap(True)
        v2.addWidget(self.info)
        self.stack.addWidget(p2)

        fila = QHBoxLayout()
        self.b_omitir = QPushButton("Omitir")
        self.b_omitir.setObjectName("Secondary")
        self.b_omitir.clicked.connect(self._omitir)
        self.b_atras = QPushButton("Atrás")
        self.b_atras.setObjectName("Secondary")
        self.b_atras.clicked.connect(lambda: self._ir(0))
        self.b_sig = QPushButton("Continuar")
        self.b_sig.setObjectName("Primary")
        self.b_sig.clicked.connect(self._siguiente)
        fila.addWidget(self.b_omitir)
        fila.addStretch()
        fila.addWidget(self.b_atras)
        fila.addWidget(self.b_sig)
        lay.addLayout(fila)
        self._ir(0)

    def _ir(self, i: int):
        self.stack.setCurrentIndex(i)
        self.paso.setText(f"Paso {i + 1} de 2")
        self.b_atras.setVisible(i == 1)
        if i == 0:
            self.titulo.setText("Bienvenido")
            self.b_sig.setText("Continuar")
            return
        self.titulo.setText("Todo listo")
        self.b_sig.setText("Empezar")
        ok, modelo, msg = check_ai(self.repo)
        ia = (f"<b style='color:#2f855a'>● IA local lista</b> ({html.escape(nombre_modelo(modelo))})."
              if ok else
              "<b style='color:#5f6b77'>● IA local opcional.</b> El programa funciona completo con "
              "el diagnóstico por reglas. Si quiere ayuda de la IA para redactar y resumir, descargue "
              "el paquete de IA (una sola vez) en la sección <b>IA local</b>.")
        self.info.setText(
            "El programa funciona <b>sin Internet</b>.<br><br>"
            "Sus datos se guardan solo en este equipo:<br>"
            f"{html.escape(str(data_dir()))}<br><br>{ia}")

    def _siguiente(self):
        if self.stack.currentIndex() == 0:
            self._ir(1)
            return
        self._guardar()
        self.accept()

    def _omitir(self):
        self.repo.set_setting("setup_done", "1")
        self.reject()

    def _guardar(self):
        self.repo.set_setting("business_name", self.nombre.text().strip() or "Mi taller")
        self.repo.set_setting("business_phone", self.telefono.text().strip())
        self.repo.set_setting("setup_done", "1")