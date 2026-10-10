from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QLabel,
                               QLineEdit, QPushButton, QWidget)
from app.db.repo import Repository


class LoginDialog(QDialog):
    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        self.first_run = repo.count_users() == 0
        self.user_id = ""
        self.setWindowTitle("Sistema Inteligente Offline — Iniciar sesión")
        self.setFixedSize(760, 460)

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
        h = QLabel("Crear cuenta inicial" if self.first_run else "Iniciar sesión")
        h.setObjectName("PageTitle")
        sub = QLabel(
            "Primer uso: cree la cuenta del técnico responsable."
            if self.first_run else "Acceso para técnicos del taller."
        )
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText("ID de técnico (ej.: TEC-001)")
        self.pw_input = QLineEdit()
        self.pw_input.setPlaceholderText("Contraseña")
        self.pw_input.setEchoMode(QLineEdit.Password)
        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        btn = QPushButton("Crear cuenta" if self.first_run else "Ingresar")
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