import html

from PySide6.QtCore import QDate, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QCheckBox, QDateEdit,
                               QLabel, QLineEdit, QComboBox, QPushButton, QFrame)
from app.db.clients_repo import ClientsRepository, normalize_doc
from app.db.hardware_repo import HardwareRepository
from app.db.health_repo import HealthRepository
from app.db.orders_repo import ACCESORIOS, OrdersRepository
from app.db.reports_repo import ReportsRepository
from app.db.repo import Repository, PRIORIDADES
from app.hardware.inventory import fmt_bytes
from app.reports.service import generate_report
from app.ui.widgets import AreaDesplazable, cabecera, campo, fecha_corta, limpiar_layout, lista_dato_valor, muted, panel

TIPOS_ID = {"uuid": "UUID", "serial": "número de serie", "board_serial": "serie de la placa", "mac": "MAC"}
NO_DISP = "No disponible"


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v) -> list:
    return v if isinstance(v, list) else []


def _coincide_por(tipos) -> str:
    nombres = [TIPOS_ID.get(t, t) for t in tipos]
    if not nombres:
        return ""
    return nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1]


def datos_equipo(scan: dict) -> list[tuple[str, str]]:
    """Resumen dato–valor de una captura. Solo datos leídos; lo demás, 'No disponible'."""
    inv, res = _d(scan.get("inventory")), _d(scan.get("summary"))
    cpu = _d(inv.get("cpu")).get("name") or res.get("cpu") or NO_DISP

    mem = _d(inv.get("memory"))
    if mem.get("total_gb"):
        modulos = [m for m in _l(mem.get("modules")) if isinstance(m, dict)]
        memoria = f'{mem["total_gb"]:g} GB'
        if modulos:
            tipos = sorted({m["type"] for m in modulos if m.get("type")})
            vel = sorted({m["speed_mhz"] for m in modulos if m.get("speed_mhz")})
            extra = " ".join(p for p in (" / ".join(tipos), " / ".join(f"{v} MHz" for v in vel)) if p)
            memoria += f" · {len(modulos)} módulo(s)" + (f" {extra}" if extra else "")
    else:
        memoria = res.get("ram") or NO_DISP

    discos = []
    for u in _l(_d(inv.get("storage")).get("physical")):
        if isinstance(u, dict) and u.get("size_bytes"):
            salud = f' ({u["health"]})' if u.get("health") else ""
            discos.append(f'{u.get("media") or "Disco"} {fmt_bytes(u["size_bytes"])}{salud}')
    discos_txt = ", ".join(discos) or res.get("storage") or NO_DISP

    so = _d(inv.get("os"))
    sistema = (" · compilación ".join(p for p in (so.get("name"), so.get("build")) if p)
               or res.get("os") or NO_DISP)

    prov = _d(scan.get("provenance"))
    if prov.get("how") == "imported_file":
        origen = f'Archivo importado ({prov.get("file") or "sin nombre"})'
    elif prov.get("how") == "local_scan":
        origen = "Escaneo de este equipo"
    else:
        origen = "No indicado"
    return [("Procesador", cpu), ("Memoria", memoria), ("Discos", discos_txt),
            ("Sistema", sistema), ("Origen", origen)]


