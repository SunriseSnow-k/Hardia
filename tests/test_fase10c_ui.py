"""Parte C (interfaz): documento en la recepción, notas y reportes en el detalle del caso."""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.db.clients_repo import ClientsRepository
from app.db.database import Database
from app.db.notes_repo import NotesRepository
from app.db.repo import Repository
from app.db.reports_repo import ReportsRepository
from app.paths import VAR_DATOS


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def entorno(monkeypatch, tmp_path):
    monkeypatch.setenv(VAR_DATOS, str(tmp_path / "appdata"))
    abiertos = []

    class _SinVisor:  # no abre el visor de PDF durante las pruebas
        # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
        @staticmethod
        def openUrl(url):
            abiertos.append(url)

    monkeypatch.setattr("app.ui.case_dialog.QDesktopServices", _SinVisor)
    return abiertos


@pytest.fixture
def repo(tmp_path, qapp):
    db = Database(tmp_path / "ui.db")
    r = Repository(db)
    r.session_tech = "TEC-007"
    yield r
    db.close()


def _llenar(page, documento="4567-8912"):
    page.cliente.setText("Luis Peña")
    page.telefono.setText("987")
    page.documento.setText(documento)
    page.equipo.setText("Laptop HP")
    page.serie.setText("SN-1")
    page.problema.setText("Lento")


def test_recepcion_guarda_el_documento(repo):
    from app.ui.pages.recepcion import RecepcionPage
    page = RecepcionPage(repo)
    _llenar(page)
    page._guardar()
    assert page.ok.text().startswith("Caso C-001") and page.documento.text() == ""
    assert ClientsRepository(repo).doc_for_case("C-001") == "45678912"


def test_recepcion_documento_invalido_no_registra(repo):
    from app.ui.pages.recepcion import RecepcionPage
    page = RecepcionPage(repo)
    _llenar(page, documento="45%67")
    page._guardar()
    assert "letras y números" in page.error.text()
    assert repo.list_cases() == []


def test_recepcion_completa_por_documento_y_reingreso(repo):
    from app.ui.pages.recepcion import RecepcionPage
    code = repo.register_intake("Ana Ríos", "999", "SN-9", "PC", "Lento")
    ClientsRepository(repo).set_doc_for_case(code, "10456789")
    page = RecepcionPage(repo)
    page.documento.setText("10456789")
    assert page.cliente.text() == "Ana Ríos" and page.telefono.text() == "999"
    page2 = RecepcionPage(repo)
    page2.serie.setText("SN-9")  # reingreso: también trae el documento
    assert page2.documento.text() == "10456789"


def test_caso_agrega_notas_con_el_tecnico_de_la_sesion(repo):
    from app.ui.case_dialog import CaseDialog
    code = repo.register_intake("Luis", "1", "SN-1", "Laptop", "Lento")
    dlg = CaseDialog(repo, code)
    assert dlg.lista_notas.count() == 1 and "Aún no hay notas" in dlg.lista_notas.item(0).text()
    dlg._agregar_nota()  # vacía
    assert "vacía" in dlg.msg_nota.text()
    dlg.tipo_nota.setCurrentIndex(dlg.tipo_nota.findData("trabajo"))
    dlg.texto_nota.setPlainText("Limpieza interna")
    dlg._agregar_nota()
    notas = NotesRepository(repo).for_case(code)
    assert len(notas) == 1 and notas[0]["kind"] == "trabajo" and notas[0]["author"] == "TEC-007"
    assert "Limpieza interna" in dlg.lista_notas.item(0).text() and dlg.changed
    dlg.done(0)


def test_caso_genera_reportes(repo, entorno):
    from app.ui.case_dialog import CaseDialog
    code = repo.register_intake("Luis", "1", "SN-1", "Laptop", "Lento")
    dlg = CaseDialog(repo, code)
    dlg._generar_reporte("cliente")
    assert "Reporte guardado" in dlg.ok.text() and len(entorno) == 1
    assert dlg.lista_reportes.count() == 1 and "Cliente" in dlg.lista_reportes.item(0).text()
    assert ReportsRepository(repo).for_case(code)[0]["kind"] == "cliente"
    dlg.done(0)
