import html

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QFrame, QScrollArea, QWidget)
from app.ai import config as ia_config, prompts
from app.db.repo import Repository
from app.diagnosis.engine import diagnose
from app.ui.ai_widgets import AiStreamPanel
from app.ui.styles import PRIORITY_COLORS

ESTADO_COLORES = {
    "ATENCIÓN REQUERIDA": ("#fbe6e3", "#c0392b"),
    "REVISIÓN RECOMENDADA": ("#fbf0d9", "#b7791f"),
    "SIN HALLAZGOS RELEVANTES": ("#e1f3e8", "#2f855a"),
    "DATOS INSUFICIENTES": ("#e6eaee", "#66727f"),
}


def tag_html(prioridad: str) -> str:
    bg, fg = PRIORITY_COLORS.get(prioridad, ("#eee", "#333"))
    return (f'<span style="background:{bg};color:{fg};font-weight:600">'
            f'&nbsp;{html.escape(prioridad)}&nbsp;</span>')


class DiagnosisDialog(QDialog):
    """Ejecuta el motor de reglas sobre un caso y muestra posibles causas.
    El análisis de IA local es opcional y no bloquea el resultado."""

    def __init__(self, repo: Repository, code: str, parent=None):
        super().__init__(parent)
        self.repo, self.code, self.saved = repo, code, False
        self.caso = repo.get_case(code)
        self.scan = repo.get_scan(code)
        self.result = diagnose(self.caso["problem"], self.scan)
        self.ai_text = ""
        self._model = ia_config.DEFAULT_MODEL
        self.panel = None
        caso, r = self.caso, self.result

        self.setWindowTitle(f"Diagnóstico — {code}")
        self.resize(680, 760)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(8)

        t = QLabel(f'Diagnóstico — {caso["equipo"]}')
        t.setObjectName("PageTitle")
        s = QLabel(f'{code} · {caso["cliente"] or "Sin cliente"} · Problema: {caso["problem"]}')
        s.setObjectName("Muted")
        s.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(s)

        fuente = ("Incluye los datos del escaneo del equipo." if r["has_scan"] else
                  "Sin datos de escaneo: el resultado se basa solo en los síntomas.")
        f = QLabel(fuente)
        f.setObjectName("Muted")
        lay.addWidget(f)

        bg, fg = ESTADO_COLORES.get(r["status"], ("#e6eaee", "#66727f"))
        estado = QLabel(r["status"])
        estado.setAlignment(Qt.AlignCenter)
        estado.setStyleSheet(f"background:{bg};color:{fg};font-weight:700;"
                             "border-radius:4px;padding:8px;")
        lay.addWidget(estado)

        inner = QWidget()
        cl = QVBoxLayout(inner)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)

        h1 = QLabel("Posibles causas identificadas por el sistema")
        h1.setObjectName("SectionTitle")
        cl.addWidget(h1)
        if not r["causes"]:
            msg = ("No se identificaron causas con los datos disponibles. Agregue más detalles "
                   "del problema o realice el escaneo del equipo." if not r["has_scan"] else
                   "Con los datos del escaneo y los síntomas no se encontraron causas relevantes.")
            vacio = QLabel(msg)
            vacio.setWordWrap(True)
            vacio.setObjectName("Muted")
            cl.addWidget(vacio)
        for i, c in enumerate(r["causes"], 1):
            card = QFrame()
            card.setObjectName("Card")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(12, 10, 12, 10)
            ev = "; ".join(c["evidence"])
            lbl = QLabel(
                f'<b>{i}. {html.escape(c["cause"])}</b> &nbsp;{tag_html(c["priority"])}'
                f'<br><span style="color:#66727f">{html.escape(c["category"])} · '
                f'Confianza {c["confidence_label"]} ({round(c["confidence"] * 100)} %)</span>'
                f'<br><span style="color:#66727f">Evidencia: {html.escape(ev)}</span>')
            lbl.setTextFormat(Qt.RichText)
            lbl.setWordWrap(True)
            cv.addWidget(lbl)
            cl.addWidget(card)

        if r["recommendations"]:
            h2 = QLabel("Recomendaciones sugeridas")
            h2.setObjectName("SectionTitle")
            cl.addWidget(h2)
            for i, rec in enumerate(r["recommendations"], 1):
                l = QLabel(f"{i}. {rec}")
                l.setWordWrap(True)
                cl.addWidget(l)

        # ---------- Análisis de IA local (opcional) ----------
        h3 = QLabel("Análisis de IA local (opcional)")
        h3.setObjectName("SectionTitle")
        cl.addWidget(h3)
        if r["causes"]:
            self.panel = AiStreamPanel(
                vacio="El análisis de la IA aparecerá aquí.",
                msg_cancel="Análisis de IA cancelado. El resultado por reglas sigue siendo válido.")
            self.panel.text_ready.connect(self._on_ai_ready)
            self.b_ia = QPushButton("Analizar con IA local")
            self.b_ia.setObjectName("Secondary")
            self.b_ia.clicked.connect(self._iniciar_ia)
            cl.addWidget(self.panel)
            cl.addWidget(self.b_ia, alignment=Qt.AlignLeft)
            ok, self._model, msg = ia_config.check_ai(repo)
            if not ok:
                self.panel.mostrar_mensaje(msg)
            elif ia_config.load(repo)["mode"] == "completo":
                QTimer.singleShot(0, self._iniciar_ia)
        else:
            nota = QLabel("Sin causas identificadas: no se ejecuta la IA para evitar "
                          "conclusiones sin datos.")
            nota.setObjectName("Muted")
            nota.setWordWrap(True)
            cl.addWidget(nota)
        cl.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        aviso = QFrame()
        aviso.setObjectName("Alert")
        av = QVBoxLayout(aviso)
        al = QLabel(r["disclaimer"])
        al.setWordWrap(True)
        av.addWidget(al)
        lay.addWidget(aviso)

        self.ok = QLabel("")
        self.ok.setObjectName("Ok")
        lay.addWidget(self.ok)

        fila = QHBoxLayout()
        self.b_guardar = QPushButton("Guardar diagnóstico")
        self.b_guardar.setObjectName("Primary")
        self.b_guardar.clicked.connect(self._guardar)
        cerrar = QPushButton("Cerrar")
        cerrar.setObjectName("Secondary")
        cerrar.clicked.connect(self.accept)
        fila.addWidget(self.b_guardar)
        fila.addWidget(cerrar)
        fila.addStretch()
        lay.addLayout(fila)

    # ---------- IA ----------
    def _iniciar_ia(self):
        ok, model, msg = ia_config.check_ai(self.repo)
        if not ok:
            self.panel.mostrar_mensaje(msg, error=True)
            return
        self._model = model
        self.ai_text = ""
        self.panel.start(model, prompts.analysis_messages(self.caso, self.scan, self.result))

    def _on_ai_ready(self, texto: str):
        self.ai_text = texto
        self.b_ia.setText("Analizar de nuevo")

    # ---------- Guardar ----------
    def _guardar(self):
        resultado, metodo = dict(self.result), "Reglas"
        if self.ai_text:
            resultado["ai_analysis"] = self.ai_text
            resultado["ai_model"] = self._model
            metodo = "Reglas + IA local"
        self.repo.save_diagnosis(self.code, resultado, metodo)
        self.saved = True
        self.b_guardar.setEnabled(False)
        self.ok.setText(f"Diagnóstico guardado ({metodo}).")

    def done(self, r):
        if self.panel is not None:
            self.panel.shutdown()
        super().done(r)