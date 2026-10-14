import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
                               QCheckBox, QComboBox, QLineEdit)
from app.ai import config as ia_config, prompts
from app.ai.ollama_client import TIMEOUT_RESPUESTA, list_models, has_model, OllamaError
from app.db.repo import Repository
from app.diagnosis.engine import load_rules
from app.ui.ai_widgets import AiStreamPanel
from app.ui.widgets import AreaDesplazable, cabecera, campo, muted, panel

PUEDE = (
    "Lee los datos del taller que se le entregan: el caso, el diagnóstico por reglas y la base "
    "de conocimiento.",
    "Redacta resúmenes, explicaciones y mensajes para el cliente.",
    "Funciona en este equipo, sin Internet.",
)
NO_PUEDE = (
    "No modifica nada: no guarda, no borra ni cambia casos por su cuenta.",
    "No decide el diagnóstico: la validación final siempre es del técnico.",
    "Solo usa los datos que se le entregan; puede equivocarse, así que revise siempre su texto.",
    "Sin Ollama, el programa sigue funcionando en modo reglas.",
)


def _lista(puntos, signo: str, color: str) -> QLabel:
    lbl = QLabel("<br>".join(f"<span style='color:{color};font-weight:600'>{signo}</span>&nbsp; "
                             f"{html.escape(p)}" for p in puntos))
    lbl.setTextFormat(Qt.RichText)
    lbl.setWordWrap(True)
    return lbl


class IaLocalPage(QWidget):
    settings_changed = Signal()

    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(8)
        textos, _t, _s = cabecera("IA local",
                                  "Asistente opcional que funciona en este equipo, sin Internet. "
                                  "Nunca decide el diagnóstico: solo redacta y resume.")
        outer.addLayout(textos)

        inner = QWidget()
        inner.setObjectName("ScrollBody")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(12)
        scroll = AreaDesplazable(inner)
        outer.addWidget(scroll, 1)

        arriba = QGridLayout()
        arriba.setHorizontalSpacing(12)

        # --- Estado y configuración ---
        p1, v1 = panel("Estado")
        self.estado = QLabel("")
        self.estado.setTextFormat(Qt.RichText)
        self.estado.setWordWrap(True)
        v1.addWidget(self.estado)
        self.chk = QCheckBox("Activar IA local")
        self.cb_modelo = QComboBox()
        self.cb_modelo.setEditable(True)
        self.cb_modo = QComboBox()
        self.cb_modo.addItem("Rápido (solo reglas; la IA se pide con un botón)", "rapido")
        self.cb_modo.addItem("Completo (reglas + análisis automático de IA)", "completo")
        v1.addWidget(self.chk)
        fila_c = QHBoxLayout()
        fila_c.addWidget(campo("Modelo", self.cb_modelo), 1)
        fila_c.addWidget(campo("Modo de diagnóstico", self.cb_modo), 1)
        v1.addLayout(fila_c)
        v1.addWidget(muted(f"Tiempo máximo de espera de una respuesta: {TIMEOUT_RESPUESTA} s "
                           "(valor fijo del programa)."))
        fila = QHBoxLayout()
        b_save = QPushButton("Guardar")
        b_save.setObjectName("Primary")
        b_save.clicked.connect(self._guardar)
        b_test = QPushButton("Probar conexión")
        b_test.setObjectName("Secondary")
        b_test.setToolTip("Envía una consulta corta al modelo y mide cuánto tarda")
        b_test.clicked.connect(self._probar)
        b_chk = QPushButton("Comprobar de nuevo")
        b_chk.setObjectName("Secondary")
        b_chk.clicked.connect(self.refresh)
        fila.addWidget(b_save)
        fila.addWidget(b_test)
        fila.addWidget(b_chk)
        fila.addStretch()
        v1.addLayout(fila)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        v1.addWidget(self.msg)
        self.test_panel = AiStreamPanel(altura=50, msg_cancel="Prueba cancelada.")
        v1.addWidget(self.test_panel)
        arriba.addWidget(p1, 0, 0)

        # --- Qué puede y qué no ---
        p2, v2 = panel("Qué puede y qué no")
        v2.addWidget(_lista(PUEDE, "✓", "#2f855a"))
        v2.addSpacing(6)
        v2.addWidget(_lista(NO_PUEDE, "✕", "#c0392b"))
        v2.addStretch()
        arriba.addWidget(p2, 0, 1)
        arriba.setColumnStretch(0, 3)
        arriba.setColumnStretch(1, 2)
        lay.addLayout(arriba)

        # --- Soporte ---
        p3, v3 = panel("Consultar soporte")
        v3.addWidget(muted("Pregunte sobre un problema; la respuesta se apoya en la base de "
                           "conocimiento local."))
        self.pregunta = QLineEdit()
        self.pregunta.setPlaceholderText("Ej.: ¿Qué reviso si el equipo se calienta y el ventilador suena fuerte?")
        self.pregunta.returnPressed.connect(self._preguntar)
        b_ask = QPushButton("Preguntar")
        b_ask.setObjectName("Secondary")
        b_ask.clicked.connect(self._preguntar)
        fila_p = QHBoxLayout()
        fila_p.addWidget(self.pregunta, 1)
        fila_p.addWidget(b_ask)
        v3.addLayout(fila_p)
        self.soporte = AiStreamPanel(vacio="La respuesta aparecerá aquí.", altura=130,
                                     msg_cancel="Consulta cancelada.")
        v3.addWidget(self.soporte)
        lay.addWidget(p3)

        # --- Ayuda ---
        p4, v4 = panel("Instalación del modelo")
        txt = QLabel(
            "1. Instale Ollama desde ollama.com y déjelo en ejecución.<br>"
            "2. En una terminal: <b>ollama pull llama3.2:3b</b> (o <b>llama3.2:1b</b> si el equipo es modesto).<br>"
            "3. Pulse «Probar conexión» para medir cuánto tarda en este equipo.<br>"
            "Si es lento, use el modo Rápido: el diagnóstico por reglas no depende de la IA.")
        txt.setTextFormat(Qt.RichText)
        txt.setWordWrap(True)
        v4.addWidget(txt)
        lay.addWidget(p4)
        lay.addStretch()
        self.refresh()

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
                "<b style='color:#c0392b'>● Ollama no disponible.</b> Instálelo desde ollama.com y "
                "déjelo en ejecución. Mientras tanto el sistema trabaja solo con reglas.")
        elif not has_model(instalados, cfg["model"]):
            self.estado.setText(
                f"<b style='color:#b7791f'>● Ollama disponible.</b> El modelo <b>{m}</b> no está instalado. "
                f"En una terminal ejecute: <b>ollama pull {m}</b>")
        else:
            lista = html.escape(", ".join(instalados))
            self.estado.setText(
                f"<b style='color:#2f855a'>● Ollama disponible · modelo {m} listo.</b><br>"
                f"<span style='color:#5f6b77'>Modelos instalados: {lista}</span>")

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
