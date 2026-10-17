import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from app.ai.ollama_client import OllamaError
from app.db.database import Database
from app.db.repo import Repository
from app.db.reports_repo import ReportsRepository
from app.paths import VAR_DATOS


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def entorno(monkeypatch, tmp_path):
    monkeypatch.setenv(VAR_DATOS, str(tmp_path / "appdata"))

    def sin_ollama(*args, **kwargs):
        raise OllamaError("sin ollama")

    monkeypatch.setattr("app.ai.config.list_models", sin_ollama)
    monkeypatch.setattr("app.ui.pages.ia_local.list_models", sin_ollama)


@pytest.fixture
def repo(tmp_path, qapp):
    db = Database(tmp_path / "ui.db")
    r = Repository(db)
    r.set_setting("auto_backup", "0")
    yield r
    db.close()


def _esperar():
    """Espera a las búsquedas en segundo plano y entrega sus resultados a la interfaz."""
    QThreadPool.globalInstance().waitForDone(5000)
    QApplication.processEvents()


def _poblar(repo, n):
    for i in range(n):
        repo.register_intake(f"Cliente {i:03d}", f"9{i:08d}", f"SN-{i:04d}", "Laptop HP", f"Problema {i}")


def test_historial_busca_y_filtra(repo):
    from app.ui.pages.historial import HistorialPage
    repo.register_intake("Luis Paredes", "1", "SN-1", "Laptop HP", "Se calienta")
    repo.register_intake("Ana Torres", "2", "SN-2", "PC Dell", "Lento")
    repo.register_intake("Marta Díaz", "3", "SN-3", "PC armada", "RAM")
    page = HistorialPage(repo)
    assert page.tabla.rowCount() == 3
    page.buscar.setText("Ana")
    page.buscar_ahora(sync=True)
    assert page.tabla.rowCount() == 1 and "1 resultado" in page.estado.text()
    page.buscar.setText("zzz")
    page.buscar_ahora(sync=True)
    assert page.tabla.rowCount() == 0 and "Sin resultados" in page.estado.text()
    page.limpiar()
    page.buscar_ahora(sync=True)
    assert page.tabla.rowCount() == 3 and page.buscar.text() == ""


def test_historial_asincrono_y_paginacion(repo):
    from app.ui.pages.historial import HistorialPage
    _poblar(repo, 60)
    page = HistorialPage(repo)
    assert page.tabla.rowCount() == 50 and "Página 1 de 2" in page.pager.lbl.text()
    page._ir_pagina(1)
    _esperar()
    assert page.tabla.rowCount() == 10 and "Página 2 de 2" in page.pager.lbl.text()
    page.buscar.setText("Cliente 059")
    page.buscar_ahora()
    _esperar()
    assert page.tabla.rowCount() >= 1 and "Página 1 de 1" in page.pager.lbl.text()


def test_historial_filtros_se_combinan_con_texto(repo):
    from app.ui.pages.historial import HistorialPage
    _poblar(repo, 6)
    repo.update_case_status("C-001", "Listo")
    repo.update_case_status("C-002", "Listo")
    page = HistorialPage(repo)
    page.f_estado.setCurrentText("Listo")
    page.buscar.setText("SN-0001")
    page.buscar_ahora(sync=True)
    assert page.tabla.rowCount() == 1 and page.tabla.item(0, 0).text() == "C-002"


def test_historial_error_se_muestra(repo, monkeypatch):
    from app.ui.pages.historial import HistorialPage

    def boom(self, **kw):
        raise RuntimeError("fallo simulado")

    page = HistorialPage(repo)
    monkeypatch.setattr("app.db.search_repo.SearchQueries.search_cases", boom)
    page.refresh(sync=True)
    assert "No se pudo completar la búsqueda: fallo simulado" in page.estado.text()
    page.refresh()  # también en segundo plano
    _esperar()
    assert "fallo simulado" in page.estado.text()


def test_reportes_filtra_y_selector(repo):
    from app.ui.pages.reportes import ReportesPage
    c1 = repo.register_intake("Luis", "1", "SN-1", "Laptop", "a")
    c2 = repo.register_intake("Ana", "2", "SN-2", "PC", "b")
    rr = ReportsRepository(repo)
    rr.add(c1, "tecnico", "C:/x/a.pdf")
    rr.add(c2, "cliente", "C:/x/b.pdf")
    page = ReportesPage(repo, "TEC-001")
    assert page.tabla.rowCount() == 2 and page.combo.count() == 2
    page.f_tipo.setCurrentIndex(1)
    page.buscar_ahora(sync=True)
    assert page.tabla.rowCount() == 1 and page.tabla.item(0, 0).text() == c1
    page.buscar_caso.setText("Ana")
    page._cargar_casos()
    assert page.combo.count() == 1
    page.buscar_caso.setText("zzz")
    page._cargar_casos()
    assert page.combo.count() == 0 and not page.b_tec.isEnabled()


def test_detalle_del_caso_muestra_sus_reportes(repo):
    from app.ui.case_dialog import CaseDialog
    c1 = repo.register_intake("Luis", "1", "SN-1", "Laptop", "a")
    c2 = repo.register_intake("Ana", "2", "SN-2", "PC", "b")
    rr = ReportsRepository(repo)
    rr.add(c1, "tecnico", "C:/x/a.pdf")
    rr.add(c2, "cliente", "C:/x/b.pdf")
    dlg = CaseDialog(repo, c1)
    assert dlg.lista_reportes.count() == 1
    assert "Técnico" in dlg.lista_reportes.item(0).text()
