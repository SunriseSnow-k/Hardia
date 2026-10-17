"""Fase 11: salud del equipo frente a fábrica (lógica pura, repositorio, prueba de rendimiento y PDF)."""
import copy
import json
import os
from types import SimpleNamespace as NS

import pytest

from app.db.database import Database
from app.db.hardware_repo import HardwareRepository
from app.db.health_repo import HealthRepository
from app.db.repo import Repository
from app.hardware.inventory import inventory_rows
from app.hardware.scanner import read_cpu_temperature, run_scan
from app.health import ATENCION, BUENO, REVISAR, SIN_REF, componente, estado_por_pct, evaluate, load_references
from app.health import benchmark as bm
from app.health.evaluate import estado_por_margen, peor
from app.health.references import find_cpu, find_disk_type
from app.paths import VAR_DATOS
from tests.test_fase10b_hardware import _env, _psutil, _wmi_basico

GB = 1024 ** 3


@pytest.fixture
def refs():
    return load_references()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv(VAR_DATOS, str(tmp_path / "appdata"))
    db = Database(tmp_path / "t.db")
    yield Repository(db)
    db.close()


def _scan(**kw):
    s = run_scan(env=_env(**kw))
    s["provenance"] = {"how": "local_scan", "file": None}
    return s


def _con_modulos(scan, configurada, nominal):
    s = copy.deepcopy(scan)
    for m in s["inventory"]["memory"]["modules"]:
        m["configured_mhz"], m["nominal_mhz"] = configurada, nominal
    return s


def _con_bateria(scan, full, design=50000):
    s = copy.deepcopy(scan)
    s["inventory"]["battery"].update(full_mwh=full, design_mwh=design)
    return s


# ---------------- escáner (campos opcionales nuevos) ----------------
def test_escaner_guarda_velocidad_nominal_y_configurada_y_rpm():
    base = _wmi_basico()
    from tests.test_fase10b_hardware import NS as N
    base.Win32_PhysicalMemory = lambda: [N(Capacity=8 * GB, Speed=3200, ConfiguredClockSpeed=2666, SMBIOSMemoryType=26)]
    s = run_scan(env=_env(base=base, wmi_extra={r"root\Microsoft\Windows\Storage": NS(MSFT_PhysicalDisk=lambda: [
        NS(DeviceId="0", MediaType=4, BusType=11, HealthStatus=0, SpindleSpeed=0),
        NS(DeviceId="1", MediaType=3, BusType=11, HealthStatus=0, SpindleSpeed=5400)])}))
    m = s["inventory"]["memory"]["modules"][0]
    assert (m["nominal_mhz"], m["configured_mhz"], m["speed_mhz"]) == (3200, 2666, 2666)
    discos = {d["index"]: d for d in s["inventory"]["storage"]["physical"]}
    assert discos[0]["rpm"] is None and discos[1]["rpm"] == 5400
    textos = " ".join(f["value"] for f in inventory_rows(s))
    assert "3200 MHz (configurada 2666 MHz)" in textos and "5400 rpm" in textos
    assert s["version"] == 2  # el formato .diag no cambia de versión


def test_lectura_de_temperatura_para_la_prueba():
    assert read_cpu_temperature(_env()) == (71.0, "LibreHardwareMonitor")
    sin = _env(wmi_extra={r"root\LibreHardwareMonitor": RuntimeError("Invalid namespace"),
                          r"root\wmi": NS(MSAcpi_ThermalZoneTemperature=lambda: [])})
    assert read_cpu_temperature(sin) == (None, None)


