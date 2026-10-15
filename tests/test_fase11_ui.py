"""Fase 11 (interfaz): pantalla Salud del equipo, detalle, prueba de rendimiento y su
integración en Equipos, Recepción, Caso, Diagnóstico y Escanear."""
import copy

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.ai.ollama_client import OllamaError
from app.db.database import Database
from app.db.hardware_repo import HardwareRepository
from app.db.health_repo import HealthRepository
from app.db.notes_repo import NotesRepository
from app.db.repo import Repository
from app.hardware.inventory import identifiers_from_scan
from app.hardware.scanner import run_scan
from tests.test_fase10b_hardware import _env


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def entorno(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    def sin_ollama(*args, **kwargs):
        raise OllamaError("sin ollama")

    monkeypatch.setattr("app.ai.config.list_models", sin_ollama)
    monkeypatch.setattr("app.ui.pages.ia_local.list_models", sin_ollama)


@pytest.fixture
def repo(tmp_path, qapp):
    db = Database(tmp_path / "ui.db")
    r = Repository(db)
    r.set_setting("auto_backup", "0")
    r.session_tech = "TEC-001"
    yield r
    db.close()


def _scan(**kw):
    s = run_scan(env=_env(**kw))
    s["provenance"] = {"how": "local_scan", "file": None}
    return s


def _caso_con_captura(repo, full=None, serie="SN-1"):
    code = repo.register_intake("Luis Paredes", "987", serie, "Laptop HP", "Se calienta")
    s = _scan()
    if full:
        s = copy.deepcopy(s)
        s["inventory"]["battery"]["full_mwh"] = full
    HardwareRepository(repo).save_capture(code, s)
    return code


class _LectorFalso:
    def __init__(self, temp=60.0):
        self.temp = temp

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *e):
        return False

    def leer(self):
        return (self.temp, "LibreHardwareMonitor") if self.temp is not None else (None, None)


def test_navegacion_incluye_salud(repo):
    from app.ui.main_window import IDX_SALUD, SECCIONES, MainWindow
    assert SECCIONES[IDX_SALUD] == "Salud del equipo" and len(SECCIONES) == 11
    code = _caso_con_captura(repo)
    win = MainWindow(repo, "TEC-001")
    win.abrir_salud(code)
    assert win.pages.currentIndex() == IDX_SALUD and win.salud.code == code
    win.sidebar.setCurrentRow(0)
    win.sidebar.setCurrentRow(IDX_SALUD)  # volver por la barra lateral conserva el caso
    assert win.salud.code == code
    win._skip_backup = True
    win.close()


def test_pantalla_salud_muestra_resumen_y_tabla(repo):
    from app.ui.pages.salud import SaludPage
    code = _caso_con_captura(repo)
    page = SaludPage(repo)
    page.show_case(code)
    assert page.indice_lbl.text() == "85 %" and page.contadores["Atención"].text() == "1"
    assert page.tabla.rowCount() == len(page.resultado["componentes"])
    assert not page.alerta.isHidden() and "Advertencia" in page.alerta_txt.text()
    assert "Batería" in page.incluidos_lbl.text()
    assert code in page.subtitulo.text() and page.b_bench.isEnabled() and page.b_inv.isEnabled()
    assert HealthRepository(repo).latest_index_for_case(code) == 85.0


def test_salud_sin_caso_sin_captura_y_captura_suelta(repo):
    from app.ui.pages.salud import SaludPage
    page = SaludPage(repo)
    assert not page.b_bench.isEnabled() and "requiere un caso" in page.motivo_bench.text()
    code = repo.register_intake("Ana", "1", "SN-9", "PC", "Lento")
    page.show_case(code)
    assert page.p_tabla.isHidden() and "no tiene captura" in page.aviso.text()
    # sin captura los botones siguen activos: al pulsarlos ofrecen escanear este equipo
    assert page.b_bench.isEnabled() and page.b_inv.isEnabled() and "escanear" in page.motivo_bench.text()
    page.show_scan(_scan())
    assert not page.p_tabla.isHidden() and "no se guarda" in page.subtitulo.text()
    assert repo.c.execute("SELECT COUNT(*) FROM health_results").fetchone()[0] == 0


