"""Fase 14: orden de servicio (accesorios, estado físico, fecha estimada y PDF para firmar)."""
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.db.database import Database
from app.db.orders_repo import TERMINOS_PREDETERMINADOS, OrdersRepository
from app.db.repo import Repository
from app.db.reports_repo import ReportsRepository
from app.reports.orden import load_order_data
from app.reports.service import KINDS, generate_report


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    db = Database(tmp_path / "orden.db")
    yield Repository(db)
    db.close()


@pytest.fixture
def caso(repo):
    return repo.register_intake("Ana Díaz", "987 654 321", "SN-1", "Laptop HP", "No enciende")


def test_guardar_y_corregir_orden(repo, caso):
    orders = OrdersRepository(repo)
    orders.save(caso, ["Cargador", " ", "Mouse"], "Rayón en la tapa", "", "2026-12-01", "kq")
    o = orders.get(caso)
    assert o["accessories"] == "Cargador, Mouse"
    assert o["condition"] == "Rayón en la tapa" and o["estimated_date"] == "2026-12-01"
    assert o["received_by"] == "KQ"
    orders.save(caso, "Cargador", "Sin daños", "Respaldar archivos", "")  # corrección
    o = orders.get(caso)
    assert (o["accessories"], o["condition"], o["observations"], o["estimated_date"]) == \
        ("Cargador", "Sin daños", "Respaldar archivos", "")
    assert o["received_by"] == "KQ"  # quien recibió no se pierde al corregir


def test_validaciones(repo, caso):
    orders = OrdersRepository(repo)
    with pytest.raises(ValueError, match="No existe"):
        orders.save("C-999")
    with pytest.raises(ValueError, match="fecha"):
        orders.save(caso, estimated_date="31/12/2026")
    with pytest.raises(ValueError, match="500"):
        orders.save(caso, condition="x" * 501)
    repo.update_case_status(caso, "Entregado")
    with pytest.raises(ValueError, match="entregado"):
        orders.save(caso, "Cargador")


def test_terminos_editables(repo):
    orders = OrdersRepository(repo)
    assert len(orders.terms()) == len(TERMINOS_PREDETERMINADOS.splitlines())
    repo.set_setting("service_terms", "Garantía de 30 días.\n\n  Pago al retirar.  ")
    assert orders.terms() == ["Garantía de 30 días.", "Pago al retirar."]


def test_pdf_de_la_orden(repo, caso, tmp_path):
    OrdersRepository(repo).save(caso, ["Cargador"], "Rayón", "Cliente indica caída", "2026-12-01", "KQ")
    data = load_order_data(repo, caso)
    assert data["order"]["accessories"] == "Cargador" and data["caso"]["cliente"] == "Ana Díaz"
    rr = ReportsRepository(repo)
    ruta = generate_report(repo, rr, caso, "orden", "KQ", out_dir=tmp_path)
    assert ruta.read_bytes().startswith(b"%PDF") and "_orden_" in ruta.name
    assert rr.for_case(caso)[0]["kind"] == "orden" and KINDS["orden"] == "Orden de servicio"


def test_pdf_sin_orden_registrada(repo, caso, tmp_path):
    """Casos antiguos (sin orden) también pueden imprimirla, con valores por defecto."""
    ruta = generate_report(repo, ReportsRepository(repo), caso, "orden", out_dir=tmp_path)
    assert ruta.exists()


# ---------------- Interfaz ----------------
@pytest.fixture
def ui_repo(repo):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    return repo


def _llenar(page):
    page.cliente.setText("Luis Paredes")
    page.equipo.setText("Laptop Lenovo")
    page.serie.setText("SN-77")
    page.problema.setText("Lento")


def test_recepcion_guarda_orden_y_la_abre(ui_repo, _sin_abrir_archivos):
    from app.ui.pages.recepcion import RecepcionPage
    page = RecepcionPage(ui_repo, "TEC-1")
    _llenar(page)
    page.accesorios[0].setChecked(True)  # Cargador
    page.otros_acc.setText("Lápiz óptico")
    page.estado_fisico.setText("Bisagra floja")
    page.chk_fecha.setChecked(True)
    page._guardar()
    assert page.ok.text().startswith("Caso C-001") and "Aviso" not in page.ok.text()
    o = OrdersRepository(ui_repo).get("C-001")
    assert o["accessories"] == "Cargador, Lápiz óptico" and o["condition"] == "Bisagra floja"
    assert o["estimated_date"] == (date.today() + timedelta(days=3)).isoformat()
    assert o["received_by"] == "TEC-1"
    assert len(_sin_abrir_archivos) == 1 and "_orden_" in Path(_sin_abrir_archivos[0].toLocalFile()).name
    # el formulario queda limpio para la siguiente recepción
    assert not page.accesorios[0].isChecked() and page.estado_fisico.text() == ""
    assert not page.chk_fecha.isChecked()


def test_recepcion_sin_imprimir_y_preferencia_recordada(ui_repo, _sin_abrir_archivos):
    from app.ui.pages.recepcion import RecepcionPage
    page = RecepcionPage(ui_repo)
    page.chk_orden.setChecked(False)
    _llenar(page)
    page._guardar()
    assert OrdersRepository(ui_repo).get("C-001") is not None
    assert _sin_abrir_archivos == []
    assert not RecepcionPage(ui_repo).chk_orden.isChecked()


def test_recepcion_rechaza_fecha_pasada(ui_repo):
    from PySide6.QtCore import QDate

    from app.ui.pages.recepcion import RecepcionPage
    page = RecepcionPage(ui_repo)
    _llenar(page)
    page.chk_fecha.setChecked(True)
    page.fecha.setDate(QDate.currentDate().addDays(-1))
    page._guardar()
    assert "anterior a hoy" in page.error.text()
    assert ui_repo.list_cases() == []


def test_recepcion_no_abre_orden_si_no_se_guardo(ui_repo, _sin_abrir_archivos, monkeypatch):
    from app.ui.pages.recepcion import RecepcionPage

    def falla(*a, **k):
        raise RuntimeError("bloqueada")
    monkeypatch.setattr(OrdersRepository, "save", falla)
    page = RecepcionPage(ui_repo)
    _llenar(page)
    page._guardar()
    assert page.ok.text().startswith("Caso C-001") and "orden de servicio" in page.ok.text()
    assert _sin_abrir_archivos == []
