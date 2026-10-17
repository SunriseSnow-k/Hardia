"""Fase 11 (diseño nuevo): utilidades de los widgets, textos derivados de los datos,
búsquedas ampliadas y cierre de sesión. No cambia la lógica del diagnóstico."""
from datetime import datetime

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.ai.ollama_client import OllamaError
from app.db.clients_repo import ClientsRepository
from app.db.database import Database
from app.db.equipment_repo import EquipmentRepository
from app.db.hardware_repo import HardwareRepository
from app.db.repo import Repository
from app.hardware.scanner import run_scan
from app.paths import VAR_DATOS
from tests.test_fase10b_hardware import _env, _psutil


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


def _scan(**kw):
    s = run_scan(env=_env(**kw))
    s["provenance"] = {"how": "local_scan", "file": None}
    return s


# ---------------- utilidades puras ----------------
def test_tiempo_transcurrido_y_fechas():
    from app.ui.widgets import fecha_corta, fecha_larga, tiempo_transcurrido
    ahora = datetime(2026, 10, 13, 12, 0, 0)
    assert tiempo_transcurrido("2026-10-13 11:59:30", ahora) == "hace un momento"
    assert tiempo_transcurrido("2026-10-13 11:20:00", ahora) == "hace 40 min"
    assert tiempo_transcurrido("2026-10-13T09:00:00", ahora) == "hace 3 h"
    assert tiempo_transcurrido("2026-10-12 11:00:00", ahora) == "hace 1 día"
    assert tiempo_transcurrido("2026-10-10 12:00:00", ahora) == "hace 3 días"
    assert tiempo_transcurrido("2026-09-01 12:00:00", ahora) == "el 01/09/2026"
    assert tiempo_transcurrido("basura", ahora) == ""
    assert fecha_corta("2026-10-06 09:15:00") == "06/10/2026 09:15"
    assert fecha_corta("2026-10-06 09:15:00", con_hora=False) == "06/10/2026"
    assert fecha_corta("sin fecha") == "sin fecha"
    assert fecha_larga(ahora) == "Martes 13 de octubre de 2026"


def test_ruta_cortable_no_cambia_el_texto_visible():
    from app.ui.widgets import ruta_cortable
    r = ruta_cortable(r"C:\Users\x\AppData")
    assert r.replace("\u200b", "") == r"C:\Users\x\AppData" and r.count("\u200b") == 3


def test_dividir_respuesta_ia():
    from app.ui.diagnosis_dialog import dividir_respuesta_ia
    texto = ("**Hechos:** La CPU marca 87 °C.\nEl ventilador suena.\n"
             "## Inferencias\nPosible polvo en el disipador.\n"
             "Recomendación: limpiar y cambiar la pasta térmica.")
    partes = dividir_respuesta_ia(texto)
    assert partes == {"Hechos": "La CPU marca 87 °C.\nEl ventilador suena.",
                      "Inferencias": "Posible polvo en el disipador.",
                      "Recomendación": "limpiar y cambiar la pasta térmica."}
    assert dividir_respuesta_ia("Texto normal sin secciones.") is None
    assert dividir_respuesta_ia("Hechos: algo\nInferencias: otra cosa") is None  # falta una sección


def test_estado_de_categorias_y_lo_no_leido():
    from app.ui.pages.escaneo import no_leido, texto_estado
    s = run_scan(env=_env(psutil=_psutil(bateria=False)))
    disp = s["availability"]
    comp = {c["name"]: c for c in s["components"]}
    assert texto_estado(comp["Batería"], disp["battery"]) == "No aplica"
    assert texto_estado(comp["CPU"], disp["cpu"]) == "Detectado"
    assert texto_estado(comp["GPU"], disp["graphics"]) == "Parcial"
    assert texto_estado({"status": "warn"}, None) == "Parcial"  # durante la lectura
    filas = no_leido(s)
    assert ("Gráficos", "Memoria gráfica (WMI no la informa o supera los 4 GB)", "No disponible") in filas
    assert not any(cat == "Batería" for cat, _d, _m in filas)  # "no aplica" no es un faltante
    assert no_leido({"components": []}) == []  # archivo de versión 1


def test_datos_equipo_solo_con_datos_leidos():
    from app.ui.pages.recepcion import datos_equipo
    d = dict(datos_equipo(_scan()))
    assert d["Procesador"].startswith("Intel(R) Core")
    assert "2 módulo(s)" in d["Memoria"] and "DDR4" in d["Memoria"]
    assert d["Origen"] == "Escaneo de este equipo"
    viejo = dict(datos_equipo({"summary": {"cpu": "i5"}, "components": []}))
    assert viejo["Procesador"] == "i5" and viejo["Memoria"] == "No disponible"
    assert viejo["Origen"] == "No indicado"


