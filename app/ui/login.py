from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QLabel,
                               QLineEdit, QPushButton, QWidget)


class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sistema Inteligente Offline — Iniciar sesión")
        self.setFixedSize(760, 460)
        self.user_id = ""

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Panel izquierdo
        left = QWidget()
        left.setObjectName("LoginLeft")
        lv = QVBoxLayout(left)
        lv.setAlignment(Qt.AlignCenter)
        icon = QLabel("CPU")
        icon.setObjectName("LoginIcon")
        icon.setAlignment(Qt.AlignCenter)
        title = QLabel("Sistema Inteligente Offline")
        title.setStyleSheet("font-size:18px; font-weight:600;")
        subtitle = QLabel("Diagnóstico y mantenimiento de\ncomputadoras asistido por IA local")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color:#a9b6c4;")
        chips = QLabel("●  Modo Offline      ●  IA Local")
        chips.setStyleSheet("color:#7fd1a0; font-size:12px;")
        for w in (icon, title, subtitle, chips):
            lv.addWidget(w, alignment=Qt.AlignCenter)
            lv.addSpacing(10)

        # Panel derecho
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(48, 40, 48, 40)
        rv.setAlignment(Qt.AlignVCenter)
        h = QLabel("Iniciar sesión")
        h.setObjectName("PageTitle")
        sub = QLabel("Acceso para técnicos del taller.")
        sub.setObjectName("Muted")
        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText("ID de técnico (ej.: TEC-001)")
        self.pw_input = QLineEdit()
        self.pw_input.setPlaceholderText("Contraseña")
        self.pw_input.setEchoMode(QLineEdit.Password)
        self.error = QLabel("")
        self.error.setObjectName("Error")
        btn = QPushButton("Ingresar")
        btn.setObjectName("Primary")
        btn.setDefault(True)
        btn.clicked.connect(self.try_login)
        self.pw_input.returnPressed.connect(self.try_login)

        for w in (h, sub, self.id_input, self.pw_input, self.error, btn):
            rv.addWidget(w)
            rv.addSpacing(8)

        root.addWidget(left, 1)
        root.addWidget(right, 1)

    def try_login(self):
        # Fase 1: validación provisional. En la Fase 2 se valida contra SQLite.
        if not self.id_input.text().strip() or not self.pw_input.text():
            self.error.setText("Ingrese su ID y su contraseña.")
            return
        self.user_id = self.id_input.text().strip().upper()
        self.accept()