# ---------------- referencias ----------------
def test_referencias_documentadas_y_busqueda(refs):
    assert all(c.get("fuente") and c.get("tjmax_c") for c in refs["cpus"])
    assert all(d.get("fuente") and d.get("lectura_mb_s") for d in refs["discos_por_tipo"])
    assert refs["cpu_puntajes"]["modelos"] == []  # no hay puntajes públicos en la unidad de esta prueba
    assert find_cpu(refs, "Intel(R) Core(TM) i5-1135G7 @ 2.40GHz")["tjmax_c"] == 100
    assert find_cpu(refs, "Intel(R) Core(TM) i5-1135") is None
    assert find_cpu(refs, "AMD Ryzen 5 5500U with Radeon Graphics")["tjmax_c"] == 105
    assert find_disk_type(refs, {"media": "SSD", "bus": "SATA"})["lectura_mb_s"] == 500
    assert find_disk_type(refs, {"media": "SSD", "bus": "NVMe"}) is None
    assert find_disk_type(refs, {"media": "HDD", "bus": "SATA"}) is None  # sin rpm no hay referencia
    assert find_disk_type(refs, {"media": "HDD", "rpm": 5400})["lectura_mb_s"] == 100


def test_copia_del_taller_tiene_prioridad_y_si_esta_danada_se_usa_la_del_programa(tmp_path, monkeypatch):
    monkeypatch.setenv(VAR_DATOS, str(tmp_path))
    destino = tmp_path / "SistemaDiagnostico" / "references.json"
    destino.parent.mkdir(parents=True)
    destino.write_text(json.dumps({"cpus": [{"modelo": "X-1", "tjmax_c": 90, "fuente": "taller"}]}), encoding="utf-8")
    assert load_references()["cpus"][0]["modelo"] == "X-1"
    destino.write_text("{dañado", encoding="utf-8")
    assert load_references()["cpus"][0]["modelo"] == "i5-8250U"


# ---------------- cálculo y umbrales ----------------
def test_umbrales():
    assert estado_por_pct(80) == BUENO and estado_por_pct(79.9) == REVISAR
    assert estado_por_pct(60) == REVISAR and estado_por_pct(59.9) == ATENCION
    assert estado_por_pct(None) == SIN_REF
    assert estado_por_margen(20) == BUENO and estado_por_margen(19) == REVISAR and estado_por_margen(9) == ATENCION
    assert peor(BUENO, SIN_REF, REVISAR) == REVISAR and peor(SIN_REF) == SIN_REF


def test_bateria_calculo_y_estados(refs):
    s = _scan()
    for full, estado in ((42500, BUENO), (35000, REVISAR), (25000, ATENCION)):
        c = componente(evaluate(_con_bateria(s, full), refs), "bateria")
        assert c["estado"] == estado and c["pct"] == round(100 * full / 50000, 1)
    c = componente(evaluate(_con_bateria(s, 42500), refs), "bateria")
    assert c["calculo"] == "42 500 mWh ÷ 50 000 mWh = 85 %" and c["medido"]["valor"] == "42 500 mWh"
    assert componente(evaluate(_scan(psutil=_psutil(bateria=False)), refs), "bateria") is None  # no aplica


def test_memoria_sin_referencia_en_capturas_sin_velocidades(refs):
    s = _scan()  # los módulos simulados no tienen ambas velocidades a la vez
    c = componente(evaluate(s, refs), "memoria")
    assert c["estado"] == SIN_REF and c["pct"] is None and "velocidad nominal" in c["alt"]
    viejo = copy.deepcopy(s)
    for m in viejo["inventory"]["memory"]["modules"]:  # captura anterior a los campos nuevos
        m.pop("nominal_mhz", None)
        m.pop("configured_mhz", None)
    assert componente(evaluate(viejo, refs), "memoria")["estado"] == SIN_REF
    c = componente(evaluate(_con_modulos(s, 2666, 3200), refs), "memoria")
    assert c["pct"] == 83.3 and c["estado"] == BUENO and c["fabrica"]["valor"] == "3200 MHz"