class RecepcionPage(QWidget):
    case_created = Signal(str)
    open_case = Signal(str)
    go_scan = Signal()

    CHIPS = ["Lento", "Se apaga", "No enciende", "Se calienta", "Disco lleno", "Pantalla azul"]

    def __init__(self, repo: Repository, tech_id: str = ""):
        super().__init__()
        self.repo = repo
        self.tech_id = tech_id
        self.orders = OrdersRepository(repo)
        self.hwr = HardwareRepository(repo)
        self.clients = ClientsRepository(repo)
        self.health = HealthRepository(repo)
        self._prev_code = None
        self.hw: dict | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(12)
        textos, _t, _s = cabecera("Recepción de equipo",
                                  "Registro rápido en una sola pantalla. Los campos marcados con * son obligatorios.")
        outer.addLayout(textos)

        cuerpo_w = QWidget()
        cuerpo_w.setObjectName("ScrollBody")
        root = QVBoxLayout(cuerpo_w)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        scroll = AreaDesplazable(cuerpo_w)
        outer.addWidget(scroll, 1)

        # Aviso de reingreso
        self.alert = QFrame()
        self.alert.setObjectName("Alert")
        al = QHBoxLayout(self.alert)
        al.setContentsMargins(14, 10, 14, 10)
        icono = QLabel("⚠")
        icono.setStyleSheet("color:#b7791f; font-size:18px; font-weight:600;")
        self.alert_text = QLabel()
        self.alert_text.setWordWrap(True)
        self.alert_text.setTextFormat(Qt.RichText)
        btn_prev = QPushButton("Ver caso anterior")
        btn_prev.setObjectName("Secondary")
        btn_prev.clicked.connect(self._ver_anterior)
        al.addWidget(icono, alignment=Qt.AlignTop)
        al.addWidget(self.alert_text, 1)
        al.addWidget(btn_prev, alignment=Qt.AlignVCenter)
        self.alert.hide()
        root.addWidget(self.alert)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(16)

        # --- Panel del formulario ---
        form, fv = panel("Cliente y equipo")
        self.cliente = QLineEdit()
        self.cliente.setPlaceholderText("Nombre y apellido")
        self.telefono = QLineEdit()
        self.telefono.setPlaceholderText("Ej.: 987 654 321")
        self.documento = QLineEdit()
        self.documento.setPlaceholderText("DNI, RUC o CE")
        self.documento.setMaxLength(24)
        self.documento.textChanged.connect(self._on_documento)
        self.equipo = QLineEdit()
        self.equipo.setPlaceholderText("Ej.: Laptop HP 15")
        self.serie = QLineEdit()
        self.serie.setPlaceholderText("Ej.: SN-48213")
        self.serie.textChanged.connect(self._on_serie)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.addWidget(self._campo("Cliente *", self.cliente), 0, 0)
        grid.addWidget(self._campo("Teléfono", self.telefono), 0, 1)
        grid.addWidget(self._campo("Documento del cliente (opcional)", self.documento), 0, 2)
        grid.addWidget(self._campo("Equipo *", self.equipo), 1, 0, 1, 2)
        grid.addWidget(self._campo("N.º de serie *", self.serie), 1, 2)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        fv.addLayout(grid)

        fv.addSpacing(4)
        h2 = QLabel("Problema reportado *")
        h2.setObjectName("SectionTitle")
        fv.addWidget(h2)
        fv.addWidget(muted("Marque los síntomas que describe el cliente y agregue el detalle."))
        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.chips = []
        for texto in self.CHIPS:
            b = QPushButton(texto)
            b.setObjectName("ChipBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.chips.append(b)
            chips.addWidget(b)
        chips.addStretch()
        fv.addLayout(chips)
        self.problema = QLineEdit()
        self.problema.setPlaceholderText("Describa el problema en una línea")
        fv.addWidget(self.problema)

        self.prioridad = QComboBox()
        self.prioridad.addItems(PRIORIDADES)
        self.prioridad.setCurrentText("Media")
        self.prioridad.setMinimumWidth(160)
        fila_p = QHBoxLayout()
        fila_p.addWidget(self._campo("Prioridad", self.prioridad))
        fila_p.addStretch()
        fv.addLayout(fila_p)

        # --- Orden de servicio: lo que se recibe junto con el equipo ---
        fv.addSpacing(4)
        h3 = QLabel("Ingreso del equipo")
        h3.setObjectName("SectionTitle")
        fv.addWidget(h3)
        fv.addWidget(muted("Marque los accesorios que deja el cliente. Estos datos salen en la orden de servicio."))
        rejilla_acc = QGridLayout()  # en rejilla para no ensanchar el formulario
        rejilla_acc.setSpacing(8)
        self.accesorios = []
        for i, texto in enumerate(ACCESORIOS):
            b = QPushButton(texto)
            b.setObjectName("ChipBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.accesorios.append(b)
            rejilla_acc.addWidget(b, i // 3, i % 3)
        fv.addLayout(rejilla_acc)
        self.otros_acc = QLineEdit()
        self.otros_acc.setPlaceholderText("Otros accesorios (opcional)")
        self.estado_fisico = QLineEdit()
        self.estado_fisico.setPlaceholderText("Ej.: rayones en la tapa, falta una tecla")
        self.observaciones = QLineEdit()
        self.observaciones.setPlaceholderText("Ej.: el cliente pide conservar sus archivos")
        self.chk_fecha = QCheckBox("Fecha estimada de entrega")
        self.fecha = QDateEdit()
        self.fecha.setCalendarPopup(True)
        self.fecha.setDisplayFormat("dd/MM/yyyy")
        self.fecha.setEnabled(False)
        self.chk_fecha.toggled.connect(self.fecha.setEnabled)
        g2 = QGridLayout()
        g2.setHorizontalSpacing(12)
        g2.setVerticalSpacing(10)
        g2.addWidget(self._campo("Otros accesorios", self.otros_acc), 0, 0)
        g2.addWidget(self._campo("Estado físico", self.estado_fisico), 0, 1, 1, 2)
        g2.addWidget(self._campo("Observaciones", self.observaciones), 1, 0, 1, 2)
        caja_f = QWidget()
        cf = QVBoxLayout(caja_f)
        cf.setContentsMargins(0, 0, 0, 0)
        cf.setSpacing(4)
        cf.addWidget(self.chk_fecha)
        cf.addWidget(self.fecha)
        g2.addWidget(caja_f, 1, 2)
        for c in range(3):
            g2.setColumnStretch(c, 1)
        fv.addLayout(g2)
        self.chk_orden = QCheckBox("Abrir la orden de servicio para imprimir al guardar")
        self.chk_orden.setChecked(self.repo.get_setting("print_order", "1") == "1")
        self.chk_orden.toggled.connect(lambda v: self.repo.set_setting("print_order", "1" if v else "0"))
        fv.addWidget(self.chk_orden)

        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        self.ok = QLabel("")
        self.ok.setObjectName("Ok")
        self.ok.setWordWrap(True)
        fv.addWidget(self.error)
        fv.addWidget(self.ok)

        botones = QHBoxLayout()
        guardar = QPushButton("Guardar recepción")
        guardar.setObjectName("Primary")
        guardar.clicked.connect(self._guardar)
        limpiar = QPushButton("Limpiar")
        limpiar.setObjectName("Secondary")
        limpiar.clicked.connect(self._limpiar)
        botones.addWidget(guardar)
        botones.addWidget(limpiar)
        botones.addStretch()
        fv.addLayout(botones)
        fv.addStretch()

        # --- Panel de datos del equipo (escaneo) ---
        lado, lv = panel("Datos del equipo")
        self.ident_lbl = QLabel("")
        self.ident_lbl.setTextFormat(Qt.RichText)
        self.ident_lbl.setWordWrap(True)
        lv.addWidget(self.ident_lbl)
        self.hw_box = QVBoxLayout()
        self.hw_box.setSpacing(8)
        lv.addLayout(self.hw_box)
        scan = QPushButton("Escanear o importar datos")
        scan.setObjectName("Secondary")
        scan.clicked.connect(self.go_scan.emit)
        lv.addWidget(scan)
        lv.addStretch()

        cuerpo.addWidget(form, 3)
        cuerpo.addWidget(lado, 2)
        root.addLayout(cuerpo)
        root.addStretch()
        self.fecha.setDate(QDate.currentDate().addDays(3))
        self._render_hw()

    @staticmethod
    def _campo(etiqueta: str, widget: QWidget) -> QWidget:
        return campo(etiqueta, widget)

    # ---------- Datos de hardware e identificación ----------
    def set_hardware(self, data: dict):
        """Recibe un escaneo (local o importado desde USB) y lo relaciona con los equipos registrados."""
        self.hw = data
        self._identificar(data)
        self._render_hw()

    def _identificar(self, data: dict):
        resumen = data.get("summary", {}) if isinstance(data.get("summary"), dict) else {}
        try:
            res = self.hwr.identify_scan(data)
        except Exception as e:  # la identificación nunca debe impedir registrar el equipo
            self.ident_lbl.setText(f"<span style='color:#b7791f'>No se pudo comprobar si el equipo ya "
                                   f"estaba registrado: {html.escape(str(e))}</span>")
            return
        estado, cand = res["status"], res["candidates"]
        escrita = self.serie.text().strip()
        if estado == "encontrado":
            c = cand[0]
            por = _coincide_por(c.get("matched", []))
            texto = (f"<b style='color:#2f855a'>✓ Equipo ya registrado:</b> {html.escape(c['description'])} "
                     f"(serie {html.escape(c['serial'])})."
                     + (f" Coincide por {html.escape(por)}." if por else ""))
            if not escrita:
                self.serie.setText(c["serial"])  # activa el aviso de reingreso
            elif escrita.upper() != c["serial"].upper():
                texto += (f"<br><span style='color:#c0392b'>Usted escribió la serie {html.escape(escrita)}, "
                          "pero el escaneo corresponde al equipo anterior. Verifique antes de guardar.</span>")
        elif estado == "ambiguo":
            lista = ", ".join(f"{html.escape(c['description'])} ({html.escape(c['serial'])})" for c in cand)
            texto = ("<b style='color:#c0392b'>✕ El escaneo coincide con varios equipos registrados:</b> "
                     f"{lista}. Escriba la serie correcta para continuar.")
        elif estado == "probable":
            lista = ", ".join(f"{html.escape(c['description'])} ({html.escape(c['serial'])})" for c in cand)
            texto = ("<b style='color:#b7791f'>⚠ Posible equipo conocido:</b> coincide solo por un identificador "
                     f"débil (MAC) con {lista}. Confirme escribiendo la serie.")
        else:
            texto = "<b>Equipo nuevo:</b> no coincide con ningún equipo registrado."
            if resumen.get("serial") and not escrita:
                self.serie.setText(resumen["serial"])
        if estado != "encontrado" and resumen.get("description") and not self.equipo.text().strip():
            self.equipo.setText(resumen["description"])
        self.ident_lbl.setText(texto)

    def _render_hw(self):
        limpiar_layout(self.hw_box)
        if not self.hw:
            self.hw_box.addWidget(muted("Sin datos de hardware. Use el escaneo o importe un archivo .diag "
                                        "para completarlos automáticamente."))
            return
        self.hw_box.addWidget(lista_dato_valor(datos_equipo(self.hw)))
        fecha = fecha_corta(self.hw.get("scanned_at", "")) or "fecha desconocida"
        self.hw_box.addWidget(muted(f"Escaneado el {fecha}"))

    # ---------- Documento del cliente ----------
    def _on_documento(self, texto: str):
        """Si el documento ya está registrado, completa el nombre y el teléfono vacíos."""
        if len(texto.strip()) < 6:
            return
        cli = self.clients.find_by_doc(texto)
        if cli is None:
            return
        if not self.cliente.text().strip():
            self.cliente.setText(cli["name"])
        if not self.telefono.text().strip():
            self.telefono.setText(cli["phone"] or "")

    # ---------- Reingreso ----------
    def _on_serie(self, texto: str):
        texto = texto.strip()
        self._prev_code = None
        if len(texto) < 3:
            self.alert.hide()
            return
        previos = self.repo.previous_cases(texto)
        if not previos:
            self.alert.hide()
            return
        ultimo = previos[0]
        self._prev_code = ultimo["code"]
        veces = "1 vez" if len(previos) == 1 else f"{len(previos)} veces"
        texto = (
            f'<b>Reingreso detectado:</b> este equipo ({html.escape(ultimo["serial"])}) ya fue atendido '
            f'{veces}. Último caso: {html.escape(ultimo["code"])} del '
            f'{html.escape(fecha_corta(ultimo["created_at"], con_hora=False))} — '
            f'{html.escape(ultimo["problem"])} ({html.escape(ultimo["status"])}).'
        )
        for previo in previos:  # índice de salud de la visita más reciente que lo tenga
            indice = self.health.latest_index_for_case(previo["code"])
            if indice is not None:
                texto += (f'<br>Índice de salud en la visita {html.escape(previo["code"])}: '
                          f'<b>{indice:.0f} %</b> respecto a fábrica (orientativo).')
                break
        self.alert_text.setText(texto)
        self.alert.show()
        if not self.cliente.text().strip():
            self.cliente.setText(ultimo["cliente"] or "")
        if not self.telefono.text().strip():
            self.telefono.setText(ultimo["phone"] or "")
        if not self.equipo.text().strip():
            self.equipo.setText(ultimo["equipo"] or "")
        if not self.documento.text().strip():
            self.documento.setText(self.clients.doc_for_case(ultimo["code"]))

    def _ver_anterior(self):
        if self._prev_code:
            self.open_case.emit(self._prev_code)

    # ---------- Guardar ----------
    def _guardar(self):
        self.ok.setText("")
        cliente = self.cliente.text().strip()
        telefono = self.telefono.text().strip()
        equipo = self.equipo.text().strip()
        serie = self.serie.text().strip()
        partes = [c.text() for c in self.chips if c.isChecked()]
        escrito = self.problema.text().strip()
        if escrito:
            partes.append(escrito)
        problema = ", ".join(partes)
        if not (cliente and equipo and serie and problema):
            self.error.setText("Complete cliente, equipo, serie y problema.")
            return
        try:
            documento = normalize_doc(self.documento.text())
        except ValueError as e:
            self.error.setText(str(e))
            return
        acc = [b.text() for b in self.accesorios if b.isChecked()]
        if self.otros_acc.text().strip():
            acc.append(self.otros_acc.text().strip())
        estimada = self.fecha.date().toString("yyyy-MM-dd") if self.chk_fecha.isChecked() else ""
        if estimada and self.fecha.date() < QDate.currentDate():
            self.error.setText("La fecha estimada de entrega no puede ser anterior a hoy.")
            return
        self.error.setText("")
        code = self.repo.register_intake(
            cliente, telefono, serie, equipo, problema, self.prioridad.currentText(),
        )
        aviso = ""
        if documento:
            try:
                self.clients.set_doc_for_case(code, documento)
            except Exception as e:  # el caso ya quedó registrado; solo se avisa
                aviso += f" Aviso: no se pudo guardar el documento ({e})."
        if self.hw:  # guarda una captura nueva (las anteriores se conservan) y los datos actuales del equipo
            r = self.hw.get("summary", {})
            cid = self.repo.add_client(cliente, telefono)
            self.repo.upsert_equipment(
                serie, equipo, cid, cpu=r.get("cpu", ""), ram=r.get("ram", ""),
                storage=r.get("storage", ""), os_name=r.get("os", ""),
            )
            try:
                res = self.hwr.save_capture(code, self.hw)
                if res["conflicts"]:
                    aviso += (f" Aviso: {len(res['conflicts'])} identificador(es) del escaneo ya pertenecen a "
                             "otro equipo y no se reasignaron; revise que la serie sea la correcta.")
            except Exception as e:
                aviso += f" Aviso: no se pudo guardar la captura de hardware ({e})."
            else:
                try:  # deja guardado el índice de salud para Equipos, Caso y futuros reingresos
                    self.health.evaluate_case(code)
                except Exception as e:
                    aviso += f" Aviso: no se pudo evaluar la salud del equipo ({e})."
        orden_ok = True
        try:
            self.orders.save(code, acc, self.estado_fisico.text(), self.observaciones.text(), estimada,
                             self.tech_id)
        except Exception as e:
            orden_ok = False
            aviso += f" Aviso: no se pudo guardar la orden de servicio ({e})."
        if orden_ok and self.chk_orden.isChecked():
            try:
                ruta = generate_report(self.repo, ReportsRepository(self.repo), code, "orden", self.tech_id)
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(ruta)))
            except Exception as e:
                aviso += f" Aviso: no se pudo generar la orden de servicio ({e})."
        self._limpiar()
        self.ok.setText(f"Caso {code} registrado en la cola de trabajo.{aviso}")
        self.case_created.emit(code)

    def _limpiar(self):
        for campo_ in (self.cliente, self.telefono, self.documento, self.equipo, self.serie,
                       self.problema):
            campo_.clear()
        for c in self.chips + self.accesorios:
            c.setChecked(False)
        for campo_ in (self.otros_acc, self.estado_fisico, self.observaciones):
            campo_.clear()
        self.chk_fecha.setChecked(False)
        self.fecha.setDate(QDate.currentDate().addDays(3))
        self.prioridad.setCurrentText("Media")
        self.error.setText("")
        self.ok.setText("")
        self.ident_lbl.setText("")
        self.alert.hide()
        self.hw = None
        self._render_hw()