def test_selector_de_casos(repo):
    from app.ui.pages.salud import SaludPage
    c1 = _caso_con_captura(repo)
    c2 = _caso_con_captura(repo, serie="SN-2")
    page = SaludPage(repo)
    page.refresh()
    assert page.combo.count() == 2 and page.code == c2  # el más reciente
    page.combo.setCurrentIndex(page.combo.findData(c1))
    page._elegir_combo()
    assert page.code == c1


def test_detalle_componente_evolucion_nota_e_inclusion(repo):
    from app.ui.pages.salud import SaludPage
    _caso_con_captura(repo, full=45000)  # visita anterior del mismo equipo
    c2 = _caso_con_captura(repo, full=40000)
    page = SaludPage(repo)
    page.show_case(c2)
    dlg = page.abrir_detalle("bateria", ejecutar=False)
    assert "90 %" in dlg.variacion.text() and "80 %" in dlg.variacion.text() and "−10 puntos" in dlg.variacion.text()
    dlg._incluir()
    assert "Incluido" in dlg.msg.text()
    assert HealthRepository(repo).included_for_case(c2)[0]["clave"] == "bateria"
    dlg._agregar_nota("Batería al 80 %: ofrecer reemplazo")
    notas = NotesRepository(repo).for_case(c2)
    assert notas[-1]["kind"] == "observacion" and notas[-1]["author"] == "TEC-001"
    sin_caso = SaludPage(repo)
    sin_caso.show_scan(_scan())
    d2 = sin_caso.abrir_detalle("bateria", ejecutar=False)
    assert not d2.b_incluir.isEnabled() and not d2.b_nota.isEnabled()


def test_prueba_solo_en_el_mismo_equipo(repo):
    from app.ui.pages.salud import SaludPage, misma_maquina
    code = _caso_con_captura(repo)
    page = SaludPage(repo)
    page.show_case(code)
    propios = identifiers_from_scan(page.datos["captura"]["payload"])
    page._ids_locales = lambda: propios
    assert page.comprobar_equipo() == (True, "")
    page._ids_locales = lambda: [("uuid", "OTRO"), ("serial", "OTRA")]
    ok, motivo = page.comprobar_equipo()
    assert not ok and "otro equipo" in motivo
    assert misma_maquina({"inventory": {}}, propios) is None


def test_dialogo_de_prueba_guarda_y_actualiza_la_salud(repo, monkeypatch):
    from app.ui.benchmark_dialog import BenchmarkDialog
    code = _caso_con_captura(repo)
    hr = HealthRepository(repo)
    cap = hr.evaluate_case(code)["captura"]
    falso = {"version": 1, "fecha": "2026-10-14T10:00:00", "condiciones": {"cargador": True},
             "cpu": {"ops_s": 5000.0, "sostenido_pct": 95.0, "duracion_s": 2, "temp_max": 70.0,
                     "temp_fuente": "LibreHardwareMonitor", "detenido_por_temp": False, "cancelado": False},
             "discos": [{"index": 0, "lectura_mb_s": 450.0, "duracion_s": 1, "estado": "ok", "motivo": ""},
                        {"index": 1, "lectura_mb_s": None, "estado": "no_autorizado",
                         "motivo": "requiere ejecutar el programa como administrador"}],
             "cancelado": False}
    dlg = BenchmarkDialog(repo, code, cap, lector=_LectorFalso(), condiciones={"cargador": True})
    assert dlg.b_iniciar.isEnabled() and len(dlg.pasos) == 3  # CPU + 2 discos internos
    dlg._on_fin(falso)
    assert dlg.saved and "guardada" in dlg.estado.text()
    r = hr.evaluate_case(code)["resultado"]
    assert r["indice"]["valor"] == round((85.0 + 90.0) / 2, 1)
    cancelada = BenchmarkDialog(repo, code, cap, lector=_LectorFalso(), condiciones={})
    cancelada._on_fin({**falso, "cancelado": True})
    assert not cancelada.saved and "no se guardó" in cancelada.estado.text()