def test_discos_salud_y_lectura(refs):
    r = evaluate(_scan(), refs)
    ssd, hdd = componente(r, "disco:0"), componente(r, "disco:1")
    assert ssd["estado"] == BUENO and ssd["pct"] is None and "prueba de rendimiento" in ssd["alt"]
    assert hdd["estado"] == ATENCION  # Windows Storage: Advertencia
    assert any(k == "Vida útil restante" and v.startswith("No disponible") for k, v in hdd["windows"])
    bench = {"discos": [{"index": 0, "lectura_mb_s": 450.0}, {"index": 1, "lectura_mb_s": 95.0}]}
    r2 = evaluate(_scan(), refs, bench)
    ssd = componente(r2, "disco:0")
    assert ssd["pct"] == 90.0 and ssd["estado"] == BUENO and "450 MB/s ÷ 500 MB/s" in ssd["calculo"]
    hdd = componente(r2, "disco:1")
    assert hdd["pct"] is None and hdd["alt"] == "Sin referencia para este tipo de unidad"
    lento = evaluate(_scan(), refs, {"discos": [{"index": 0, "lectura_mb_s": 250.0}]})
    assert componente(lento, "disco:0")["estado"] == ATENCION
    sin_permiso = evaluate(_scan(), refs, {"discos": [{"index": 0, "lectura_mb_s": None,
                                                        "motivo": "requiere ejecutar el programa como administrador"}]})
    assert "administrador" in componente(sin_permiso, "disco:0")["alt"]


def test_refrigeracion_margen_fuente_y_corte(refs):
    c = componente(evaluate(_scan(), refs), "refrigeracion")
    assert c["pct"] is None and c["alt"] == "Margen de 29 °C" and c["estado"] == BUENO
    assert "aproximada" not in c["medido"]["nota"]
    acpi = _scan(wmi_extra={r"root\LibreHardwareMonitor": RuntimeError("Invalid namespace")})
    c = componente(evaluate(acpi, refs), "refrigeracion")
    assert "aproximada" in c["medido"]["nota"]
    caliente = evaluate(_scan(), refs, {"cpu": {"temp_max": 95.0, "temp_fuente": "LibreHardwareMonitor",
                                                  "detenido_por_temp": True, "ops_s": 1000}})
    c = componente(caliente, "refrigeracion")
    assert c["estado"] == ATENCION and "durante la prueba" in c["medido"]["nota"]
    otro = copy.deepcopy(_scan())
    otro["inventory"]["cpu"]["name"] = "CPU desconocida 9000"
    assert componente(evaluate(otro, refs), "refrigeracion")["alt"].startswith("Sin límite de fábrica")


def test_procesador_sin_referencia_y_con_referencia_del_taller(refs):
    s = _scan()
    assert componente(evaluate(s, refs), "procesador")["alt"].startswith("Sin medición")
    bench = {"cpu": {"ops_s": 8000.0, "sostenido_pct": 92.0, "duracion_s": 60}}
    c = componente(evaluate(s, refs, bench), "procesador")
    assert c["estado"] == SIN_REF and c["medido"]["valor"] == "8 000 op/s" and "92 %" in c["medido"]["nota"]
    con_ref = copy.deepcopy(refs)
    con_ref["cpu_puntajes"]["modelos"] = [{"modelo": "i5-1135G7", "ops_s": 10000, "fuente": "taller"}]
    c = componente(evaluate(s, con_ref, bench), "procesador")
    assert c["pct"] == 80.0 and c["estado"] == BUENO


def test_indice_con_datos_parciales_y_hallazgo(refs):
    r = evaluate(_scan(), refs)
    assert r["indice"]["valor"] == 85.0 and r["indice"]["incluidos"] == ["Batería"]
    assert r["hallazgo"]["clave"] == "disco:1"
    assert sum(r["conteo"].values()) == len(r["componentes"])
    r2 = evaluate(_con_modulos(_con_bateria(_scan(), 25000), 2666, 3200), refs)
    assert r2["indice"]["valor"] == round((50.0 + 83.3) / 2, 1) and len(r2["indice"]["incluidos"]) == 2
    sin_pct = copy.deepcopy(_scan(psutil=_psutil(bateria=False)))
    r3 = evaluate(sin_pct, refs)
    assert r3["indice"]["valor"] is None and r3["indice"]["estado"] == SIN_REF


