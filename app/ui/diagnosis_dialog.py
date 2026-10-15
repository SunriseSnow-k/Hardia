import html
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.ai import config as ia_config
from app.ai import prompts
from app.db.health_repo import HealthRepository
from app.db.repo import Repository
from app.diagnosis.engine import diagnose
from app.ui.ai_widgets import AiStreamPanel
from app.ui.styles import ACCENT
from app.ui.widgets import AreaDesplazable, BarraPorcentaje, ChipEstado, chip_html, fecha_corta, muted, panel

ESTADO_COLORES = {
    "ATENCIÓN REQUERIDA": ("#fbe6e3", "#c0392b"),
    "REVISIÓN RECOMENDADA": ("#fbf0d9", "#b7791f"),
    "SIN HALLAZGOS RELEVANTES": ("#e1f3e8", "#2f855a"),
    "DATOS INSUFICIENTES": ("#e6eaee", "#5f6b77"),
}
SECCIONES_IA = ("Hechos", "Inferencias", "Recomendación")
_RE_SECCION = re.compile(
    r"^\s*(?:[#>*\-\s]*)\**\s*(hechos|inferencias|recomendaci[oó]n(?:es)?)\s*\**\s*:?\s*\**\s*(.*)$",
    re.IGNORECASE)


def dividir_respuesta_ia(texto: str) -> dict | None:
    """Si la respuesta de la IA viene separada en 'Hechos / Inferencias / Recomendación',
    devuelve {sección: texto}. Si falta alguna de las tres, devuelve None (texto normal)."""
    partes: dict[str, list[str]] = {}
    actual = None
    for linea in (texto or "").splitlines():
        m = _RE_SECCION.match(linea)
        if m:
            nombre = m.group(1).lower()
            actual = ("Hechos" if nombre.startswith("hech") else
                      "Inferencias" if nombre.startswith("infer") else "Recomendación")
            partes.setdefault(actual, [])
            if m.group(2).strip():
                partes[actual].append(m.group(2).strip())
        elif actual:
            partes[actual].append(linea)
    if not all(s in partes for s in SECCIONES_IA):
        return None
    return {s: "\n".join(partes[s]).strip() for s in SECCIONES_IA}


