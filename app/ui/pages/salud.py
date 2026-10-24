"""Salud del equipo: estado de cada componente y rendimiento frente a sus valores de fábrica.

La lógica está en app/health (sin Qt); esta pantalla solo la muestra. El resultado es una
asistencia: los porcentajes son orientativos y la validación es del técnico."""
import html

from PySide6.QtCore import QEventLoop, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.db.hardware_repo import QAKM_HardwareRepository
from app.db.health_repo import QAKM_HealthRepository
from app.db.notes_repo import QAKM_NotesRepository
from app.db.repo import QAKM_Repository
from app.db.search_repo import QAKM_SearchQueries
from app.hardware.inventory import FUERTES_LOCAL, identifiers_from_scan
from app.hardware.scanner import COMPONENT_NAMES, local_identifiers
from app.health import ATENCION, BUENO, REVISAR, SIN_REF, componente, evaluate, load_references
from app.ui.inventory_dialog import MVCD_InventoryDialog
from app.ui.tema import T
from app.ui.widgets import (
    MVCD_AreaDesplazable,
    MVCD_BarraPorcentaje,
    MVCD_ChipEstado,
    ajustar_alto_tabla,
    cabecera,
    celda,
    color_estado,
    fecha_corta,
    item_medida,
    muted,
    panel,
    vaciar_tabla,
)

MAX_CASOS_COMBO = 50
COLUMNAS = ["Componente", "Estado", "Medido ahora", "De fábrica", "Respecto a fábrica", "Fuente del dato", ""]
ANCHOS = {0: 210, 2: 170, 3: 170, 4: 170, 6: 100}  # el resto se ajusta al contenido o al espacio libre
NOTA_FINAL = ("Cómo leer esta pantalla: cada componente se compara con su valor de fábrica (100 %). Los "
              "porcentajes salen de datos leídos del sistema (Windows o Linux) o medidos por la prueba de rendimiento; lo que "
              "no tiene medición o referencia aparece como «Sin referencia» con su motivo. El índice es "
              "orientativo: es una asistencia y la validación final es del técnico.")


def _pct_txt(c: dict) -> str:
    return f'{c["pct"]:.0f} %' if c.get("pct") is not None else (c.get("alt") or "Sin referencia")


def misma_maquina(scan: dict, locales) -> bool | None:
    """True si la captura es de este equipo (coincide un identificador fuerte), False si no,
    None si la captura no tiene identificadores fuertes para comprobarlo."""
    de_captura = {(k, v) for k, v in identifiers_from_scan(scan) if k in FUERTES_LOCAL}
    if not de_captura:
        return None
    return bool(de_captura & {(k, v) for k, v in locales if k in FUERTES_LOCAL})


