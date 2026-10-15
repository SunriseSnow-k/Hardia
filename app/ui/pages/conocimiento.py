import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.diagnosis.engine import load_rules, normalizar
from app.reports.cliente import implication
from app.ui.styles import ACCENT
from app.ui.tema import T
from app.ui.widgets import AreaDesplazable, ChipEstado, cabecera, chip_html, colores_de, limpiar_layout, muted, panel


class ConocimientoPage(QWidget):
    """Consulta de solo lectura de la base de conocimiento local."""

    def __init__(self):
        super().__init__()
        self.rules = load_rules()
        self.cat = "Todas"
        self._visibles: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(12)
        textos, _t, _s = cabecera("Base de conocimiento",
                                  f"● Base de conocimiento local · solo lectura · {len(self.rules)} reglas")
        root.addLayout(textos)

        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText("Buscar por causa, síntoma, palabra clave o recomendación…")
        self.buscar.setClearButtonEnabled(True)
        self.buscar.textChanged.connect(self._construir)
        root.addWidget(self.buscar)

        fila = QHBoxLayout()
        self.chips: dict[str, QPushButton] = {}
        for c in ["Todas", *sorted({r["category"] for r in self.rules})]:
            b = QPushButton(c)
            b.setObjectName("ChipBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=c: self._set_cat(c))
            self.chips[c] = b
            fila.addWidget(b)
        fila.addStretch()
        root.addLayout(fila)
        self.chips["Todas"].setChecked(True)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(14)
        p_lista, vl = panel(margen=0)
        vl.setContentsMargins(0, 10, 0, 0)
        self.cuenta = muted("")
        self.cuenta.setContentsMargins(14, 0, 14, 4)
        vl.addWidget(self.cuenta)
        self.lista = QListWidget()
        self.lista.setObjectName("RuleList")
        self.lista.setWordWrap(True)
        self.lista.currentRowChanged.connect(self._mostrar)
        vl.addWidget(self.lista, 1)
        cuerpo.addWidget(p_lista, 2)

        p_det, vd = panel()
        det_w = QWidget()
        det_w.setObjectName("ScrollBody")
        self.detalle = QVBoxLayout(det_w)
        self.detalle.setContentsMargins(0, 0, 6, 0)
        self.detalle.setSpacing(10)
        sc = AreaDesplazable(det_w)
        vd.addWidget(sc, 1)
        cuerpo.addWidget(p_det, 3)
        root.addLayout(cuerpo, 1)
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
        texto = " ".join([r["id"], r["cause"], r["category"],
                          *[s["name"] for s in r["symptoms"]],
                          *[k for s in r["symptoms"] for k in s.get("keywords", [])],
                          *r["recommendations"]])
        return q in normalizar(texto)

    def _construir(self):
        q = normalizar(self.buscar.text())
        self._visibles = [r for r in self.rules if self._coincide(r, q)]
        self.cuenta.setText(f"{len(self._visibles)} de {len(self.rules)} reglas")
        self.lista.blockSignals(True)
        self.lista.clear()
        for r in self._visibles:
            item = QListWidgetItem(f'{r["id"]} · {r["category"]} · {r["priority"]}\n{r["cause"]}')
            item.setToolTip(r["cause"])
            self.lista.addItem(item)
        self.lista.blockSignals(False)
        if self._visibles:
            self.lista.setCurrentRow(0)
            self._mostrar(0)
        else:
            self._mostrar(-1)

    def _seccion(self, titulo: str, contenido: QWidget | str):
        h = QLabel(titulo)
        h.setStyleSheet(f"font-weight:600; color:{T.texto_suave}; font-size:12px;")
        self.detalle.addWidget(h)
        if isinstance(contenido, str):
            lbl = QLabel(contenido)
            lbl.setTextFormat(Qt.RichText)
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            contenido = lbl
        self.detalle.addWidget(contenido)

    def _mostrar(self, fila: int):
        limpiar_layout(self.detalle)
        if not 0 <= fila < len(self._visibles):
            self.detalle.addWidget(muted("No hay reglas que coincidan con la búsqueda."))
            self.detalle.addStretch()
            return
        r = self._visibles[fila]
        titulo = QLabel(r["cause"])
        titulo.setObjectName("SectionTitle")
        titulo.setWordWrap(True)
        self.detalle.addWidget(titulo)
        chips = QHBoxLayout()
        chips.addWidget(ChipEstado(f'Regla {r["id"]}', T.acento_suave, ACCENT))
        chips.addWidget(ChipEstado(r["category"], T.fondo_app, T.texto))
        chips.addWidget(ChipEstado(f'Prioridad {r["priority"]}', *colores_de(r["priority"])))
        chips.addStretch()
        self.detalle.addLayout(chips)

        sint = " ".join(chip_html(s["name"], T.acento_suave, ACCENT) for s in r["symptoms"])
        self._seccion("SÍNTOMAS", sint or f"<span style='color:{T.texto_suave}'>Sin síntomas definidos</span>")
        claves = sorted({k for s in r["symptoms"] for k in s.get("keywords", [])})
        self._seccion("PALABRAS CLAVE", html.escape(", ".join(claves)) or "—")
        cond = r.get("conditions", [])
        self._seccion("CONDICIONES CON DATOS DEL EQUIPO",
                      "<br>".join(f"• {html.escape(c['label'])}" for c in cond)
                      or f"<span style='color:{T.texto_suave}'>Solo usa los síntomas descritos</span>")
        self._seccion("RECOMENDACIONES", "<br>".join(
            f"<b style='color:{ACCENT}'>{i}.</b> {html.escape(x)}"
            for i, x in enumerate(r["recommendations"], 1)))
        self._seccion("QUÉ SIGNIFICA PARA EL CLIENTE", html.escape(implication({"id": r["id"]})))
        minimos = []
        if r.get("min_evidence"):
            minimos.append(f'evidencia mínima {r["min_evidence"]}')
        if r.get("min_confidence"):
            minimos.append(f'confianza mínima {round(r["min_confidence"] * 100)} %')
        if minimos:
            self.detalle.addWidget(muted("Se propone solo con " + " y ".join(minimos) + "."))
        self.detalle.addStretch()
