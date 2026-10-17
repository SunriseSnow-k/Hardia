"""Fase 17: presupuesto y cobro (líneas, estados, pagos, anulaciones, auditoría y PDF)."""
import pytest

from app.db.audit_repo import AuditRepository
from app.db.billing_repo import BillingRepository
from app.db.database import Database
from app.db.repo import Repository
from app.db.reports_repo import ReportsRepository
from app.paths import VAR_DATOS
from app.reports.service import generate_report
from app.servicios import cobro
from app.servicios.cuentas import SinPermiso


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv(VAR_DATOS, str(tmp_path / "appdata"))
    db = Database(tmp_path / "cobro.db")
    r = Repository(db)
    r.create_user("ADM", "secreto1")             # primera cuenta: administrador
    r.create_user("TEC", "secreto1", role="tecnico")
    yield r
    db.close()


@pytest.fixture
def caso(repo):
    return repo.register_intake("Ana Díaz", "987 654 321", "SN-1", "Laptop HP", "No enciende")


def _acciones(repo):
    return [a["action"] for a in AuditRepository(repo).recientes()]


@pytest.mark.parametrize("texto, centimos", [
    ("120", 12000), ("120,5", 12050), ("120.50", 12050), ("S/ 1.250,90", 125090), ("1,250.90", 125090),
    ("1.250", 125000), ("1,250", 125000), ("0", 0), (" 15 ", 1500), (".5", 50),
])
def test_a_centimos(texto, centimos):
    assert cobro.a_centimos(texto) == centimos


@pytest.mark.parametrize("texto, error", [
    ("", "Escriba"), ("abc", "Escriba"), ("-5", "negativo"), ("1.234,567", "dos decimales"),
    ("2000000", "demasiado grande"), ("1-2", "no es válido"),
])
def test_a_centimos_rechaza(texto, error):
    with pytest.raises(ValueError, match=error):
        cobro.a_centimos(texto)


def test_formato():
    assert cobro.formato(125090) == "S/ 1,250.90"
    assert cobro.formato(-500, "$") == "-$ 5.00"


def test_presupuesto_totales_y_descuento(repo, caso):
    assert cobro.resumen(repo, caso).estado == "Sin presupuesto"
    cobro.agregar_linea(repo, caso, "servicio", "Mantenimiento", 1, 8000)
    lid = cobro.agregar_linea(repo, caso, "repuesto", "Pasta térmica", 2, 1500)
    cobro.fijar_descuento(repo, caso, 1000, "Cliente frecuente")
    r = cobro.resumen(repo, caso)
    assert (r.estado, r.subtotal, r.descuento, r.total, r.saldo) == ("Borrador", 11000, 1000, 10000, 10000)
    assert r.notas == "Cliente frecuente"
    cobro.quitar_linea(repo, lid)
    r = cobro.resumen(repo, caso)
    assert r.subtotal == 8000 and r.total == 7000
    with pytest.raises(ValueError, match="subtotal"):
        cobro.fijar_descuento(repo, caso, 9000)


@pytest.mark.parametrize("args, error", [
    (("otro", "X", 1, 100), "Tipo"), (("servicio", "  ", 1, 100), "descripción"),
    (("servicio", "x" * 201, 1, 100), "200"), (("servicio", "X", 0, 100), "cantidad"),
    (("servicio", "X", 1, -1), "precio"),
])
def test_validaciones_de_linea(repo, caso, args, error):
    with pytest.raises(ValueError, match=error):
        cobro.agregar_linea(repo, caso, *args)


def test_estados_y_bloqueo_tras_aprobar(repo, caso):
    with pytest.raises(ValueError, match="al menos una línea"):
        cobro.cambiar_estado(repo, "TEC", caso, "Enviado")
    cobro.agregar_linea(repo, caso, "servicio", "Cambio de pantalla", 1, 30000)
    cobro.cambiar_estado(repo, "TEC", caso, "Enviado")
    cobro.cambiar_estado(repo, "tec", caso, "Aprobado")
    r = cobro.resumen(repo, caso)
    assert r.estado == "Aprobado" and r.decidido_por == "TEC" and r.decidido_el and not r.editable
    with pytest.raises(ValueError, match="Reábralo"):
        cobro.agregar_linea(repo, caso, "servicio", "Extra", 1, 100)
    with pytest.raises(SinPermiso):
        cobro.cambiar_estado(repo, "TEC", caso, "Borrador")  # reabrir uno aprobado: solo administrador
    cobro.cambiar_estado(repo, "ADM", caso, "Borrador")
    assert cobro.resumen(repo, caso).decidido_por == ""
    cobro.cambiar_estado(repo, "TEC", caso, "Rechazado")
    assert _acciones(repo)[:3] == ["presupuesto_rechazado", "presupuesto_reabierto", "presupuesto_aprobado"]
    with pytest.raises(ValueError, match="no válido"):
        cobro.cambiar_estado(repo, "TEC", caso, "Pagado")