def test_prueba_sin_temperatura_exige_confirmacion(repo):
    from app.ui.benchmark_dialog import BenchmarkDialog
    code = _caso_con_captura(repo)
    cap = HealthRepository(repo).evaluate_case(code)["captura"]
    dlg = BenchmarkDialog(repo, code, cap, lector=_LectorFalso(temp=None), condiciones={})
    assert not dlg.b_iniciar.isEnabled()
    dlg.chk_sin_temp.setChecked(True)
    assert dlg.b_iniciar.isEnabled()


def test_dialogo_de_prueba_ejecuta_de_verdad_en_poco_tiempo(repo, monkeypatch):
    """Ejecución real del hilo con duraciones cortas y sin discos (la lectura física requiere administrador)."""
    from PySide6.QtCore import QEventLoop, QTimer

    from app.ui.benchmark_dialog import BenchmarkDialog
    code = _caso_con_captura(repo)
    cap = HealthRepository(repo).evaluate_case(code)["captura"]
    dlg = BenchmarkDialog(repo, code, cap, duracion_cpu=2, duracion_disco=1, procesos=1,
                          lector=_LectorFalso(), condiciones={"cargador": True})
    dlg.discos = []
    bucle = QEventLoop()
    dlg.worker = None
    dlg.iniciar()
    dlg.worker.finished.connect(bucle.quit)
    QTimer.singleShot(30000, bucle.quit)
    bucle.exec()
    QApplication.processEvents()
    assert dlg.saved and dlg.resultado["cpu"]["ops_s"] > 0
    dlg.done(0)


def test_equipos_muestra_rendimiento_y_accion_salud(repo):
    from app.ui.pages.equipos import COL_RENDIMIENTO, EquiposPage
    code = _caso_con_captura(repo)
    HealthRepository(repo).evaluate_case(code)
    repo.register_intake("Ana", "1", "SN-2", "PC", "Lento")
    page = EquiposPage(repo)
    emitidos = []
    page.ver_salud.connect(emitidos.append)
    from app.ui.widgets import BarraPorcentaje
    textos = sorted(page.tabla.cellWidget(i, COL_RENDIMIENTO).findChild(BarraPorcentaje).texto()
                    for i in range(page.tabla.rowCount()))
    assert textos == ["85 %", "Sin medición"]
    fila = next(i for i, r in enumerate(page._filas) if r["serial"] == "SN-1")
    acciones = page.tabla.cellWidget(fila, 6).layout().itemAt(0).widget()
    acciones.click()
    assert emitidos == [code]


def test_recepcion_evalua_y_avisa_indice_anterior(repo):
    from app.ui.pages.recepcion import RecepcionPage
    page = RecepcionPage(repo)
    page.set_hardware(_scan())
    page.cliente.setText("Luis")
    page.equipo.setText("Laptop")
    page.serie.setText("SN-1")
    page.problema.setText("Lento")
    page._guardar()
    assert "Aviso" not in page.ok.text()
    assert HealthRepository(repo).latest_index_for_case("C-001") == 85.0
    page.serie.setText("SN-1")
    assert "Índice de salud en la visita C-001" in page.alert_text.text() and "85 %" in page.alert_text.text()


def test_caso_muestra_salud_y_diagnostico_incluye_hallazgos(repo):
    from app.ui.case_dialog import CaseDialog
    from app.ui.diagnosis_dialog import DiagnosisDialog
    code = _caso_con_captura(repo)
    dlg = CaseDialog(repo, code)
    textos = " ".join(w.text() for w in dlg.findChildren(type(dlg.ok)))
    assert "85 %" in textos and "Lo más importante" in textos
    dlg.done(0)
    HealthRepository(repo).include_in_diagnosis(code, "disco:1", "Salud del equipo — disco con advertencia")
    d = DiagnosisDialog(repo, code)
    assert "1 hallazgo(s) incluido(s)" in d.datos_usados.text()
    d._guardar()
    assert repo.get_diagnosis(code)["result"]["health_findings"] == ["Salud del equipo — disco con advertencia"]
    assert repo.get_diagnosis(code)["result"]["causes"] == d.result["causes"]  # las reglas no cambian
    d.done(0)