# ---------------- datos ----------------
def test_reingreso_en_la_lista_de_casos(repo):
    a = repo.register_intake("Ana", "1", "SN-1", "PC", "Lento")
    b = repo.register_intake("Ana", "1", "SN-1", "PC", "No enciende")
    filas = {r["code"]: r for r in repo.list_cases()}
    assert not filas[a]["reingreso"] and filas[b]["reingreso"]
    assert repo.get_case(b)["reingreso"]


def test_equipos_busca_por_documento_marca_y_varias_palabras(repo):
    hw = HardwareRepository(repo)
    c1 = repo.register_intake("Luis Peña", "987", "SN-1", "Laptop", "Lento")
    hw.save_capture(c1, _scan())
    c2 = repo.register_intake("Ana Ríos", "999", "SN-2", "PC armada", "Lento")
    ClientsRepository(repo).set_doc_for_case(c2, "10456789")
    repo.update_case_status(c2, "Listo")
    er = EquipmentRepository(repo)
    assert [r["serial"] for r in er.list_equipment("10456789")] == ["SN-2"]
    assert [r["serial"] for r in er.list_equipment("HP")] == ["SN-1"]  # marca de la captura
    assert [r["serial"] for r in er.list_equipment("luis laptop")] == ["SN-1"]
    assert er.list_equipment("luis armada") == []
    assert er.list_equipment("100%") == []  # comodines escapados
    assert er.list_equipment("")[0]["ultimo_status"] == "Listo"


# ---------------- interfaz ----------------
def test_buscador_global_encuentra_por_documento(repo):
    from app.ui.main_window import MainWindow
    code = repo.register_intake("Ana Ríos", "999", "SN-2", "PC", "Lento")
    ClientsRepository(repo).set_doc_for_case(code, "10456789")
    win = MainWindow(repo, "TEC-001")
    win._al_buscar("10456789")
    assert list(win._hits.values()) == [code]
    win._al_buscar("x")
    assert win._hits == {}
    win._skip_backup = True
    win.close()


def test_cerrar_sesion_marca_la_salida(repo):
    from app.ui.main_window import MainWindow
    win = MainWindow(repo, "TEC-001")
    cerradas = []
    win.closed.connect(lambda: cerradas.append(True))
    win.show()
    win.cerrar_sesion()
    assert win.logout_requested and cerradas == [True] and not win.isVisible()


def test_inicio_muestra_contadores_y_reingreso(repo):
    from app.ui.pages.inicio import InicioPage
    repo.register_intake("Ana", "1", "SN-1", "PC", "Lento")
    repo.register_intake("Ana", "1", "SN-1", "PC", "No enciende")
    page = InicioPage(repo)
    assert "2 caso(s) activo(s)" in page.subtitulo.text()
    textos = [w.text() for w in page.findChildren(type(page.subtitulo))]
    assert any(t.startswith("Reingreso") for t in textos)


def test_caso_actualiza_las_etapas(repo):
    from app.ui.case_dialog import CaseDialog
    code = repo.register_intake("Ana", "1", "SN-1", "PC", "Lento")
    dlg = CaseDialog(repo, code)
    assert dlg.ok.isHidden()
    dlg.estado.setCurrentText("Listo")
    dlg._guardar_estado()
    assert repo.get_case(code)["status"] == "Listo"
    assert "Listo" in dlg.etapas.accessibleName() and dlg.ok.text() == "Estado actualizado."
    dlg.done(0)


def test_escaneo_muestra_estados_escritos(qapp):
    from app.ui.pages.escaneo import EscaneoPage
    page = EscaneoPage()
    page.data = _scan(psutil=_psutil(bateria=False))
    page._pintar_resultado()
    estados = [f.chip.text() for f in page.filas]
    assert len(estados) == 11 and "No aplica" in estados and "Parcial" in estados
    assert "Gráficos" in page.no_leido_lbl.text()


def test_conocimiento_muestra_detalle_e_implicacion(qapp):
    from app.reports.cliente import IMPLICACIONES
    from app.ui.pages.conocimiento import ConocimientoPage
    page = ConocimientoPage()
    assert page.lista.count() == len(page.rules)
    page.lista.setCurrentRow(0)
    textos = " ".join(w.text() for w in page.findChildren(type(page.cuenta)))
    assert IMPLICACIONES[page._visibles[0]["id"]] in textos
    page.buscar.setText("zzzz")
    assert page.lista.count() == 0 and "0 de" in page.cuenta.text()


def test_barra_porcentaje(qapp):
    from app.ui.widgets import BarraPorcentaje
    b = BarraPorcentaje(83.4)
    assert b.texto() == "83 %"
    b.set_valor(None, texto_alt="Sin medición")
    assert b.texto() == "Sin medición" and b.valor() is None
    b.grab()  # se pinta sin errores con y sin valor