def test_entregado_no_se_modifica(repo, caso):
    cobro.agregar_linea(repo, caso, "servicio", "Revisión", 1, 2000)
    repo.update_case_status(caso, "Entregado")
    with pytest.raises(ValueError, match="entregado"):
        cobro.agregar_linea(repo, caso, "servicio", "Otra", 1, 100)
    with pytest.raises(ValueError, match="entregado"):
        cobro.cambiar_estado(repo, "TEC", caso, "Aprobado")
    # el saldo de un equipo entregado todavía se puede cobrar
    cobro.registrar_pago(repo, "TEC", caso, 2000, "Efectivo")
    with pytest.raises(ValueError, match="no tiene saldo"):
        cobro.registrar_pago(repo, "TEC", caso, 100, "Efectivo")


def test_pagos_adelanto_saldo_y_anulacion(repo, caso):
    pid = cobro.registrar_pago(repo, "TEC", caso, 5000, "Efectivo", "Adelanto")  # sin presupuesto: adelanto
    cobro.agregar_linea(repo, caso, "servicio", "Reparación de placa", 1, 20000)
    cobro.cambiar_estado(repo, "TEC", caso, "Aprobado")
    with pytest.raises(ValueError, match="supera el saldo"):
        cobro.registrar_pago(repo, "TEC", caso, 15001, "Tarjeta")
    cobro.registrar_pago(repo, "TEC", caso, 15000, "Tarjeta")
    assert cobro.saldo_pendiente(repo, caso) == 0
    with pytest.raises(SinPermiso):
        cobro.anular_pago(repo, "TEC", pid, "Error de digitación")
    with pytest.raises(ValueError, match="motivo"):
        cobro.anular_pago(repo, "ADM", pid, " ")
    cobro.anular_pago(repo, "ADM", pid, "Error de digitación")
    with pytest.raises(ValueError, match="ya estaba anulado"):
        cobro.anular_pago(repo, "ADM", pid, "otra vez")
    r = cobro.resumen(repo, caso)
    assert r.pagado == 15000 and r.saldo == 5000 and len(r.pagos) == 2
    anulado = BillingRepository(repo).payment(pid)
    assert anulado["voided_by"] == "ADM" and anulado["void_reason"] == "Error de digitación"
    assert _acciones(repo)[0] == "pago_anulado"
    assert sum(a == "pago_registrado" for a in _acciones(repo)) == 2


@pytest.mark.parametrize("kw, error", [
    (dict(monto=0, metodo="Efectivo"), "mayor que cero"), (dict(monto=100, metodo="Cheque"), "Forma de pago"),
    (dict(monto=100, metodo="Efectivo", nota="x" * 201), "200"),
])
def test_validaciones_de_pago(repo, caso, kw, error):
    with pytest.raises(ValueError, match=error):
        cobro.registrar_pago(repo, "TEC", caso, **kw)


def test_pago_requiere_tecnico_activo_y_presupuesto_no_rechazado(repo, caso):
    with pytest.raises(SinPermiso):
        cobro.registrar_pago(repo, "NADIE", caso, 100, "Efectivo")
    cobro.agregar_linea(repo, caso, "servicio", "Revisión", 1, 2000)
    cobro.cambiar_estado(repo, "TEC", caso, "Rechazado")
    with pytest.raises(ValueError, match="rechazado"):
        cobro.registrar_pago(repo, "TEC", caso, 100, "Efectivo")
    with pytest.raises(ValueError, match="No existe"):
        cobro.registrar_pago(repo, "TEC", "C-999", 100, "Efectivo")


def test_simbolo_configurable(repo):
    assert cobro.simbolo(repo) == "S/"
    repo.set_setting("currency_symbol", "$")
    assert cobro.simbolo(repo) == "$"


@pytest.mark.parametrize("kind", ["presupuesto", "cuenta"])
def test_pdfs(repo, caso, tmp_path, kind):
    cobro.agregar_linea(repo, caso, "servicio", "Mantenimiento <completo>", 1, 8000)
    cobro.fijar_descuento(repo, caso, 500, "Incluye limpieza")
    cobro.cambiar_estado(repo, "TEC", caso, "Aprobado")
    cobro.registrar_pago(repo, "TEC", caso, 3000, "Efectivo")
    ruta = generate_report(repo, ReportsRepository(repo), caso, kind, "TEC", out_dir=tmp_path)
    assert ruta.read_bytes().startswith(b"%PDF") and f"_{kind}_" in ruta.name