def test_escaneo_ofrece_ver_salud(qapp):
    from app.ui.pages.escaneo import EscaneoPage
    page = EscaneoPage()
    assert not page.b_salud.isEnabled()
    emitidos = []
    page.ver_salud.connect(emitidos.append)
    page.data = _scan()
    page._botones_resultado(True)
    assert page.b_salud.isEnabled()
    page._ver_salud()
    assert emitidos and emitidos[0]["scanned_at"] == page.data["scanned_at"]  # la señal entrega una copia


def test_configuracion_muestra_referencias_y_crea_copia(repo, tmp_path):
    from app.health.references import ruta_taller
    from app.ui.pages.configuracion import ConfiguracionPage
    page = ConfiguracionPage(repo, "TEC-001")
    assert page.b_copia_refs.isEnabled()
    page._copiar_referencias()
    assert ruta_taller().is_file() and not page.b_copia_refs.isEnabled()
    page._copiar_referencias()
    assert "ya existe" in page.msg_refs.text()


# ---------------- caso sin captura: escanear este equipo desde Salud ----------------
def _pagina_sin_captura(repo, serie="5CD1234ABC"):
    from app.ui.pages.salud import SaludPage
    code = repo.register_intake("Luis", "1", serie, "Laptop HP", "Lento")
    page = SaludPage(repo)
    page.show_case(code)
    locales = identifiers_from_scan(_scan())  # "este equipo" es el del escaneo simulado
    page._ids_locales = lambda: locales
    page._escanear = _scan
    mensajes = []
    page._informar = lambda titulo, texto: mensajes.append(texto)
    page._preguntar = lambda titulo, texto: True
    return code, page, mensajes


def test_inventario_escanea_y_guarda_si_el_caso_es_este_equipo(repo):
    code, page, mensajes = _pagina_sin_captura(repo)
    assert page.caso_es_este_equipo() == (True, "")
    dlg = page._ver_inventario(ejecutar=False)
    assert dlg is not None and dlg.arbol.topLevelItemCount() == 11 and not mensajes
    assert len(HardwareRepository(repo).captures_for_case(code)) == 1
    assert page.indice_lbl.text() == "85 %" and not page.p_tabla.isHidden()


def test_prueba_escanea_primero_y_luego_abre_el_dialogo(repo, monkeypatch):
    code, page, _m = _pagina_sin_captura(repo)
    abiertos = []

    class _Dialogo:
        def __init__(self, repo_, code_, captura, parent=None):
            abiertos.append((code_, captura["id"]))
            self.saved = False

        def exec(self):
            return 0

    monkeypatch.setattr("app.ui.benchmark_dialog.BenchmarkDialog", _Dialogo)
    page._prueba()
    assert abiertos and abiertos[0][0] == code


def test_caso_de_otro_equipo_explica_como_obtener_la_captura(repo):
    code, page, mensajes = _pagina_sin_captura(repo, serie="OTRA-SERIE")
    assert page.caso_es_este_equipo() == (False, "")
    assert page._ver_inventario(ejecutar=False) is None
    assert "no es el del caso" in mensajes[0] and "importe su archivo .diag" in mensajes[0]
    assert HardwareRepository(repo).captures_for_case(code) == []


def test_si_el_tecnico_no_acepta_no_se_escanea(repo):
    code, page, _m = _pagina_sin_captura(repo)
    escaneos = []
    page._escanear = lambda: escaneos.append(1) or _scan()
    page._preguntar = lambda titulo, texto: False
    assert page._ver_inventario(ejecutar=False) is None and not escaneos
    assert HardwareRepository(repo).captures_for_case(code) == []
