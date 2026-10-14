from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QVBoxLayout, QLabel,
                               QLineEdit, QPushButton, QWidget)
from app.db.repo import Repository
from app.ui.widgets import campo

BENEFICIOS = (
    "Recepción, escaneo y diagnóstico de cada equipo en un solo lugar",
    "Reportes en PDF para el técnico y para el cliente",
    "IA local opcional: sin ella, el diagnóstico por reglas sigue funcionando",
)


class LoginDialog(QDialog):
    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        self.first_run = repo.count_users() == 0
        self.user_id = ""
        self.setWindowTitle("Sistema Inteligente Offline — Iniciar sesión")
        self.setFixedSize(900, 560)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Mitad izquierda: identidad y beneficios
        left = QWidget()
        left.setObjectName("LoginLeft")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(48, 48, 48, 48)
        lv.setSpacing(14)
        lv.addStretch()
        icon = QLabel(">_")
        icon.setObjectName("LoginIcon")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(72, 64)
        title = QLabel("Sistema Inteligente Offline")
        title.setStyleSheet("font-size:22px; font-weight:600;")
        subtitle = QLabel("Diagnóstico asistido y mantenimiento de computadoras. "
                          "Funciona sin Internet: los datos se quedan en este equipo.")
        subtitle.setObjectName("LoginMuted")
        subtitle.setWordWrap(True)
        lv.addWidget(icon)
        lv.addWidget(title)
        lv.addWidget(subtitle)
        lv.addSpacing(8)
        for texto in BENEFICIOS:
            b = QLabel(f"<span style='color:#5ec1df'>✓</span>&nbsp; {texto}")
            b.setTextFormat(Qt.RichText)
            b.setWordWrap(True)
            lv.addWidget(b)
        lv.addStretch()

        # Mitad derecha: tarjeta de acceso
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setAlignment(Qt.AlignCenter)
        card = QFrame()
        card.setObjectName("LoginCard")
        card.setFixedWidth(360)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(28, 26, 28, 26)
        cv.setSpacing(10)
        h = QLabel("Crear cuenta inicial" if self.first_run else "Iniciar sesión")
        h.setObjectName("PageTitle")
        sub = QLabel(
            "Primer uso: cree la cuenta del técnico responsable."
            if self.first_run else "Acceso para técnicos del taller."
        )
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText("Ej.: TEC-001")
        self.pw_input = QLineEdit()
        self.pw_input.setPlaceholderText("Contraseña" + (" (mínimo 6 caracteres)" if self.first_run else ""))
        self.pw_input.setEchoMode(QLineEdit.Password)
        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        btn = QPushButton("Crear cuenta" if self.first_run else "Ingresar")
        btn.setObjectName("Primary")
        btn.setDefault(True)
        btn.clicked.connect(self.try_login)
        self.pw_input.returnPressed.connect(self.try_login)
        nota = QLabel("Sin Internet no hay recuperación de contraseña: si la olvida, solo se puede "
                      "restaurar una copia de seguridad.")
        nota.setObjectName("Muted")
        nota.setWordWrap(True)

        cv.addWidget(h)
        cv.addWidget(sub)
        cv.addSpacing(4)
        cv.addWidget(campo("ID de técnico", self.id_input))
        cv.addWidget(campo("Contraseña", self.pw_input))
        cv.addWidget(self.error)
        cv.addWidget(btn)
        cv.addWidget(nota)
        rv.addWidget(card)

        root.addWidget(left, 1)
        root.addWidget(right, 1)

    def try_login(self):
        tech_id = self.id_input.text().strip()
        password = self.pw_input.text()
        if not tech_id or not password:
            self.error.setText("Ingrese su ID y su contraseña.")
            return
        if self.first_run:
            try:
                self.repo.create_user(tech_id, password)
            except ValueError as e:
                self.error.setText(str(e))
                return
        elif not self.repo.verify_user(tech_id, password):
            self.error.setText("ID o contraseña incorrectos.")
            self.pw_input.clear()
            return
        self.user_id = tech_id.upper()
        self.accept()
