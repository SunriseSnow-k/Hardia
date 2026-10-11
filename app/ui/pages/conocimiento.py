import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QFrame, QScrollArea)
from app.diagnosis.engine import load_rules, normalizar
from app.ui.styles import PRIORITY_COLORS


class ConocimientoPage(QWidget):
    """Consulta de solo lectura de la base de conocimiento local."""

    def __init__(self):
        super().__init__()
        self.rules = load_rules()
        self.cat = "Todas"

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(12)
        t = QLabel("Base de conocimiento")
        t.setObjectName("PageTitle")
        s = QLabel(f"● Base de conocimiento local · solo lectura · {len(self.rules)} reglas")
        s.setObjectName("Muted")
        root.addWidget(t)
        root.addWidget(s)

        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText("Buscar en la base de conocimiento…")
        self.buscar.textChanged.connect(self._construir)
        root.addWidget(self.buscar)

        fila = QHBoxLayout()
        self.chips: dict[str, QPushButton] = {}
        for c in ["Todas", *sorted({r["category"] for r in self.rules})]:
            b = QPushButton(c)
            b.setObjectName("ChipBtn")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, c=c: self._set_cat(c))
            self.chips[c] = b
            fila.addWidget(b)
        fila.addStretch()
        root.addLayout(fila)
        self.chips["Todas"].setChecked(True)

        self.cuenta = QLabel("")
        self.cuenta.setObjectName("Muted")
        root.addWidget(self.cuenta)

        self.inner = QWidget()
        self.lista = QVBoxLayout(self.inner)
        self.lista.setContentsMargins(0, 0, 0, 0)
        self.lista.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.inner)
        root.addWidget(scroll, 1)
        self._construir()

    def _set_cat(self, cat: str):
        self.cat = cat
        for nombre, b in self.chips.items():
            b.setChecked(nombre == cat)
        self._construir()

    def _coincide(self, r: dict, q: str) -> bool:
        if self.cat != "Todas" and r["category"] != self.cat:
            return False
        if not q:
            return True
        texto = " ".join([r["cause"], r["category"],
                          *[s["name"] for s in r["symptoms"]], *r["recommendations"]])
        return q in normalizar(texto)

    def _construir(self):
        while self.lista.count():
            item = self.lista.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        q = normalizar(self.buscar.text())
        reglas = [r for r in self.rules if self._coincide(r, q)]
        self.cuenta.setText(f"{len(reglas)} de {len(self.rules)} reglas")
        for r in reglas:
            card = QFrame()
            card.setObjectName("Panel")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(14, 10, 14, 10)
            bg, fg = PRIORITY_COLORS.get(r["priority"], ("#eee", "#333"))
            sint = ", ".join(s["name"] for s in r["symptoms"]) or "—"
            cond = "; ".join(c["label"] for c in r.get("conditions", [])) or "—"
            recs = " · ".join(r["recommendations"])
            lbl = QLabel(
                f'<b>{html.escape(r["cause"])}</b> &nbsp;'
                f'<span style="background:{bg};color:{fg};font-weight:600">&nbsp;{r["priority"]}&nbsp;</span>'
                f'<br><span style="color:#66727f">{html.escape(r["category"])} · Regla {r["id"]}</span>'
                f'<br><b>Síntomas:</b> {html.escape(sint)}'
                f'<br><b>Datos del equipo:</b> {html.escape(cond)}'
                f'<br><b>Recomendaciones:</b> {html.escape(recs)}')
            lbl.setTextFormat(Qt.RichText)
            lbl.setWordWrap(True)
            cv.addWidget(lbl)
            self.lista.addWidget(card)
        self.lista.addStretch()