def test_captura_antigua_v1_sin_inventario(refs):
    v1 = {"format": "SD-DIAG", "version": 1, "summary": {"cpu": "i5"}, "metrics": {"cpu_temp": 80},
          "components": [{"name": "CPU", "detail": "i5", "status": "ok"}]}
    r = evaluate(v1, refs)
    assert r["componentes"] == [] and r["indice"]["valor"] is None and "versión anterior" in r["aviso"]
    assert "no tiene captura" in evaluate(None, refs)["aviso"]


# ---------------- repositorio ----------------
def test_migracion_idempotente_y_resultados(repo, refs):
    HealthRepository(repo)
    HealthRepository(repo)  # segunda vez: sin errores ni duplicados
    tablas = {f[0] for f in repo.c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"health_results", "health_benchmarks", "health_diag_items"} <= tablas
    hr = HealthRepository(repo)
    code = repo.register_intake("Luis", "1", "SN-1", "Laptop", "Lento")
    assert hr.evaluate_case(code)["result_id"] is None  # sin captura no se guarda nada
    HardwareRepository(repo).save_capture(code, _scan())
    a = hr.evaluate_case(code)
    b = hr.evaluate_case(code)
    assert a["result_id"] == b["result_id"]  # sin cambios no se duplica
    assert repo.c.execute("SELECT COUNT(*) FROM health_results").fetchone()[0] == 1
    assert hr.latest_index_for_case(code) == 85.0
    eq = repo.c.execute("SELECT equipment_id FROM cases WHERE code=?", (code,)).fetchone()[0]
    assert hr.latest_index_by_equipment()[eq]["indice"] == 85.0
    cap = a["captura"]
    hr.save_benchmark(code, cap["id"], {"cpu": {"ops_s": 5000.0}, "discos": [{"index": 0, "lectura_mb_s": 450.0}]})
    c = hr.evaluate_case(code)
    assert c["benchmark_id"] is not None and c["result_id"] != a["result_id"]
    assert c["resultado"]["indice"]["valor"] == round((85.0 + 90.0) / 2, 1)


def test_historial_por_equipo_e_inclusion_en_diagnostico(repo, refs):
    hr = HealthRepository(repo)
    hw = HardwareRepository(repo)
    c1 = repo.register_intake("Luis", "1", "SN-1", "Laptop", "Lento")
    hw.save_capture(c1, _con_bateria(_scan(), 45000))
    c2 = repo.register_intake("Luis", "1", "SN-1", "Laptop", "Lento")
    hw.save_capture(c2, _con_bateria(_scan(), 40000))
    eq = repo.c.execute("SELECT equipment_id FROM cases WHERE code=?", (c1,)).fetchone()[0]
    hist = hr.history_for_equipment(eq, refs)
    assert [componente(h["resultado"], "bateria")["pct"] for h in hist] == [90.0, 80.0]
    assert hr.include_in_diagnosis(c2, "bateria", "Batería al 80 %") is True
    assert hr.include_in_diagnosis(c2, "bateria", "Batería al 80 % (revisado)") is False
    assert [i["texto"] for i in hr.included_for_case(c2)] == ["Batería al 80 % (revisado)"]
    with pytest.raises(ValueError):
        hr.include_in_diagnosis(c2, "bateria", "  ")
    with pytest.raises(ValueError):
        hr.include_in_diagnosis("C-999", "bateria", "x")


# ---------------- prueba de rendimiento ----------------
def test_prueba_cpu_corta_y_corte_por_temperatura():
    r = bm.prueba_cpu(2, procesos=1, leer_temp=lambda: (50.0, "simulada"))
    assert r["ops_s"] > 0 and not r["detenido_por_temp"] and r["temp_max"] == 50.0 and len(r["muestras"]) >= 2
    caliente = bm.prueba_cpu(30, procesos=1, leer_temp=lambda: (96.0, "simulada"))
    assert caliente["detenido_por_temp"] and caliente["duracion_s"] < 5


