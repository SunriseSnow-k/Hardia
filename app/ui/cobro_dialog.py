"""Presupuesto y cobro de un caso: líneas, descuento, aprobación del cliente, pagos y PDF."""
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.db.billing_repo import METODOS_PAGO, TIPOS_LINEA
from app.db.repo import Repository
from app.db.reports_repo import ReportsRepository
from app.db.users_repo import UsersRepository
from app.reports.service import generate_report
from app.servicios import cobro
from app.ui.tema import T
from app.ui.widgets import AreaDesplazable, ChipEstado, fecha_corta, muted, panel

COL_LINEAS = ["Descripción", "Tipo", "Cant.", "P. unitario", "Importe"]
COL_PAGOS = ["Fecha", "Forma de pago", "Importe", "Recibió", "Estado"]


def _tabla(columnas: list[str], estirar: int) -> QTableWidget:
    t = QTableWidget(0, len(columnas))
    t.setHorizontalHeaderLabels(columnas)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setShowGrid(False)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setSectionResizeMode(estirar, QHeaderView.Stretch)
    t.setMinimumHeight(130)
    return t


def _item(texto: str, dato=None, derecha: bool = False) -> QTableWidgetItem:
    it = QTableWidgetItem(texto)
    if dato is not None:
        it.setData(Qt.UserRole, dato)
    if derecha:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


