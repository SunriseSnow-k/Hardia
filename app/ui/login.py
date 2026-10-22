from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from app.db.repo import Repository
from app.paths import recurso
from app.servicios import cuentas
from app.ui.tema import T
from app.ui.widgets import campo

BENEFICIOS = (
    "Recepción, escaneo y diagnóstico de cada equipo en un solo lugar",
    "Reportes en PDF para el técnico y para el cliente",
    "IA local opcional: sin ella, el diagnóstico por reglas sigue funcionando",
)


class LoginDialog(QDialog):
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        self.first_run = repo.count_users() == 0
        self.user_id = ""
        self.sesion: cuentas.Sesion | None = None
        self.setWindowTitle("Hardia — Iniciar sesión")
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
        icon = QLabel()
        icon.setPixmap(QIcon(str(recurso("assets", "icono.png"))).pixmap(72, 72))
        icon.setFixedSize(72, 72)
        title = QLabel("Hardia")
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
            b = QLabel(f"<span style='color:{T.acento_claro}'>✓</span>&nbsp; {texto}")
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
        nota = QLabel("Si olvida su contraseña, un administrador del taller puede asignarle una nueva "
                      "desde Configuración.")
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
        try:
            if self.first_run:
                sesion = cuentas.crear_cuenta_inicial(self.repo, self.id_input.text(), self.pw_input.text())
            else:
                sesion = cuentas.iniciar_sesion(self.repo, self.id_input.text(), self.pw_input.text())
        except (ValueError, cuentas.SinPermiso) as e:
            self.error.setText(str(e))
            if not self.first_run:
                self.pw_input.clear()
            return
        self.sesion = sesion
        self.user_id = sesion.tech_id
        self.accept()