class DiagnosisDialog(QDialog):
    """Ejecuta el motor de reglas sobre un caso y muestra posibles causas.
    El análisis de IA local es opcional y no bloquea el resultado."""

    def __init__(self, repo: Repository, code: str, parent=None):
        super().__init__(parent)
        self.repo, self.code, self.saved = repo, code, False
        self.caso = repo.get_case(code)
        self.scan = repo.get_scan(code)
        self.result = diagnose(self.caso["problem"], self.scan)
        # Hallazgos de la pantalla Salud que el técnico decidió incluir (no cambian las causas)
        self.salud_items = HealthRepository(repo).included_for_case(code)
        self.ai_text = ""
        self._model = ia_config.DEFAULT_MODEL
        self.panel = None
        caso, r = self.caso, self.result

        self.setWindowTitle(f"Diagnóstico — {code}")
        self.resize(820, 820)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(10)

        t = QLabel(f'Diagnóstico — {caso["equipo"]}')
        t.setObjectName("PageTitle")
        s = muted(f'{code} · {caso["cliente"] or "Sin cliente"} · Problema: {caso["problem"]}')
        s.setStyleSheet("font-size:13px;")
        lay.addWidget(t)
        lay.addWidget(s)

        fila_est = QHBoxLayout()
        bg, fg = ESTADO_COLORES.get(r["status"], ("#e6eaee", "#5f6b77"))
        self.chip_estado = ChipEstado(r["status"], bg, fg, grande=True)
        fila_est.addWidget(self.chip_estado)
        fila_est.addStretch()
        lay.addLayout(fila_est)
        self.datos_usados = muted(self._datos_usados())
        lay.addWidget(self.datos_usados)

        inner = QWidget()
        inner.setObjectName("ScrollBody")
        cl = QVBoxLayout(inner)
        cl.setContentsMargins(0, 0, 4, 0)
        cl.setSpacing(12)

        # ---------- Causas ----------
        p_c, vc = panel("Posibles causas identificadas por el sistema")
        if not r["causes"]:
            msg = ("No se identificaron causas con los datos disponibles. Agregue más detalles "
                   "del problema o realice el escaneo del equipo." if not r["has_scan"] else
                   "Con los datos del escaneo y los síntomas no se encontraron causas relevantes.")
            vc.addWidget(muted(msg))
        for i, c in enumerate(r["causes"], 1):
            vc.addWidget(self._fila_causa(i, c))
        cl.addWidget(p_c)

        # ---------- Recomendaciones ----------
        if r["recommendations"]:
            p_r, vr = panel("Recomendaciones sugeridas")
            for i, rec in enumerate(r["recommendations"], 1):
                l = QLabel(f"<b style='color:{ACCENT}'>{i}.</b>&nbsp; {html.escape(rec)}")
                l.setTextFormat(Qt.RichText)
                l.setWordWrap(True)
                vr.addWidget(l)
            cl.addWidget(p_r)

        if self.salud_items:
            p_s, vs = panel("Hallazgos de salud incluidos por el técnico")
            for item in self.salud_items:
                l = QLabel(f"• {html.escape(item['texto'])}")
                l.setTextFormat(Qt.RichText)
                l.setWordWrap(True)
                vs.addWidget(l)
            vs.addWidget(muted("Se guardan junto con el diagnóstico; no modifican las causas propuestas por las reglas."))
            cl.addWidget(p_s)

        # ---------- Análisis de IA local (opcional) ----------
        p_ia, vi = panel("IA local (asistencia)")
        self.modelo_lbl = muted("")
        vi.addWidget(self.modelo_lbl)
        if r["causes"]:
            self.panel = AiStreamPanel(
                vacio="El análisis de la IA aparecerá aquí.",
                msg_cancel="Análisis de IA cancelado. El resultado por reglas sigue siendo válido.")
            self.panel.text_ready.connect(self._on_ai_ready)
            self.bloques = QWidget()
            self.bloques_lay = QVBoxLayout(self.bloques)
            self.bloques_lay.setContentsMargins(0, 0, 0, 0)
            self.bloques_lay.setSpacing(8)
            self.bloques.hide()
            self.b_ia = QPushButton("Analizar con IA local")
            self.b_ia.setObjectName("Secondary")
            self.b_ia.clicked.connect(self._iniciar_ia)
            vi.addWidget(self.panel)
            vi.addWidget(self.bloques)
            vi.addWidget(self.b_ia, alignment=Qt.AlignLeft)
            ok, self._model, msg = ia_config.check_ai(repo)
            self.modelo_lbl.setText(f"Modelo: {self._model}. La IA no decide el diagnóstico: "
                                    "solo explica el resultado por reglas.")
            if not ok:
                self.panel.mostrar_mensaje(msg)
            elif ia_config.load(repo)["mode"] == "completo":
                QTimer.singleShot(0, self._iniciar_ia)
        else:
            self.modelo_lbl.setText("Sin causas identificadas: no se ejecuta la IA para evitar "
                                    "conclusiones sin datos.")
        cl.addWidget(p_ia)
        cl.addStretch()

        scroll = AreaDesplazable(inner)
        lay.addWidget(scroll, 1)

        aviso = QFrame()
        aviso.setObjectName("Alert")
        av = QHBoxLayout(aviso)
        av.setContentsMargins(14, 10, 14, 10)
        icono = QLabel("⚠")
        icono.setStyleSheet("color:#b7791f; font-size:16px; font-weight:600;")
        al = QLabel(f"<b>Validación del técnico:</b> {html.escape(r['disclaimer'])}")
        al.setTextFormat(Qt.RichText)
        al.setWordWrap(True)
        av.addWidget(icono, alignment=Qt.AlignTop)
        av.addWidget(al, 1)
        lay.addWidget(aviso)

        self.ok = QLabel("")
        self.ok.setObjectName("Ok")
        lay.addWidget(self.ok)

        fila = QHBoxLayout()
        self.b_guardar = QPushButton("Guardar diagnóstico")
        self.b_guardar.setObjectName("Primary")
        self.b_guardar.clicked.connect(self._guardar)
        self.b_cerrar = QPushButton("Cerrar sin guardar")
        self.b_cerrar.setObjectName("Secondary")
        self.b_cerrar.clicked.connect(self.accept)
        fila.addWidget(self.b_guardar)
        fila.addWidget(self.b_cerrar)
        fila.addStretch()
        lay.addLayout(fila)

    # ---------- construcción ----------
    def _datos_usados(self) -> str:
        r = self.result
        if r["has_scan"]:
            fecha = fecha_corta((self.scan or {}).get("scanned_at", "")) or "fecha desconocida"
            captura = f"captura del {fecha}"
        else:
            captura = "sin captura de hardware (solo síntomas)"
        sintomas = ", ".join(r["symptoms_detected"]) or "ninguno reconocido en el texto"
        salud = (f" · salud del equipo: {len(self.salud_items)} hallazgo(s) incluido(s)"
                 if self.salud_items else "")
        return f"Datos usados: {captura} · síntomas: {sintomas}{salud} · método: reglas"

    def _fila_causa(self, i: int, c: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        g = QGridLayout(card)
        g.setContentsMargins(12, 10, 12, 10)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(4)
        num = QLabel(str(i))
        num.setAlignment(Qt.AlignCenter)
        num.setFixedSize(26, 26)
        num.setStyleSheet(f"background:#e1f0f5; color:{ACCENT}; border-radius:13px; font-weight:600;")
        causa = QLabel(f'<b>{html.escape(c["cause"])}</b><br>'
                       f'<span style="color:#5f6b77;font-size:12px">{html.escape(c["category"])} · '
                       f'Regla {html.escape(c["id"])}</span>')
        causa.setTextFormat(Qt.RichText)
        causa.setWordWrap(True)
        evid = QLabel(" ".join(chip_html(e, "#eef1f4", "#1b2430") for e in c["evidence"])
                      or "<span style='color:#5f6b77'>Sin evidencia registrada</span>")
        evid.setTextFormat(Qt.RichText)
        evid.setWordWrap(True)
        evid.setToolTip("Evidencia usada por la regla")
        pct = round(c["confidence"] * 100)
        conf = QLabel(f'Confianza {c["confidence_label"]} · {pct} %')
        conf.setObjectName("Muted")
        barra = BarraPorcentaje(pct, color=ACCENT, alto=6, mostrar_numero=False)
        barra.setFixedWidth(150)

        g.addWidget(num, 0, 0, 2, 1, Qt.AlignTop)
        g.addWidget(causa, 0, 1)
        g.addWidget(ChipEstado(c["priority"]), 0, 2, Qt.AlignRight | Qt.AlignTop)
        g.addWidget(evid, 1, 1)
        derecha = QVBoxLayout()
        derecha.setSpacing(2)
        derecha.addWidget(conf, alignment=Qt.AlignRight)
        derecha.addWidget(barra, alignment=Qt.AlignRight)
        g.addLayout(derecha, 1, 2)
        g.setColumnStretch(1, 1)
        return card

    def _mostrar_bloques(self, texto: str):
        while self.bloques_lay.count():
            w = self.bloques_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        partes = dividir_respuesta_ia(texto)
        if not partes:
            self.bloques.hide()
            self.panel.salida.show()
            return
        for titulo, contenido in partes.items():
            f = QFrame()
            f.setObjectName("Card")
            v = QVBoxLayout(f)
            v.setContentsMargins(12, 8, 12, 8)
            h = QLabel(titulo)
            h.setStyleSheet(f"font-weight:600; color:{ACCENT};")
            b = QLabel(contenido or "—")
            b.setWordWrap(True)
            b.setTextInteractionFlags(Qt.TextSelectableByMouse)
            v.addWidget(h)
            v.addWidget(b)
            self.bloques_lay.addWidget(f)
        self.panel.salida.hide()
        self.bloques.show()

    # ---------- IA ----------
    def _iniciar_ia(self):
        ok, model, msg = ia_config.check_ai(self.repo)
        if not ok:
            self.panel.mostrar_mensaje(msg, error=True)
            return
        self._model = model
        self.ai_text = ""
        self.bloques.hide()
        self.panel.salida.show()
        self.modelo_lbl.setText(f"Modelo: {model}. La IA no decide el diagnóstico: "
                                "solo explica el resultado por reglas.")
        self.panel.start(model, prompts.analysis_messages(self.caso, self.scan, self.result))

    def _on_ai_ready(self, texto: str):
        self.ai_text = texto
        self.b_ia.setText("Analizar de nuevo")
        self._mostrar_bloques(texto)

    # ---------- Guardar ----------
    def _guardar(self):
        resultado, metodo = dict(self.result), "Reglas"
        if self.salud_items:
            resultado["health_findings"] = [i["texto"] for i in self.salud_items]
        if self.ai_text:
            resultado["ai_analysis"] = self.ai_text
            resultado["ai_model"] = self._model
            metodo = "Reglas + IA local"
        self.repo.save_diagnosis(self.code, resultado, metodo)
        self.saved = True
        self.b_guardar.setEnabled(False)
        self.b_cerrar.setText("Cerrar")
        self.ok.setText(f"Diagnóstico guardado ({metodo}).")

    def done(self, r):
        if self.panel is not None:
            self.panel.shutdown()
        super().done(r)
