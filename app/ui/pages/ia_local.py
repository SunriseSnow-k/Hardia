import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QFrame, QCheckBox, QComboBox, QLineEdit, QScrollArea)
from app.ai import config as ia_config, prompts
from app.ai.ollama_client import list_models, has_model, OllamaError
from app.db.repo import Repository
from app.diagnosis.engine import load_rules
from app.ui.ai_widgets import AiStreamPanel


class IaLocalPage(QWidget):
    settings_changed = Signal()

    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(8)
        t = QLabel("IA local")
        t.setObjectName("PageTitle")
        s = QLabel("Asistente opcional que funciona en este equipo, sin Internet. "
                   "Nunca decide el diagnóstico: solo redacta y resume.")
        s.setObjectName("Muted")
        s.setWordWrap(True)
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

        # --- Estado ---
        p1, v1 = self._panel("Estado")
        self.estado = QLabel("")
        self.estado.setTextFormat(Qt.RichText)
        self.estado.setWordWrap(True)
        b_chk = QPushButton("Comprobar de nuevo")
        b_chk.setObjectName("Secondary")
        b_chk.clicked.connect(self.refresh)
        v1.addWidget(self.estado)
        v1.addWidget(b_chk, alignment=Qt.AlignLeft)
        lay.addWidget(p1)

        # --- Configuración ---
        p2, v2 = self._panel("Configuración")
        self.chk = QCheckBox("Activar IA local")
        self.cb_modelo = QComboBox()
        self.cb_modelo.setEditable(True)
        self.cb_modo = QComboBox()
        self.cb_modo.addItem("Rápido (solo reglas; la IA se pide con un botón)", "rapido")
        self.cb_modo.addItem("Completo (reglas + análisis automático de IA)", "completo")
        for etiqueta, w in (("Modelo", self.cb_modelo), ("Modo de diagnóstico", self.cb_modo)):
            l = QLabel(etiqueta)
            l.setObjectName("Muted")
            v2.addWidget(l)
            v2.addWidget(w)
        v2.insertWidget(1, self.chk)
        fila = QHBoxLayout()
        b_save = QPushButton("Guardar configuración")
        b_save.setObjectName("Primary")
        b_save.clicked.connect(self._guardar)
        b_test = QPushButton("Probar modelo")
        b_test.setObjectName("Secondary")
        b_test.clicked.connect(self._probar)
        fila.addWidget(b_save)
        fila.addWidget(b_test)
        fila.addStretch()
        v2.addLayout(fila)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        v2.addWidget(self.msg)
        self.test_panel = AiStreamPanel(altura=50, msg_cancel="Prueba cancelada.")
        v2.addWidget(self.test_panel)
        lay.addWidget(p2)

        # --- Soporte ---
        p3, v3 = self._panel("Consultar soporte")
        ayuda = QLabel("Pregunte sobre un problema; la respuesta se apoya en la base de conocimiento local.")
        ayuda.setObjectName("Muted")
        ayuda.setWordWrap(True)
        self.pregunta = QLineEdit()
        self.pregunta.setPlaceholderText("Ej.: ¿Qué reviso si el equipo se calienta y el ventilador suena fuerte?")
        self.pregunta.returnPressed.connect(self._preguntar)
        b_ask = QPushButton("Preguntar")
        b_ask.setObjectName("Primary")
        b_ask.clicked.connect(self._preguntar)
        self.soporte = AiStreamPanel(vacio="La respuesta aparecerá aquí.", altura=130,
                                     msg_cancel="Consulta cancelada.")
        for w in (ayuda, self.pregunta):
            v3.addWidget(w)
        v3.addWidget(b_ask, alignment=Qt.AlignLeft)
        v3.addWidget(self.soporte)
        lay.addWidget(p3)

        # --- Ayuda ---
        p4, v4 = self._panel("Instalación del modelo")
        txt = QLabel(
            "1. Instale Ollama desde ollama.com y déjelo en ejecución.<br>"
            "2. En una terminal: <b>ollama pull llama3.2:3b</b> (o <b>llama3.2:1b</b> si el equipo es modesto).<br>"
            "3. Pulse «Probar modelo» para medir cuánto tarda en este equipo.<br>"
            "Si es lento, use el modo Rápido: el diagnóstico por reglas no depende de la IA.")
        txt.setTextFormat(Qt.RichText)
        txt.setWordWrap(True)
        v4.addWidget(txt)
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

    def _set_msg(self, texto: str, ok: bool = True):
        self.msg.setStyleSheet("color:#2f855a;font-weight:600;" if ok else "color:#c0392b;")
        self.msg.setText(texto)

    def refresh(self):
        cfg = ia_config.load(self.repo)
        try:
            instalados = list_models()
        except OllamaError:
            instalados = None

        nombres = []
        for n in [cfg["model"], *(instalados or []), *ia_config.MODELOS_SUGERIDOS]:
            if n not in nombres:
                nombres.append(n)
        self.cb_modelo.clear()
        self.cb_modelo.addItems(nombres)
        self.cb_modelo.setCurrentText(cfg["model"])
        self.chk.setChecked(cfg["enabled"])
        self.cb_modo.setCurrentIndex(0 if cfg["mode"] == "rapido" else 1)

        m = html.escape(cfg["model"])
        if instalados is None:
            self.estado.setText(
                "<b style='color:#c0392b'>● Ollama no detectado.</b> Instálelo desde ollama.com y "
                "déjelo en ejecución. Mientras tanto el sistema trabaja solo con reglas.")
        elif not has_model(instalados, cfg["model"]):
            self.estado.setText(
                f"<b style='color:#b7791f'>● Ollama detectado.</b> El modelo <b>{m}</b> no está instalado. "
                f"En una terminal ejecute: <b>ollama pull {m}</b>")
        else:
            lista = html.escape(", ".join(instalados))
            self.estado.setText(
                f"<b style='color:#2f855a'>● Ollama detectado · modelo {m} listo.</b><br>"
                f"<span style='color:#66727f'>Modelos instalados: {lista}</span>")

    def _guardar(self):
        modelo = self.cb_modelo.currentText().strip() or ia_config.DEFAULT_MODEL
        ia_config.save(self.repo, self.chk.isChecked(), modelo, self.cb_modo.currentData())
        self.settings_changed.emit()
        self.refresh()
        self._set_msg("Configuración guardada.")

    def _probar(self):
        modelo = self.cb_modelo.currentText().strip()
        try:
            instalados = list_models()
        except OllamaError:
            self._set_msg("No se detectó Ollama. Inicie Ollama e inténtelo de nuevo.", ok=False)
            return
        if not has_model(instalados, modelo):
            self._set_msg(f"El modelo {modelo} no está instalado. En una terminal ejecute: "
                          f"ollama pull {modelo}", ok=False)
            return
        self._set_msg("Probando el modelo…")
        self.test_panel.start(modelo, prompts.test_messages())

    def _preguntar(self):
        pregunta = self.pregunta.text().strip()
        if not pregunta:
            self.soporte.mostrar_mensaje("Escriba una pregunta.", error=True)
            return
        ok, model, msg = ia_config.check_ai(self.repo)
        if not ok:
            self.soporte.mostrar_mensaje(msg, error=True)
            return
        reglas = prompts.relevant_rules(pregunta, load_rules())
        self.soporte.start(model, prompts.support_messages(pregunta, reglas))

    def shutdown(self):
        self.test_panel.shutdown()
        self.soporte.shutdown()