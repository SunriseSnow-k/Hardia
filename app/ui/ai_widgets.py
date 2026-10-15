from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from app.ai import config as ia_config
from app.ai.worker import AiWorker
from app.ui.tema import T

_ZOMBIES: list = []  # hilos que tardaron en terminar: se conservan hasta que acaben


class AiStreamPanel(QFrame):
    """Muestra una respuesta de la IA en vivo, con tiempo transcurrido y cancelación."""
    text_ready = Signal(str)  # texto completo, solo si terminó bien

    def __init__(self, vacio: str = "", altura: int = 130, msg_cancel: str = "Cancelado."):
        super().__init__()
        self.msg_cancel = msg_cancel
        self.worker = None
        self._run = 0
        self._seg = 0
        self._texto = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.salida = QPlainTextEdit()
        self.salida.setReadOnly(True)
        self.salida.setPlaceholderText(vacio)
        self.salida.setMinimumHeight(altura)
        self.salida.setStyleSheet(f"background:{T.superficie};border:1px solid {T.borde};"
                                  f"border-radius:4px;padding:6px;color:{T.texto};")
        self.barra = QProgressBar()
        self.barra.setRange(0, 0)
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(6)
        self.barra.setStyleSheet(
            f"QProgressBar{{background:{T.pista};border:1px solid {T.borde};border-radius:3px;}}"
            f"QProgressBar::chunk{{background:{T.acento};border-radius:2px;}}")
        self.barra.hide()
        fila = QHBoxLayout()
        self.estado = QLabel("")
        self.estado.setObjectName("Muted")
        self.estado.setWordWrap(True)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setObjectName("Secondary")
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_cancel.hide()
        fila.addWidget(self.estado, 1)
        fila.addWidget(self.btn_cancel)
        lay.addWidget(self.salida)
        lay.addWidget(self.barra)
        lay.addLayout(fila)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

    # ---------- API ----------
    def text(self) -> str:
        return self._texto.strip()

    def is_running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def mostrar_mensaje(self, texto: str, error: bool = False):
        self._estado(texto, error)

    def start(self, model: str, messages: list[dict]):
        self.shutdown()
        self._run += 1
        self._texto = ""
        self._seg = 0
        self.salida.clear()
        w = AiWorker(self._run, model, messages)
        w.chunk.connect(self._chunk)
        w.completed.connect(self._fin)
        w.failed.connect(self._error)
        self.worker = w
        self.barra.show()
        self.btn_cancel.show()
        self._estado(self._progreso())
        self.timer.start()
        w.start()

    def cancel(self):
        w = self.worker
        if w is not None and w.isRunning():
            self._run += 1  # ignora lo que llegue después
            w.cancel()
            self._parar_ui()
            self._estado(self.msg_cancel)

    def shutdown(self):
        """Cancela y espera al hilo (se usa al cerrar ventanas o reiniciar)."""
        w = self.worker
        self.timer.stop()
        if w is not None and w.isRunning():
            self._run += 1
            w.cancel()
            if not w.wait(5000):
                _ZOMBIES.append(w)
        self._parar_ui()

    # ---------- internos ----------
    def _estado(self, texto: str, error: bool = False):
        self.estado.setStyleSheet(f"color:{T.peligro};font-size:13px;" if error else "")
        self.estado.setText(texto)

    def _parar_ui(self):
        self.timer.stop()
        self.barra.hide()
        self.btn_cancel.hide()

    def _progreso(self) -> str:
        if not self._texto:
            extra = " (la primera vez tarda más porque se carga el modelo)" if self._seg >= 15 else ""
            return f"Cargando el modelo y analizando… {self._seg} s{extra}"
        return f"Generando… {self._seg} s"

    def _tick(self):
        self._seg += 1
        self._estado(self._progreso())

    def _chunk(self, run: int, texto: str):
        if run != self._run:
            return
        self._texto += texto
        self.salida.moveCursor(QTextCursor.End)
        self.salida.insertPlainText(texto)

    def _fin(self, run: int):
        if run != self._run:
            return
        self._parar_ui()
        self._estado(f"Completado en {self._seg} s. Es una asistencia: debe validarla el técnico.")
        self.text_ready.emit(self.text())

    def _error(self, run: int, mensaje: str):
        if run != self._run:
            return
        self._parar_ui()
        self._estado(mensaje, error=True)


class AiDialog(QDialog):
    """Ventana para una tarea de IA (resumen del historial, mensaje al cliente…)."""

    def __init__(self, repo, titulo: str, subtitulo: str, mensajes: list[dict],
                 parent=None, nota: str = ""):
        super().__init__(parent)
        self._mensajes = mensajes
        self._model = ""
        self.setWindowTitle(titulo)
        self.resize(580, 440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(8)
        t = QLabel(titulo)
        t.setObjectName("PageTitle")
        s = QLabel(subtitulo)
        s.setObjectName("Muted")
        s.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(s)
        self.panel = AiStreamPanel(altura=220, msg_cancel="Generación cancelada.")
        lay.addWidget(self.panel, 1)
        if nota:
            n = QLabel(nota)
            n.setObjectName("Muted")
            n.setWordWrap(True)
            lay.addWidget(n)
        self.ok = QLabel("")
        self.ok.setObjectName("Ok")
        lay.addWidget(self.ok)

        fila = QHBoxLayout()
        self.b_copiar = QPushButton("Copiar texto")
        self.b_copiar.setObjectName("Primary")
        self.b_copiar.clicked.connect(self._copiar)
        self.b_regen = QPushButton("Generar de nuevo")
        self.b_regen.setObjectName("Secondary")
        self.b_regen.clicked.connect(self._generar)
        cerrar = QPushButton("Cerrar")
        cerrar.setObjectName("Secondary")
        cerrar.clicked.connect(self.accept)
        for b in (self.b_copiar, self.b_regen, cerrar):
            fila.addWidget(b)
        fila.addStretch()
        lay.addLayout(fila)

        ok, model, msg = ia_config.check_ai(repo)
        if ok:
            self._model = model
            QTimer.singleShot(0, self._generar)
        else:
            self.panel.mostrar_mensaje(msg, error=True)
            self.b_copiar.setEnabled(False)
            self.b_regen.setEnabled(False)

    def _generar(self):
        self.ok.setText("")
        self.panel.start(self._model, self._mensajes)

    def _copiar(self):
        texto = self.panel.text()
        if texto:
            QApplication.clipboard().setText(texto)
            self.ok.setText("Texto copiado.")

    def done(self, r):
        self.panel.shutdown()
        super().done(r)