# ---------------- detalle de un componente ----------------
class MVCD_DetalleComponenteDialog(QDialog):
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    """% grande, cálculo, barras medido/referencia, datos de Windows, evolución entre
    inspecciones, qué significa y qué hacer."""

    def __init__(self, repo: QAKM_Repository, code: str | None, comp: dict, historial: list[dict], parent=None):
        super().__init__(parent)
        self.repo, self.code, self.comp = repo, code, comp
        self.hr = QAKM_HealthRepository(repo)
        self.tech_id = getattr(repo, "session_tech", "") or ""
        self.setWindowTitle(f'Salud — {comp["nombre"]}')
        self.resize(760, 760)
        exterior = QVBoxLayout(self)
        exterior.setContentsMargins(0, 0, 0, 12)
        cuerpo = QWidget()
        cuerpo.setObjectName("ScrollBody")
        lay = QVBoxLayout(cuerpo)
        lay.setContentsMargins(24, 20, 24, 8)
        lay.setSpacing(12)
        exterior.addWidget(MVCD_AreaDesplazable(cuerpo), 1)

        fila_t = QHBoxLayout()
        t = QLabel(comp["nombre"])
        t.setObjectName("PageTitle")
        fila_t.addWidget(t)
        fila_t.addWidget(MVCD_ChipEstado(comp["estado"]))
        fila_t.addStretch()
        lay.addLayout(fila_t)
        if comp.get("modelo"):
            lay.addWidget(muted(comp["modelo"]))

        # Resultado y cálculo
        p1, v1 = panel("Respecto a fábrica")
        grande = QLabel(_pct_txt(comp))
        grande.setObjectName("BigNumber" if comp.get("pct") is not None else "SectionTitle")
        grande.setStyleSheet(f"color:{color_estado(comp['estado'])};")
        v1.addWidget(grande)
        if comp.get("calculo"):
            v1.addWidget(QLabel(f"Cómo se calculó: {comp['calculo']}"))
        else:
            v1.addWidget(muted("No se calculó un porcentaje: " + (comp.get("alt") or "falta la medición o la referencia.")))
        if comp.get("pct") is not None:
            g = QGridLayout()
            g.setHorizontalSpacing(10)
            g.addWidget(QLabel(f'Medido: {comp["medido"]["valor"]}'), 0, 0)
            g.addWidget(MVCD_BarraPorcentaje(comp["pct"], color=color_estado(comp["estado"])), 0, 1)
            g.addWidget(QLabel(f'De fábrica: {comp["fabrica"]["valor"]}'), 1, 0)
            g.addWidget(MVCD_BarraPorcentaje(100, color=T.lateral_texto), 1, 1)
            g.setColumnStretch(1, 1)
            v1.addLayout(g)
        v1.addWidget(muted(f'Fuente: {comp.get("fuente") or "—"}'))
        lay.addWidget(p1)

        # Datos leídos del sistema operativo (la clave "windows" es histórica: también Linux)
        if comp.get("windows"):
            p2, v2 = panel("Datos del sistema")
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(10)
            for i, (dato, valor) in enumerate(comp["windows"]):
                tarjeta = QFrame()
                tarjeta.setObjectName("Card")
                tv = QVBoxLayout(tarjeta)
                tv.setContentsMargins(12, 8, 12, 8)
                tv.addWidget(muted(dato))
                val = QLabel(str(valor))
                val.setWordWrap(True)
                no_disp = str(valor).startswith("No disponible")
                val.setStyleSheet(f"color:{T.texto_suave};" if no_disp else "font-weight:600;")
                tv.addWidget(val)
                grid.addWidget(tarjeta, i // 2, i % 2)
            v2.addLayout(grid)
            lay.addWidget(p2)

        # Evolución entre inspecciones
        p3, v3 = panel("Evolución entre inspecciones")
        puntos = []
        for h in historial:
            c = componente(h["resultado"], comp["clave"])
            if c is None:
                continue
            puntos.append((h, c))
            fila = QHBoxLayout()
            etiqueta = QLabel(f'{h["case_code"]} · {fecha_corta(h["captured_at"], con_hora=False)}')
            etiqueta.setMinimumWidth(170)
            fila.addWidget(etiqueta)
            if c.get("pct") is not None:
                fila.addWidget(MVCD_BarraPorcentaje(c["pct"], color=color_estado(c["estado"])), 1)
            else:
                fila.addWidget(muted(f'{c["medido"]["valor"]} · {c.get("alt") or c["estado"]}'), 1)
            v3.addLayout(fila)
        self.variacion = muted(self._variacion(puntos))
        v3.addWidget(self.variacion)
        lay.addWidget(p3)

        # Qué significa y qué hacer
        p4, v4 = panel("Qué significa")
        for quien, texto in (("Para el técnico", comp.get("tecnico")), ("Para el cliente", comp.get("cliente"))):
            if texto:
                l = QLabel(f"<b>{quien}:</b> {html.escape(texto)}")
                l.setTextFormat(Qt.RichText)
                l.setWordWrap(True)
                v4.addWidget(l)
        lay.addWidget(p4)

        p5, v5 = panel("Qué hacer")
        if comp.get("que_hacer"):
            q = QLabel(comp["que_hacer"])
            q.setWordWrap(True)
            v5.addWidget(q)
        botones = QHBoxLayout()
        self.b_incluir = QPushButton("Incluir en el diagnóstico")
        self.b_incluir.setObjectName("Primary")
        self.b_incluir.clicked.connect(lambda: self._incluir())
        self.b_nota = QPushButton("Agregar nota al caso")
        self.b_nota.setObjectName("Secondary")
        self.b_nota.clicked.connect(lambda: self._agregar_nota())
        for b in (self.b_incluir, self.b_nota):
            b.setEnabled(bool(code))
            if not code:
                b.setToolTip("Disponible cuando la captura pertenece a un caso")
            botones.addWidget(b)
        botones.addStretch()
        v5.addLayout(botones)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        v5.addWidget(self.msg)
        lay.addWidget(p5)
        lay.addStretch()

        cerrar = QPushButton("Cerrar")
        cerrar.setObjectName("Secondary")
        cerrar.clicked.connect(self.accept)
        fila_c = QHBoxLayout()
        fila_c.setContentsMargins(24, 0, 24, 0)
        fila_c.addStretch()
        fila_c.addWidget(cerrar)
        exterior.addLayout(fila_c)

    @staticmethod
    def _variacion(puntos) -> str:
        con = [(h, c) for h, c in puntos if c.get("pct") is not None]
        if len(con) >= 2:
            (h1, c1), (h2, c2) = con[0], con[-1]
            dif = c2["pct"] - c1["pct"]
            signo = "+" if dif > 0 else "−" if dif < 0 else "±"
            return (f'De {c1["pct"]:.0f} % ({h1["case_code"]}, {fecha_corta(h1["captured_at"], con_hora=False)}) '
                    f'a {c2["pct"]:.0f} % ({h2["case_code"]}, {fecha_corta(h2["captured_at"], con_hora=False)}): '
                    f'{signo}{abs(dif):.0f} puntos.')
        con_num = [(h, c) for h, c in puntos if c.get("medido_num") is not None]
        if len(con_num) >= 2:
            (h1, c1), (h2, c2) = con_num[0], con_num[-1]
            return (f'De {c1["medido"]["valor"]} ({h1["case_code"]}) a {c2["medido"]["valor"]} '
                    f'({h2["case_code"]}).')
        return "Aún no hay dos inspecciones con medición para comparar."

    def _texto(self) -> str:
        c = self.comp
        base = c.get("resumen") or f'{c["nombre"]}: {c["estado"].lower()} ({c["medido"]["valor"]}).'
        return f"Salud del equipo — {base}"

    def _set_msg(self, texto: str, ok: bool = True):
        self.msg.setStyleSheet(f"color:{T.exito};font-weight:600;" if ok else f"color:{T.peligro};")
        self.msg.setText(texto)

    def _incluir(self):
        try:
            nuevo = self.hr.include_in_diagnosis(self.code, self.comp["clave"], self._texto())
        except ValueError as e:
            self._set_msg(str(e), ok=False)
            return
        self._set_msg("Incluido: aparecerá en el diagnóstico del caso." if nuevo
                      else "Ya estaba incluido; se actualizó el texto.")

    def _agregar_nota(self, texto: str | None = None):
        if texto is None:
            texto, ok = QInputDialog.getMultiLineText(self, "Agregar nota al caso",
                                                      "Observación técnica (puede editarla):", self._texto())
            if not ok:
                return
        try:
            QAKM_NotesRepository(self.repo).add(self.code, "observacion", texto, self.tech_id)
        except ValueError as e:
            self._set_msg(str(e), ok=False)
            return
        self._set_msg("Nota agregada al caso como observación técnica.")


# ---------------- pantalla ----------------
class MVCD_SaludPage(QWidget):
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    """Si `embebida` es True (dentro del detalle del caso) no muestra el selector de casos."""
    changed = Signal()

    def __init__(self, repo: QAKM_Repository, embebida: bool = False):
        super().__init__()
        self.repo = repo
        self.hr = QAKM_HealthRepository(repo)
        self.embebida = embebida
        self.code: str | None = None
        self.scan: dict | None = None
        self.datos: dict | None = None
        self.resultado: dict | None = None
        self.historial: list[dict] = []
        # Se reemplazan en las pruebas (WMI real, escaneo real y cuadros de diálogo)
        self._ids_locales = local_identifiers
        self._escanear = self._escanear_con_progreso
        self._preguntar = lambda titulo, texto: QMessageBox.question(
            self, titulo, texto, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        self._informar = lambda titulo, texto: QMessageBox.information(self, titulo, texto)
        self._timer_caso = QTimer(self)
        self._timer_caso.setSingleShot(True)
        self._timer_caso.setInterval(300)
        self._timer_caso.timeout.connect(self._cargar_casos)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(12)
        cab = QHBoxLayout()
        textos, _t, self.subtitulo = cabecera("Salud del equipo", "Seleccione un caso para ver la salud del equipo.")
        cab.addLayout(textos, 1)
        self.b_inv = QPushButton("Ver inventario completo")
        self.b_inv.setObjectName("Secondary")
        self.b_inv.clicked.connect(lambda: self._ver_inventario())
        self.b_bench = QPushButton("Ejecutar prueba de rendimiento")
        self.b_bench.setObjectName("Primary")
        self.b_bench.clicked.connect(self._prueba)
        cab.addWidget(self.b_inv, alignment=Qt.AlignTop)
        cab.addWidget(self.b_bench, alignment=Qt.AlignTop)
        root.addLayout(cab)
        self.motivo_bench = muted("")
        self.motivo_bench.setAlignment(Qt.AlignRight)
        root.addWidget(self.motivo_bench)

        # Selector de caso (mismo patrón que Reportes)
        self.selector = QWidget()
        sl = QHBoxLayout(self.selector)
        sl.setContentsMargins(0, 0, 0, 0)
        self.buscar_caso = QLineEdit()
        self.buscar_caso.setPlaceholderText("Buscar el caso: cliente, documento, serie, código, equipo…")
        self.buscar_caso.setClearButtonEnabled(True)
        self.buscar_caso.textChanged.connect(lambda _t: self._timer_caso.start())
        self.combo = QComboBox()
        self.combo.activated.connect(lambda _i: self._elegir_combo())
        sl.addWidget(self.buscar_caso, 1)
        sl.addWidget(self.combo, 2)
        root.addWidget(self.selector)
        self.selector.setVisible(not embebida)

        cuerpo = QWidget()
        cuerpo.setObjectName("ScrollBody")
        self.cuerpo = QVBoxLayout(cuerpo)
        self.cuerpo.setContentsMargins(0, 0, 0, 0)
        self.cuerpo.setSpacing(12)
        root.addWidget(MVCD_AreaDesplazable(cuerpo), 1)

        # Resumen
        self.p_resumen, vr = panel()
        fila = QHBoxLayout()
        fila.setSpacing(24)
        izq = QVBoxLayout()
        izq.setSpacing(4)
        izq.addWidget(muted("Rendimiento respecto a fábrica"))
        num = QHBoxLayout()
        self.indice_lbl = QLabel("—")
        self.indice_lbl.setObjectName("BigNumber")
        self.indice_chip = MVCD_ChipEstado(SIN_REF)
        num.addWidget(self.indice_lbl)
        num.addWidget(self.indice_chip, alignment=Qt.AlignVCenter)
        num.addStretch()
        izq.addLayout(num)
        izq.addWidget(muted("índice orientativo"))
        self.indice_barra = MVCD_BarraPorcentaje(None, texto_alt="Sin componentes con referencia")
        izq.addWidget(self.indice_barra)
        marca = muted("Fábrica = 100 %")
        marca.setAlignment(Qt.AlignRight)
        izq.addWidget(marca)
        fila.addLayout(izq, 3)
        self.contadores: dict[str, QLabel] = {}
        cont = QGridLayout()
        cont.setHorizontalSpacing(10)
        cont.setVerticalSpacing(10)
        for i, (estado, texto) in enumerate(((BUENO, "en buen estado"), (REVISAR, "por revisar"),
                                              (ATENCION, "requieren atención"), (SIN_REF, "sin referencia"))):
            caja = QFrame()
            caja.setObjectName("Card")
            cv = QVBoxLayout(caja)
            cv.setContentsMargins(12, 8, 12, 8)
            n = QLabel("0")
            n.setStyleSheet(f"font-size:22px; font-weight:600; color:{color_estado(estado)};")
            cv.addWidget(n)
            cv.addWidget(muted(texto))
            self.contadores[estado] = n
            cont.addWidget(caja, i // 2, i % 2)
        fila.addLayout(cont, 2)
        vr.addLayout(fila)
        self.incluidos_lbl = muted("")
        vr.addWidget(self.incluidos_lbl)
        self.cuerpo.addWidget(self.p_resumen)

        # Lo más importante
        self.alerta = QFrame()
        self.alerta.setObjectName("Alert")
        al = QHBoxLayout(self.alerta)
        al.setContentsMargins(14, 10, 14, 10)
        icono = QLabel("⚠")
        icono.setStyleSheet(f"color:{T.aviso}; font-size:18px; font-weight:600;")
        self.alerta_txt = QLabel("")
        self.alerta_txt.setTextFormat(Qt.RichText)
        self.alerta_txt.setWordWrap(True)
        self.b_alerta = QPushButton("Ver detalle")
        self.b_alerta.setObjectName("Link")
        self.b_alerta.setCursor(Qt.PointingHandCursor)
        self.b_alerta.clicked.connect(lambda: self._detalle_hallazgo())
        al.addWidget(icono, alignment=Qt.AlignTop)
        al.addWidget(self.alerta_txt, 1)
        al.addWidget(self.b_alerta)
        self.cuerpo.addWidget(self.alerta)
        self.sin_hallazgos = muted("")
        self.cuerpo.addWidget(self.sin_hallazgos)

        # Tabla de componentes
        self.p_tabla, vt = panel("Componentes")
        self.tabla = QTableWidget(0, len(COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(COLUMNAS)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setSelectionMode(QAbstractItemView.NoSelection)
        self.tabla.setShowGrid(False)
        self.tabla.setFocusPolicy(Qt.NoFocus)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(64)
        self.tabla.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tabla.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tabla.setWordWrap(False)
        h = self.tabla.horizontalHeader()
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for col, ancho in ANCHOS.items():
            h.setSectionResizeMode(col, QHeaderView.Fixed)
            self.tabla.setColumnWidth(col, ancho)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.Stretch)
        vt.addWidget(self.tabla)
        self.cuerpo.addWidget(self.p_tabla)

        self.aviso = QLabel("")
        self.aviso.setWordWrap(True)
        self.cuerpo.addWidget(self.aviso)
        nota = muted(NOTA_FINAL)
        self.cuerpo.addWidget(nota)
        self.cuerpo.addStretch()

        self._pintar()

    # ---------- entrada ----------
    def refresh(self):
        if not self.embebida:
            self._cargar_casos()
        if self.code:
            self._evaluar()
        elif self.scan is None and not self.embebida and self.combo.count():
            self._elegir_combo()

    def show_case(self, code: str):
        self.code, self.scan = code, None
        if not self.embebida:
            i = self.combo.findData(code)
            if i < 0:
                caso = self.repo.get_case(code)
                if caso is not None:
                    self.combo.insertItem(0, f'{code} · {caso["equipo"]} · {caso["cliente"] or "Sin cliente"}', code)
                    i = 0
            self.combo.setCurrentIndex(i)
        self._evaluar()

    def show_scan(self, scan: dict):
        """Captura todavía sin caso (desde Escanear): se evalúa sin guardar."""
        self.code, self.scan = None, scan
        self.datos = None
        self.resultado = evaluate(scan, load_references())
        self.historial = []
        self._pintar()

    def _cargar_casos(self):
        self._timer_caso.stop()
        try:
            res = QAKM_SearchQueries(self.repo.c).search_cases(text=self.buscar_caso.text().strip(), limit=MAX_CASOS_COMBO)
        except Exception:
            return
        actual = self.code or self.combo.currentData()
        self.combo.blockSignals(True)
        self.combo.clear()
        for r in res["rows"]:
            self.combo.addItem(f'{r["code"]} · {r["equipo"]} · {r["cliente"] or "Sin cliente"}', r["code"])
        if actual:
            i = self.combo.findData(actual)
            if i >= 0:
                self.combo.setCurrentIndex(i)
        self.combo.blockSignals(False)

    def _elegir_combo(self):
        code = self.combo.currentData()
        if code:
            self.show_case(code)

    def _evaluar(self):
        refs = load_references()
        self.datos = self.hr.evaluate_case(self.code, refs)
        self.resultado = self.datos["resultado"]
        cap = self.datos["captura"]
        self.historial = []
        if cap is not None:
            self.historial = self.hr.history_for_equipment(cap["equipment_id"], refs)
        self._pintar()
        self.changed.emit()

    # ---------- pintar ----------
    def _subtitulo(self) -> str:
        if self.code:
            caso = self.repo.get_case(self.code)
            cap = (self.datos or {}).get("captura")
            partes = [self.code, caso["equipo"], f'Serie {caso["serial"]}', caso["cliente"] or "Sin cliente"]
            partes.append(f'captura del {fecha_corta(cap["captured_at"])}' if cap else "sin captura de hardware")
            return " · ".join(partes)
        if self.scan is not None:
            ident = ((self.scan.get("inventory") or {}).get("identity") or {}) if isinstance(self.scan, dict) else {}
            equipo = " ".join(p for p in (ident.get("manufacturer"), ident.get("model")) if p) or "Equipo escaneado"
            return (f'{equipo} · captura del {fecha_corta(self.scan.get("scanned_at", ""))} · '
                    "todavía sin caso: el resultado no se guarda")
        return "Seleccione un caso para ver la salud del equipo."

    def _tiene_inventario(self) -> bool:
        cap = (self.datos or {}).get("captura")
        scan = cap["payload"] if cap else self.scan
        return isinstance(scan, dict) and isinstance(scan.get("inventory"), dict)

    def _estado_botones(self):
        """Con un caso seleccionado ambos botones funcionan: si falta la captura, ofrecen
        escanear este equipo (si es el del caso) o explican cómo obtenerla."""
        tiene_inv = self._tiene_inventario()
        self.b_inv.setEnabled(bool(self.code) or tiene_inv)
        self.b_bench.setEnabled(bool(self.code))
        motivo = ""
        if not self.code:
            motivo = ("La prueba de rendimiento requiere un caso: elija uno arriba."
                      if self.scan is None else
                      "Registre la recepción con esta captura para poder ejecutar la prueba de rendimiento.")
        elif not tiene_inv:
            motivo = ("El caso no tiene captura de hardware con inventario: al pulsar un botón se ofrecerá "
                      "escanear este equipo si es el del caso.")
        self.b_bench.setToolTip("Mide el procesador (unos 60 s) y los discos (unos 30 s cada uno) en ESTE equipo")
        self.b_inv.setToolTip("" if tiene_inv else "Si el caso no tiene captura, se ofrece escanear este equipo")
        self.motivo_bench.setStyleSheet("")
        self.motivo_bench.setText(motivo)
        self.motivo_bench.setVisible(bool(motivo))

    def _pintar(self):
        self.subtitulo.setText(self._subtitulo())
        self._estado_botones()
        r = self.resultado
        comps = (r or {}).get("componentes", [])
        hay = bool(comps)
        for w in (self.p_resumen, self.p_tabla):
            w.setVisible(hay)
        self.aviso.setText((r or {}).get("aviso", "") if r else "")
        self.aviso.setVisible(bool(r and r.get("aviso")))
        if not hay:
            self.alerta.hide()
            self.sin_hallazgos.hide()
            vaciar_tabla(self.tabla)
            return
        ind = r["indice"]
        valor = ind["valor"]
        self.indice_lbl.setText(f"{valor:.0f} %" if valor is not None else "—")
        self.indice_lbl.setStyleSheet(f"color:{color_estado(ind['estado'])};")
        self.indice_chip.set_estado(ind["estado"])
        self.indice_barra.set_valor(valor, color_estado(ind["estado"]))
        for estado, lbl in self.contadores.items():
            lbl.setText(str(r["conteo"].get(estado, 0)))
        if ind["incluidos"]:
            self.incluidos_lbl.setText(
                "El índice es el promedio simple de: " + ", ".join(ind["incluidos"]) +
                ". No incluye los componentes sin referencia ni la refrigeración, que se mide como margen en °C.")
        else:
            self.incluidos_lbl.setText("Ningún componente tiene a la vez medición y referencia de fábrica: "
                                       "no se calcula el índice.")
        hall = r.get("hallazgo")
        if hall:
            self.alerta_txt.setText(f"<b>Lo más importante:</b> {html.escape(hall['texto'])}")
            self.alerta.show()
            self.sin_hallazgos.hide()
        else:
            self.alerta.hide()
            self.sin_hallazgos.setText("No se encontraron componentes que requieran atención con los datos disponibles.")
            self.sin_hallazgos.show()
        self._pintar_tabla(comps)

    def _pintar_tabla(self, comps):
        vaciar_tabla(self.tabla)
        self.tabla.setRowCount(len(comps))
        for i, c in enumerate(comps):
            celdas = [
                (celda(f"<b>{html.escape(c['nombre'])}</b>", c.get("modelo", ""), rico=True, wrap=True),
                 (c["nombre"], c.get("modelo", ""))),
                (None, (c["estado"] + "  ",)),
                (celda(html.escape(c["medido"]["valor"]), c["medido"]["nota"], rico=True, wrap=True),
                 (c["medido"]["valor"], c["medido"]["nota"])),
                (celda(html.escape(c["fabrica"]["valor"]), c["fabrica"]["nota"], rico=True, wrap=True),
                 (c["fabrica"]["valor"], c["fabrica"]["nota"])),
            ]
            for j, (widget, medidas) in enumerate(celdas):
                self.tabla.setItem(i, j, item_medida(*medidas) if j == 1 else QTableWidgetItem(""))
                if widget is not None:
                    self.tabla.setCellWidget(i, j, widget)
            chip = QWidget()
            hc = QHBoxLayout(chip)
            hc.setContentsMargins(8, 0, 8, 0)
            hc.addWidget(MVCD_ChipEstado(c["estado"]))
            hc.addStretch()
            self.tabla.setCellWidget(i, 1, chip)
            respecto = QWidget()
            hr = QHBoxLayout(respecto)
            hr.setContentsMargins(8, 0, 8, 0)
            if c.get("pct") is not None:
                hr.addWidget(MVCD_BarraPorcentaje(c["pct"], color=color_estado(c["estado"])))
            else:
                alt = muted(c.get("alt") or "Sin referencia")
                alt.setToolTip(c.get("alt") or "")
                hr.addWidget(alt)
            self.tabla.setItem(i, 4, QTableWidgetItem(""))
            self.tabla.setCellWidget(i, 4, respecto)
            completa = c.get("fuente") or "—"
            fuente = QTableWidgetItem(completa.split(" · ")[0])  # el resto, en el tooltip y en el detalle
            fuente.setToolTip(completa)
            fuente.setForeground(QColor(T.texto_suave))
            self.tabla.setItem(i, 5, fuente)
            ver = QPushButton("Ver detalle")
            ver.setObjectName("Link")
            ver.setCursor(Qt.PointingHandCursor)
            ver.clicked.connect(lambda _=False, k=c["clave"]: self.abrir_detalle(k))
            caja = QWidget()
            hv = QHBoxLayout(caja)
            hv.setContentsMargins(8, 0, 8, 0)
            hv.addWidget(ver)
            self.tabla.setItem(i, 6, QTableWidgetItem(""))
            self.tabla.setCellWidget(i, 6, caja)
        ajustar_alto_tabla(self.tabla)

    # ---------- acciones ----------
    def abrir_detalle(self, clave: str, ejecutar: bool = True):
        comp = componente(self.resultado, clave)
        if comp is None:
            return None
        dlg = MVCD_DetalleComponenteDialog(self.repo, self.code, comp, self.historial, self)
        if ejecutar:
            dlg.exec()
        return dlg

    def _detalle_hallazgo(self):
        hall = (self.resultado or {}).get("hallazgo")
        if hall:
            self.abrir_detalle(hall["clave"])

    def _ver_inventario(self, ejecutar: bool = True):
        if not self._tiene_inventario() and not self.asegurar_captura("Ver inventario completo"):
            return None
        cap = (self.datos or {}).get("captura")
        scan = cap["payload"] if cap else self.scan
        dlg = MVCD_InventoryDialog(scan, self)
        if ejecutar:
            dlg.exec()
        return dlg

    # ---------- captura del caso ----------
    def caso_es_este_equipo(self) -> tuple[bool | None, str]:
        """¿El equipo del caso es esta computadora? Compara los identificadores de este equipo
        (UUID, serie, serie de la placa, MAC) con los registrados para el equipo del caso."""
        equipo = self.repo.equipment_id_of_case(self.code)
        if equipo is None:
            return None, "No existe el caso."
        try:
            locales = self._ids_locales()
        except Exception as e:
            return None, f"No se pudo identificar este equipo: {e}"
        if not locales:
            return None, "El sistema no informó el UUID ni el número de serie de este equipo."
        res = QAKM_HardwareRepository(self.repo).identify(locales, fuertes=FUERTES_LOCAL)
        if res["status"] == "encontrado" and res["equipment_id"] == equipo:
            return True, ""
        return False, ""

    def asegurar_captura(self, accion: str) -> bool:
        """Si el caso no tiene captura con inventario, ofrece escanear ESTE equipo (solo si es el
        del caso), la guarda en el caso y vuelve a evaluar. Devuelve True si ya hay captura."""
        if self._tiene_inventario():
            return True
        if not self.code:
            return False
        caso = self.repo.get_case(self.code)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            es_este, motivo = self.caso_es_este_equipo()
        finally:
            QApplication.restoreOverrideCursor()
        if not es_este:
            texto = (f'El caso {self.code} ({caso["equipo"]}, serie {caso["serial"]}) no tiene captura de '
                     "hardware con inventario")
            if es_este is None:
                texto += f". {motivo}"
            else:
                texto += (" y este equipo no es el del caso.\n\nPara obtenerla, abra el programa en el equipo "
                          "del cliente y use Escanear equipo, o importe su archivo .diag desde Escanear → "
                          "Importar desde USB y regístrelo en la recepción.")
            self._informar(accion, texto)
            return False
        if not self._preguntar(accion, f'El caso {self.code} no tiene captura de hardware con inventario y '
                                       "corresponde a este equipo.\n\n¿Escanear este equipo ahora y guardar la "
                                       "captura en el caso? Tarda unos segundos."):
            return False
        try:
            data = self._escanear()
        except Exception as e:
            self._informar(accion, f"El escaneo falló: {e}")
            return False
        if not data:
            return False
        data.setdefault("provenance", {"how": "local_scan", "file": None})
        try:
            res = QAKM_HardwareRepository(self.repo).save_capture(self.code, data)
        except Exception as e:
            self._informar(accion, f"No se pudo guardar la captura: {e}")
            return False
        if res["conflicts"]:
            self._informar(accion, f'Captura guardada. Aviso: {len(res["conflicts"])} identificador(es) ya '
                                   "pertenecen a otro equipo y no se reasignaron.")
        self._evaluar()
        return self._tiene_inventario()

    def _escanear_con_progreso(self) -> dict | None:
        """Escaneo real de este equipo en un hilo, con barra de progreso (no bloquea la interfaz)."""
        from app.ui.pages.escaneo import MVCD_ScanWorker
        dlg = QProgressDialog("Escaneando este equipo…", None, 0, len(COMPONENT_NAMES), self)
        dlg.setWindowTitle("Escanear este equipo")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setValue(0)
        resultado, error = {}, {}
        w = MVCD_ScanWorker()
        w.step.connect(lambda i, n, _d, _s: (dlg.setValue(i + 1), dlg.setLabelText(f"Leyendo: {n}…")))
        w.finished_scan.connect(lambda d: resultado.update(d))
        w.failed.connect(lambda m: error.update(m=m))
        bucle = QEventLoop()
        w.finished.connect(bucle.quit)
        w.start()
        bucle.exec()
        dlg.close()
        if error:
            raise RuntimeError(error["m"])
        return resultado or None

    def comprobar_equipo(self) -> tuple[bool, str]:
        """La prueba mide ESTA computadora: solo se permite si la captura del caso es de ella."""
        cap = (self.datos or {}).get("captura")
        if not cap:
            return False, "El caso no tiene captura de hardware."
        try:
            locales = self._ids_locales()
        except Exception as e:
            return False, f"No se pudo identificar este equipo: {e}"
        igual = misma_maquina(cap["payload"], locales)
        if igual is None:
            return False, ("La captura no tiene UUID ni número de serie: no se puede confirmar que sea "
                           "este equipo.")
        if not igual:
            return False, ("La captura es de otro equipo. Ejecute el programa en el equipo del cliente "
                           "para medir su rendimiento.")
        return True, ""

    def _prueba(self):
        from app.ui.benchmark_dialog import MVCD_BenchmarkDialog
        if not self.asegurar_captura("Ejecutar prueba de rendimiento"):
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok, motivo = self.comprobar_equipo()
        finally:
            QApplication.restoreOverrideCursor()
        if not ok:
            self.motivo_bench.setText(motivo)
            self.motivo_bench.setStyleSheet(f"color:{T.peligro};")
            self.motivo_bench.show()
            return
        dlg = MVCD_BenchmarkDialog(self.repo, self.code, self.datos["captura"], self)
        dlg.exec()
        if dlg.saved:
            self._evaluar()


class MVCD_SaludDialog(QDialog):
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    """La misma pantalla dentro de un diálogo (desde el detalle del caso)."""

    def __init__(self, repo: QAKM_Repository, code: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Salud del equipo — {code}")
        self.resize(1120, 820)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 12)
        self.page = MVCD_SaludPage(repo, embebida=True)
        self.page.show_case(code)
        lay.addWidget(self.page, 1)
        cerrar = QPushButton("Cerrar")
        cerrar.setObjectName("Secondary")
        cerrar.clicked.connect(self.accept)
        fila = QHBoxLayout()
        fila.setContentsMargins(26, 0, 26, 0)
        fila.addStretch()
        fila.addWidget(cerrar)
        lay.addLayout(fila)