class CobroDialog(QDialog):
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    def __init__(self, repo: Repository, code: str, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.code = code
        self.changed = False
        self.tech_id = getattr(repo, "session_tech", "") or ""
        self.s = cobro.simbolo(repo)
        self.es_admin = UsersRepository(repo).role(self.tech_id) == "admin"

        self.setWindowTitle(f"Presupuesto y cobro — {code}")
        self.setMinimumWidth(760)
        self.resize(900, 760)
        exterior = QVBoxLayout(self)
        exterior.setContentsMargins(0, 0, 0, 12)
        contenido = QWidget()
        contenido.setObjectName("ScrollBody")
        exterior.addWidget(AreaDesplazable(contenido), 1)
        lay = QVBoxLayout(contenido)
        lay.setContentsMargins(24, 20, 24, 8)
        lay.setSpacing(12)

        caso = repo.get_case(code)
        fila_t = QHBoxLayout()
        titulo = QLabel(f"Presupuesto y cobro — {code}")
        titulo.setObjectName("PageTitle")
        self.chip = ChipEstado("")
        fila_t.addWidget(titulo)
        fila_t.addWidget(self.chip)
        fila_t.addStretch()
        lay.addLayout(fila_t)
        lay.addWidget(muted(f'{caso["cliente"] or "Sin cliente"} · {caso["equipo"]} · Serie {caso["serial"]}'))

        # ---------- Presupuesto ----------
        p_q, vq = panel("Presupuesto")
        self.tabla = _tabla(COL_LINEAS, 0)
        vq.addWidget(self.tabla)
        fila_a = QHBoxLayout()
        self.tipo = QComboBox()
        for clave, texto in TIPOS_LINEA.items():
            self.tipo.addItem(texto, clave)
        self.descripcion = QLineEdit()
        self.descripcion.setPlaceholderText("Servicio o repuesto")
        self.descripcion.setMaxLength(cobro.MAX_DESCRIPCION)
        self.cantidad = QSpinBox()
        self.cantidad.setRange(1, cobro.MAX_CANTIDAD)
        self.precio = QLineEdit()
        self.precio.setPlaceholderText(f"Precio ({self.s})")
        self.precio.setMaximumWidth(120)
        self.b_agregar = QPushButton("Agregar")
        self.b_agregar.setObjectName("Primary")
        self.b_agregar.clicked.connect(self._agregar)
        self.precio.returnPressed.connect(self._agregar)
        for w, estirar in ((self.tipo, 0), (self.descripcion, 1), (QLabel("Cant."), 0), (self.cantidad, 0),
                           (self.precio, 0), (self.b_agregar, 0)):
            fila_a.addWidget(w, estirar)
        vq.addLayout(fila_a)

        fila_d = QHBoxLayout()
        self.descuento = QLineEdit()
        self.descuento.setPlaceholderText("0.00")
        self.descuento.setMaximumWidth(110)
        self.notas = QLineEdit()
        self.notas.setPlaceholderText("Notas para el cliente (garantía, plazo, condiciones)")
        self.notas.setMaxLength(500)
        self.b_desc = QPushButton("Guardar descuento y notas")
        self.b_desc.setObjectName("Secondary")
        self.b_desc.clicked.connect(self._guardar_descuento)
        self.b_quitar = QPushButton("Quitar línea")
        self.b_quitar.setObjectName("Secondary")
        self.b_quitar.clicked.connect(self._quitar)
        fila_d.addWidget(QLabel(f"Descuento ({self.s})"))
        fila_d.addWidget(self.descuento)
        fila_d.addWidget(self.notas, 1)
        fila_d.addWidget(self.b_desc)
        fila_d.addWidget(self.b_quitar)
        vq.addLayout(fila_d)

        self.totales = QLabel("")
        self.totales.setAlignment(Qt.AlignRight)
        self.totales.setStyleSheet("font-size:15px;")
        vq.addWidget(self.totales)

        fila_e = QHBoxLayout()
        self.b_enviar = QPushButton("Marcar como enviado")
        self.b_aprobar = QPushButton("Aprobado por el cliente")
        self.b_rechazar = QPushButton("Rechazado por el cliente")
        self.b_reabrir = QPushButton("Reabrir")
        self.b_pdf_q = QPushButton("Presupuesto (PDF)")
        for b, estado in ((self.b_enviar, "Enviado"), (self.b_aprobar, "Aprobado"),
                          (self.b_rechazar, "Rechazado"), (self.b_reabrir, "Borrador")):
            b.setObjectName("Secondary")
            b.clicked.connect(lambda _c=False, e=estado: self._cambiar_estado(e))
            fila_e.addWidget(b)
        fila_e.addStretch()
        self.b_pdf_q.setObjectName("Secondary")
        self.b_pdf_q.clicked.connect(lambda: self._pdf("presupuesto"))
        fila_e.addWidget(self.b_pdf_q)
        vq.addLayout(fila_e)
        lay.addWidget(p_q)

        # ---------- Pagos ----------
        p_p, vp = panel("Pagos")
        self.pagos = _tabla(COL_PAGOS, 4)
        vp.addWidget(self.pagos)
        fila_p = QHBoxLayout()
        self.importe = QLineEdit()
        self.importe.setPlaceholderText(f"Importe ({self.s})")
        self.importe.setMaximumWidth(130)
        self.metodo = QComboBox()
        self.metodo.addItems(METODOS_PAGO)
        self.nota_pago = QLineEdit()
        self.nota_pago.setPlaceholderText("Nota (opcional): adelanto, n.º de operación…")
        self.nota_pago.setMaxLength(cobro.MAX_DESCRIPCION)
        self.b_saldo = QPushButton("Todo el saldo")
        self.b_saldo.setObjectName("Link")
        self.b_saldo.setCursor(Qt.PointingHandCursor)
        self.b_saldo.clicked.connect(self._poner_saldo)
        self.b_pagar = QPushButton("Registrar pago")
        self.b_pagar.setObjectName("Primary")
        self.b_pagar.clicked.connect(self._pagar)
        for w, estirar in ((self.importe, 0), (self.b_saldo, 0), (self.metodo, 0), (self.nota_pago, 1),
                           (self.b_pagar, 0)):
            fila_p.addWidget(w, estirar)
        vp.addLayout(fila_p)
        fila_p2 = QHBoxLayout()
        self.b_anular = QPushButton("Anular pago…")
        self.b_anular.setObjectName("Secondary")
        self.b_anular.clicked.connect(self._anular)
        self.b_anular.setVisible(self.es_admin)
        self.b_pdf_c = QPushButton("Estado de cuenta (PDF)")
        self.b_pdf_c.setObjectName("Secondary")
        self.b_pdf_c.clicked.connect(lambda: self._pdf("cuenta"))
        self.saldo = QLabel("")
        self.saldo.setStyleSheet("font-size:15px; font-weight:600;")
        fila_p2.addWidget(self.b_anular)
        fila_p2.addWidget(self.b_pdf_c)
        fila_p2.addStretch()
        fila_p2.addWidget(self.saldo)
        vp.addLayout(fila_p2)
        if not self.es_admin:
            vp.addWidget(muted("Para anular un pago registrado por error, pida ayuda a un administrador."))
        lay.addWidget(p_p)

        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        self.msg.hide()
        lay.addWidget(self.msg)
        lay.addStretch()

        cerrar = QPushButton("Cerrar")
        cerrar.setObjectName("Secondary")
        cerrar.clicked.connect(self.accept)
        fila_c = QHBoxLayout()
        fila_c.setContentsMargins(24, 0, 24, 0)
        fila_c.addStretch()
        fila_c.addWidget(cerrar)
        exterior.addLayout(fila_c)
        self._refrescar()

    # ---------- pintado ----------
    def _f(self, centimos: int) -> str:
        return cobro.formato(centimos, self.s)

    def _refrescar(self):
        r = cobro.resumen(self.repo, self.code)
        self.r = r
        entregado = self.repo.get_case(self.code)["status"] == "Entregado"
        self.chip.set_estado(r.estado)
        self.tabla.setRowCount(0)
        for li in r.lineas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, _item(li["description"], li["id"]))
            self.tabla.setItem(fila, 1, _item(TIPOS_LINEA.get(li["kind"], li["kind"])))
            self.tabla.setItem(fila, 2, _item(str(li["quantity"]), derecha=True))
            self.tabla.setItem(fila, 3, _item(self._f(li["unit_price"]), derecha=True))
            self.tabla.setItem(fila, 4, _item(self._f(li["quantity"] * li["unit_price"]), derecha=True))
        partes = [f"Subtotal {self._f(r.subtotal)}"]
        if r.descuento:
            partes.append(f"Descuento −{self._f(r.descuento)}")
        partes.append(f"<b>Total {self._f(r.total)}</b>")
        self.totales.setText(" · ".join(partes))
        self.descuento.setText(f"{r.descuento / 100:.2f}" if r.descuento else "")
        self.notas.setText(r.notas)

        editable = r.editable and not entregado
        for w in (self.tipo, self.descripcion, self.cantidad, self.precio, self.b_agregar, self.descuento,
                  self.notas, self.b_desc, self.b_quitar):
            w.setEnabled(editable)
        hay = bool(r.lineas) and not entregado
        self.b_enviar.setEnabled(hay and r.estado == "Borrador")
        self.b_aprobar.setEnabled(hay and r.estado in ("Borrador", "Enviado", "Rechazado"))
        self.b_rechazar.setEnabled(hay and r.estado in ("Borrador", "Enviado"))
        self.b_reabrir.setEnabled(not entregado and (r.estado == "Rechazado" or
                                                     (r.estado == "Aprobado" and self.es_admin)))
        if r.estado == "Aprobado" and not self.es_admin:
            self.b_reabrir.setToolTip("Solo un administrador puede reabrir un presupuesto aprobado.")

        self.pagos.setRowCount(0)
        for p in r.pagos:
            fila = self.pagos.rowCount()
            self.pagos.insertRow(fila)
            anulado = bool(p["voided_at"])
            estado = f'Anulado: {p["void_reason"]}' if anulado else (p["note"] or "Vigente")
            celdas = [_item(fecha_corta(p["created_at"]), p["id"]), _item(p["method"]),
                      _item(self._f(p["amount"]), derecha=True), _item(p["tech_id"]), _item(estado)]
            for col, it in enumerate(celdas):
                if anulado:
                    fuente = it.font()
                    fuente.setStrikeOut(col == 2)
                    it.setFont(fuente)
                    it.setForeground(QColor(T.texto_suave))
                self.pagos.setItem(fila, col, it)
        rechazado = r.estado == "Rechazado"
        puede_pagar = not rechazado and not (entregado and r.saldo <= 0)
        for w in (self.importe, self.metodo, self.nota_pago, self.b_pagar):
            w.setEnabled(puede_pagar)
        self.b_saldo.setVisible(puede_pagar and r.saldo > 0)
        if r.saldo > 0:
            self.saldo.setText(f"Pagado {self._f(r.pagado)} · Saldo pendiente {self._f(r.saldo)}")
            self.saldo.setStyleSheet(f"font-size:15px; font-weight:600; color:{T.aviso_texto};")
        elif r.saldo < 0:
            self.saldo.setText(f"Pagado {self._f(r.pagado)} · A favor del cliente {self._f(-r.saldo)}")
            self.saldo.setStyleSheet(f"font-size:15px; font-weight:600; color:{T.peligro};")
        else:
            texto = "Pagado por completo" if r.total else "Sin importes"
            self.saldo.setText(f"Pagado {self._f(r.pagado)} · {texto}")
            self.saldo.setStyleSheet(f"font-size:15px; font-weight:600; color:{T.exito};")

    def _aviso(self, texto: str, ok: bool = True):
        self.msg.setStyleSheet(f"color:{T.exito};font-weight:600;" if ok else f"color:{T.peligro};")
        self.msg.setText(texto)
        self.msg.setVisible(bool(texto))

    def _hacer(self, accion, exito: str) -> bool:
        try:
            accion()
        except (ValueError, PermissionError) as e:
            self._aviso(str(e), ok=False)
            return False
        self.changed = True
        self._refrescar()
        self._aviso(exito)
        return True

    # ---------- presupuesto ----------
    def _agregar(self):
        try:
            precio = cobro.a_centimos(self.precio.text())
        except ValueError as e:
            self._aviso(f"Precio: {e}", ok=False)
            return
        if self._hacer(lambda: cobro.agregar_linea(self.repo, self.code, self.tipo.currentData(),
                                                   self.descripcion.text(), self.cantidad.value(), precio),
                       "Línea agregada."):
            self.descripcion.clear()
            self.precio.clear()
            self.cantidad.setValue(1)
            self.descripcion.setFocus()

    def _quitar(self):
        fila = self.tabla.currentRow()
        if fila < 0:
            self._aviso("Seleccione la línea que desea quitar.", ok=False)
            return
        item_id = self.tabla.item(fila, 0).data(Qt.UserRole)
        self._hacer(lambda: cobro.quitar_linea(self.repo, item_id), "Línea quitada.")

    def _guardar_descuento(self):
        try:
            descuento = cobro.a_centimos(self.descuento.text()) if self.descuento.text().strip() else 0
        except ValueError as e:
            self._aviso(f"Descuento: {e}", ok=False)
            return
        self._hacer(lambda: cobro.fijar_descuento(self.repo, self.code, descuento, self.notas.text()),
                    "Descuento y notas guardados.")

    def _cambiar_estado(self, estado: str):
        textos = {"Enviado": "Presupuesto marcado como enviado.", "Aprobado": "Presupuesto aprobado.",
                  "Rechazado": "Presupuesto rechazado.", "Borrador": "Presupuesto reabierto."}
        self._hacer(lambda: cobro.cambiar_estado(self.repo, self.tech_id, self.code, estado), textos[estado])

    # ---------- pagos ----------
    def _poner_saldo(self):
        self.importe.setText(f"{self.r.saldo / 100:.2f}")

    def _pagar(self):
        try:
            monto = cobro.a_centimos(self.importe.text())
        except ValueError as e:
            self._aviso(f"Importe: {e}", ok=False)
            return
        if self._hacer(lambda: cobro.registrar_pago(self.repo, self.tech_id, self.code, monto,
                                                    self.metodo.currentText(), self.nota_pago.text()),
                       f"Pago de {self._f(monto)} registrado."):
            self.importe.clear()
            self.nota_pago.clear()

    def _anular(self):
        fila = self.pagos.currentRow()
        if fila < 0:
            self._aviso("Seleccione el pago que desea anular.", ok=False)
            return
        pago_id = self.pagos.item(fila, 0).data(Qt.UserRole)
        motivo, ok = QInputDialog.getText(self, "Anular pago", "Motivo de la anulación (queda registrado):")
        if not ok:
            return
        self._hacer(lambda: cobro.anular_pago(self.repo, self.tech_id, pago_id, motivo), "Pago anulado.")

    # ---------- PDF ----------
    def _pdf(self, tipo: str):
        try:
            ruta = generate_report(self.repo, ReportsRepository(self.repo), self.code, tipo, self.tech_id)
        except Exception as e:
            self._aviso(f"No se pudo generar el PDF: {e}", ok=False)
            return
        self.changed = True
        self._aviso(f"PDF guardado: {Path(ruta).name}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ruta)))