@pytest.mark.parametrize("kind", ["presupuesto", "cuenta"])
def test_pdfs_sin_datos(repo, caso, tmp_path, kind):
    ruta = generate_report(repo, ReportsRepository(repo), caso, kind, out_dir=tmp_path)
    assert ruta.exists()


# ---------------- Interfaz ----------------
@pytest.fixture
def ui(repo):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    repo.session_tech = "TEC"
    return repo


def test_dialogo_presupuesto_y_pago(ui, caso, _sin_abrir_archivos):
    from app.ui.cobro_dialog import CobroDialog
    dlg = CobroDialog(ui, caso)
    assert not dlg.b_anular.isVisible() and not dlg.b_enviar.isEnabled()
    dlg.descripcion.setText("Cambio de teclado")
    dlg.precio.setText("abc")
    dlg._agregar()
    assert "Precio" in dlg.msg.text() and dlg.tabla.rowCount() == 0
    dlg.precio.setText("150,00")
    dlg.cantidad.setValue(2)
    dlg._agregar()
    assert dlg.tabla.rowCount() == 1 and dlg.descripcion.text() == "" and "300.00" in dlg.totales.text()
    dlg.descuento.setText("20")
    dlg.notas.setText("Garantía de 90 días")
    dlg._guardar_descuento()
    assert cobro.resumen(ui, caso).total == 28000
    dlg._cambiar_estado("Aprobado")
    assert dlg.chip.text() == "Aprobado" and not dlg.b_agregar.isEnabled() and not dlg.b_reabrir.isEnabled()
    dlg._poner_saldo()
    assert dlg.importe.text() == "280.00"
    dlg.importe.setText("300")
    dlg._pagar()
    assert "supera el saldo" in dlg.msg.text()
    dlg.importe.setText("280")
    dlg._pagar()
    assert dlg.pagos.rowCount() == 1 and "Pagado por completo" in dlg.saldo.text() and dlg.changed
    dlg._pdf("cuenta")
    assert "_cuenta_" in _sin_abrir_archivos[-1].toLocalFile()


def test_dialogo_quitar_linea_y_anular_como_admin(ui, caso, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from app.ui.cobro_dialog import CobroDialog
    ui.session_tech = "ADM"
    cobro.agregar_linea(ui, caso, "repuesto", "Batería", 1, 9000)
    cobro.registrar_pago(ui, "ADM", caso, 4000, "Efectivo")
    dlg = CobroDialog(ui, caso)
    dlg._quitar()
    assert "Seleccione" in dlg.msg.text()
    dlg.tabla.selectRow(0)
    dlg._quitar()
    assert dlg.tabla.rowCount() == 0 and "A favor del cliente" in dlg.saldo.text()
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Cobro duplicado", True)))
    dlg.pagos.selectRow(0)
    dlg._anular()
    assert dlg.pagos.item(0, 4).text() == "Anulado: Cobro duplicado"
    assert cobro.resumen(ui, caso).pagado == 0


def test_caso_avisa_saldo_al_entregar(ui, caso, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from app.ui.case_dialog import CaseDialog
    cobro.agregar_linea(ui, caso, "servicio", "Formateo", 1, 6000)
    dlg = CaseDialog(ui, caso)
    assert "saldo S/ 60.00" in dlg.cobro_lbl.text()
    preguntas = []
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: preguntas.append(a[2]) or QMessageBox.No))
    dlg.estado.setCurrentText("Entregado")
    dlg._guardar_estado()
    assert ui.get_case(caso)["status"] == "Recibido" and "S/ 60.00" in preguntas[0]
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    dlg._guardar_estado()
    assert ui.get_case(caso)["status"] == "Entregado"


def test_configuracion_guarda_moneda(ui):
    from app.ui.pages.configuracion import ConfiguracionPage
    page = ConfiguracionPage(ui, "ADM")
    assert page.moneda.text() == "S/"
    page.nombre.setText("Taller Kevin")
    page.moneda.setText("$")
    page._guardar_negocio()
    assert cobro.simbolo(ui) == "$"
    page.moneda.setText(" ")
    page._guardar_negocio()
    assert "moneda" in page.msg_neg.text() and cobro.simbolo(ui) == "$"
