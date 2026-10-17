import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.db.database import Database
from app.db.hardware_repo import HardwareRepository
from app.db.repo import Repository
from app.hardware import diag_file
from app.hardware.scanner import run_scan
from app.paths import VAR_DATOS
from tests.test_fase10b_hardware import _env, _psutil


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def entorno(monkeypatch, tmp_path):
    monkeypatch.setenv(VAR_DATOS, str(tmp_path / "appdata"))


@pytest.fixture
def repo(tmp_path, qapp):
    db = Database(tmp_path / "ui.db")
    yield Repository(db)
    db.close()


def _scan(**kw):
    s = run_scan(env=_env(**kw))
    s["provenance"] = {"how": "local_scan", "file": None}
    return s


def test_inventario_detallado(qapp):
    from app.ui.inventory_dialog import InventoryDialog
    dlg = InventoryDialog(run_scan(env=_env(psutil=_psutil(bateria=False))))
    grupos = {dlg.arbol.topLevelItem(i).text(0): dlg.arbol.topLevelItem(i)
              for i in range(dlg.arbol.topLevelItemCount())}
    assert len(grupos) == 11 and "Procesador" in grupos and "Batería" in grupos
    bateria = grupos["Batería"].child(0)
    assert bateria.text(0) == "Estado de la detección" and bateria.text(2) == "No aplica en este equipo"
    cpu = {grupos["Procesador"].child(i).text(0): grupos["Procesador"].child(i).text(1)
           for i in range(grupos["Procesador"].childCount())}
    assert cpu["Núcleos físicos"] == "4" and cpu["Fabricante"] == "Intel"


def test_importar_archivo_nuevo_y_antiguo(repo, tmp_path):
    from app.ui.pages.escaneo import EscaneoPage
    nuevo = diag_file.save_scan(run_scan(env=_env()), tmp_path / "nuevo.diag")
    viejo = diag_file.save_scan({"format": "SD-DIAG", "version": 1, "scanned_at": "2026-09-01T08:00:00",
                                 "summary": {}, "metrics": {},
                                 "components": [{"name": "CPU", "detail": "i5", "status": "ok"}]},
                                tmp_path / "viejo.diag")
    page = EscaneoPage()
    capturado = []
    page.use_data.connect(capturado.append)
    page._importar(nuevo)
    assert len(page.filas) == 11 and page.b_inv.isEnabled()
    assert page.data["provenance"]["how"] == "imported_file" and page.data["provenance"]["file"] == "nuevo.diag"
    page._usar()
    assert capturado[0]["provenance"]["file"] == "nuevo.diag"
    page._importar(viejo)
    assert len(page.filas) == 1 and not page.b_inv.isEnabled() and page.b_usar.isEnabled()
    page._importar(tmp_path / "no_existe.diag")
    assert "No se pudo importar" in page.msg.text()


def test_recepcion_reconoce_el_equipo_registrado(repo):
    from app.ui.pages.recepcion import RecepcionPage
    hwr = HardwareRepository(repo)
    code = repo.register_intake("Luis Paredes", "987", "SN-1", "Laptop HP 15", "Lento")
    hwr.save_capture(code, _scan())
    page = RecepcionPage(repo)
    page.set_hardware(_scan())
    assert "Equipo ya registrado" in page.ident_lbl.text()
    assert page.serie.text() == "SN-1"  # la serie registrada, no la del BIOS
    assert not page.alert.isHidden() and page.cliente.text() == "Luis Paredes"


def test_recepcion_equipo_nuevo_y_ambiguo(repo):
    from app.ui.pages.recepcion import RecepcionPage
    page = RecepcionPage(repo)
    page.set_hardware(_scan())
    assert "Equipo nuevo" in page.ident_lbl.text()
    assert page.serie.text() == "5CD1234ABC" and page.equipo.text() == "HP Laptop 15-dw"
    # ambiguo: el UUID es de un equipo y la serie de otro
    hwr = HardwareRepository(repo)
    a = repo.register_intake("Ana", "1", "SN-A", "PC A", "x")
    b = repo.register_intake("Beto", "2", "SN-B", "PC B", "y")
    ea = repo.c.execute("SELECT equipment_id FROM cases WHERE code=?", (a,)).fetchone()[0]
    eb = repo.c.execute("SELECT equipment_id FROM cases WHERE code=?", (b,)).fetchone()[0]
    hwr.add_identifiers(ea, [("uuid", "4C4C4544-0042-4A10-8057-B8C04F4D3532")])
    hwr.add_identifiers(eb, [("serial", "5CD1234ABC")])
    page2 = RecepcionPage(repo)
    page2.set_hardware(_scan())
    assert "varios equipos" in page2.ident_lbl.text() and page2.serie.text() == ""


def test_recepcion_guarda_capturas_sin_perder_las_anteriores(repo):
    from app.ui.pages.recepcion import RecepcionPage
    page = RecepcionPage(repo)
    for problema in ("Lento", "Se calienta"):
        page.set_hardware(_scan())
        page.cliente.setText("Luis Paredes")
        page.telefono.setText("987")
        page.equipo.setText("Laptop HP")
        page.serie.setText("SN-1")
        page.problema.setText(problema)
        page._guardar()
        assert page.ok.text().startswith("Caso C-") and "Aviso" not in page.ok.text()
    hwr = HardwareRepository(repo)
    eq = repo.c.execute("SELECT id FROM equipment").fetchall()
    assert len(eq) == 1
    assert len(hwr.captures_for_equipment(eq[0][0])) == 2
    assert repo.c.execute("SELECT cpu FROM equipment").fetchone()[0].startswith("Intel(R) Core")
    assert {c["case_code"] for c in hwr.captures_for_equipment(eq[0][0])} == {"C-001", "C-002"}


def test_conflicto_de_identificadores_se_avisa(repo):
    from app.ui.pages.recepcion import RecepcionPage
    hwr = HardwareRepository(repo)
    otro = repo.register_intake("Ana", "1", "SN-OTRO", "PC", "x")
    eo = repo.c.execute("SELECT equipment_id FROM cases WHERE code=?", (otro,)).fetchone()[0]
    hwr.add_identifiers(eo, [("uuid", "4C4C4544-0042-4A10-8057-B8C04F4D3532")])
    page = RecepcionPage(repo)
    page.set_hardware(_scan())
    page.cliente.setText("Luis")
    page.equipo.setText("Laptop")
    page.serie.setText("SN-NUEVO")  # el técnico escribe otra serie
    page.problema.setText("Lento")
    page._guardar()
    assert "ya pertenecen a otro equipo" in page.ok.text()