def test_prueba_cpu_se_cancela():
    llamadas = []

    def cancelar():
        llamadas.append(1)
        return len(llamadas) > 2

    r = bm.prueba_cpu(30, procesos=1, cancelado=cancelar)
    assert r["cancelado"] and r["duracion_s"] < 10


@pytest.mark.skipif(os.name != "nt", reason="la lectura sin caché usa la API de Windows")
def test_lectura_sin_cache_es_solo_lectura(tmp_path):
    archivo = tmp_path / "bloque.bin"
    datos = os.urandom(4 * 1024 * 1024)
    archivo.write_bytes(datos)
    antes = archivo.stat().st_mtime_ns
    r = bm.lectura_disco(None, 5, ruta=str(archivo))
    assert r["estado"] == "ok" and r["bytes"] == len(datos) and r["lectura_mb_s"] > 0
    assert archivo.read_bytes() == datos and archivo.stat().st_mtime_ns == antes
    falta = bm.lectura_disco(None, 1, ruta=str(tmp_path / "no_existe.bin"))
    assert falta["estado"] == "fallo" and falta["lectura_mb_s"] is None


def test_condiciones_y_texto():
    proc = [NS(info={"name": "chrome.exe", "memory_info": NS(rss=900)}),
            NS(info={"name": "System", "memory_info": NS(rss=5000)}),
            NS(info={"name": "Code.exe", "memory_info": NS(rss=500)})]
    ps = NS(sensors_battery=lambda: NS(power_plugged=False, percent=55), cpu_percent=lambda interval=0: 12.0,
            process_iter=lambda attrs=None: proc)
    c = bm.condiciones(ps)
    assert c["cargador"] is False and c["procesos"] == 3 and c["programas_mas_memoria"] == ["chrome.exe", "Code.exe"]
    filas = dict(bm.texto_condiciones(c))
    assert filas["Cargador"] == "No conectado (en batería)" and filas["Carga de la batería"] == "55 %"


def test_ejecutar_no_sigue_si_se_cancela_en_la_cpu(monkeypatch):
    monkeypatch.setattr(bm, "prueba_cpu", lambda *a, **k: {"cancelado": True})
    llamado = []
    monkeypatch.setattr(bm, "lectura_disco", lambda *a, **k: llamado.append(1) or {})
    r = bm.ejecutar([{"index": 0}], cond={})
    assert r["cancelado"] and r["discos"] == [] and not llamado


# ---------------- reportes ----------------
def test_reportes_incluyen_la_salud(repo, tmp_path):
    from app.reports.cliente import build_client, salud_para_cliente
    from app.reports.datos import load_report_data
    from app.reports.tecnico import build_technical
    hw = HardwareRepository(repo)
    code = repo.register_intake("Luis", "1", "SN-1", "Laptop", "Lento")
    hw.save_capture(code, _scan())
    HealthRepository(repo).include_in_diagnosis(code, "disco:1", "Disco con advertencia")
    data = load_report_data(repo, code)
    assert data["health"]["resultado"]["indice"]["valor"] == 85.0
    assert data["health"]["incluidos"][0]["texto"] == "Disco con advertencia"
    items = dict(salud_para_cliente(data))
    assert items["Estado general (orientativo)"].startswith("85 %")
    assert "Gráficos" not in items  # sin referencia: no se muestra al cliente
    build_technical(data, tmp_path / "t.pdf", "TEC-001")
    build_client(data, tmp_path / "c.pdf", "TEC-001")
    assert (tmp_path / "t.pdf").stat().st_size > 0 and (tmp_path / "c.pdf").stat().st_size > 0
    sin = repo.register_intake("Ana", "2", "SN-2", "PC", "Lento")
    vacio = load_report_data(repo, sin)
    build_technical(vacio, tmp_path / "t2.pdf")
    assert salud_para_cliente(vacio) == []
