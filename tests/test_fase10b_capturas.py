import pytest

from app.db.database import QAKM_Database
from app.db.hardware_repo import QAKM_HardwareRepository
from app.db.repo import QAKM_Repository
from app.hardware.inventory import compare_captures
from app.hardware.scanner import run_scan
from tests.test_fase10b_hardware import _env


@pytest.fixture
def ctx(tmp_path):
    db = QAKM_Database(tmp_path / "t.db")
    repo = QAKM_Repository(db)
    yield repo, QAKM_HardwareRepository(repo)
    db.close()


def _scan(**cambios):
    s = run_scan(env=_env())
    s["provenance"] = {"how": "local_scan", "file": None}
    s.update(cambios)
    return s


def test_guarda_captura_vinculada_a_caso_y_equipo(ctx):
    repo, hw = ctx
    code = repo.register_intake("Luis", "1", "SN-1", "Laptop HP", "Lento")
    res = hw.save_capture(code, _scan())
    assert res["conflicts"] == []
    fila = hw.captures_for_case(code)[0]
    assert fila["source"] == "local_scan" and fila["schema_version"] == 2
    cap = hw.get_capture(fila["id"])
    assert cap["manufacturer"] == "HP" and cap["serial"] == "5CD1234ABC"
    assert cap["payload"]["inventory"]["cpu"]["cores"] == 4
    assert repo.get_scan(code)["inventory"]["cpu"]["cores"] == 4  # el diagnóstico sigue funcionando
    ids = {tuple(r) for r in repo.c.execute("SELECT kind, value FROM equipment_identifiers")}
    assert ("uuid", "4C4C4544-0042-4A10-8057-B8C04F4D3532") in ids and ("mac", "AA:BB:CC:DD:EE:FF") in ids


def test_reanalizar_conserva_el_historial(ctx):
    repo, hw = ctx
    c1 = repo.register_intake("Luis", "1", "SN-1", "Laptop HP", "Lento")
    hw.save_capture(c1, _scan(scanned_at="2026-09-25T10:00:00"))
    c2 = repo.register_intake("Luis", "1", "SN-1", "Laptop HP", "Se calienta")
    nueva = _scan(scanned_at="2026-10-06T09:00:00")
    nueva["inventory"]["memory"]["total_gb"] = 31.7
    hw.save_capture(c2, nueva)
    hw.save_capture(c2, _scan(scanned_at="2026-10-06T09:30:00"))  # segunda captura del mismo caso
    eq = repo.c.execute("SELECT equipment_id FROM cases WHERE code=?", (c1,)).fetchone()[0]
    caps = hw.captures_for_equipment(eq)
    assert [c["captured_at"] for c in caps] == ["2026-10-06T09:30:00", "2026-10-06T09:00:00",
                                                "2026-09-25T10:00:00"]
    assert len(hw.captures_for_case(c2)) == 2 and len(hw.captures_for_case(c1)) == 1
    anterior = hw.latest_capture(eq, exclude_case=c2)
    assert anterior["case_code"] == c1
    cambios = compare_captures(anterior["payload"], hw.get_capture(caps[1]["id"])["payload"])
    assert [c["area"] for c in cambios] == ["Memoria RAM"]
    assert repo.c.execute("SELECT COUNT(*) FROM equipment").fetchone()[0] == 1  # sin duplicar equipos


def test_identificacion_del_equipo(ctx):
    repo, hw = ctx
    code = repo.register_intake("Luis", "1", "SN-1", "Laptop HP", "Lento")
    hw.save_capture(code, _scan())
    eq = repo.c.execute("SELECT equipment_id FROM cases WHERE code=?", (code,)).fetchone()[0]
    res = hw.identify_scan(_scan())
    assert res["status"] == "encontrado" and res["equipment_id"] == eq
    assert res["candidates"][0]["serial"] == "SN-1" and "uuid" in res["candidates"][0]["matched"]
    assert hw.identify([("mac", "AA:BB:CC:DD:EE:FF")])["status"] == "probable"
    assert hw.identify([("uuid", "11111111-2222-3333-4444-555555555555")])["status"] == "nuevo"
    assert hw.identify([])["status"] == "nuevo"


def test_reconoce_equipos_registrados_antes_por_su_serie(ctx):
    repo, hw = ctx
    repo.register_intake("Ana", "2", "5CD1234ABC", "Laptop", "Lento")  # sin identificadores guardados
    res = hw.identify_scan(_scan())
    assert res["status"] == "encontrado" and res["candidates"][0]["serial"] == "5CD1234ABC"


def test_ambiguo_y_conflictos_no_reasignan(ctx):
    repo, hw = ctx
    a = repo.register_intake("Ana", "1", "SN-A", "PC A", "x")
    b = repo.register_intake("Beto", "2", "SN-B", "PC B", "y")
    ea = repo.c.execute("SELECT equipment_id FROM cases WHERE code=?", (a,)).fetchone()[0]
    eb = repo.c.execute("SELECT equipment_id FROM cases WHERE code=?", (b,)).fetchone()[0]
    hw.add_identifiers(ea, [("uuid", "UUID-A")])
    hw.add_identifiers(eb, [("serial", "SERIE-B")])
    res = hw.identify([("uuid", "UUID-A"), ("serial", "SERIE-B")])
    assert res["status"] == "ambiguo" and {c["equipment_id"] for c in res["candidates"]} == {ea, eb}
    conflictos = hw.add_identifiers(ea, [("serial", "SERIE-B"), ("uuid", "UUID-A")])
    assert conflictos == [{"kind": "serial", "value": "SERIE-B", "equipment_id": eb}]
    assert hw.identify([("serial", "SERIE-B")])["equipment_id"] == eb  # no se reasignó


def test_caso_inexistente(ctx):
    _repo, hw = ctx
    with pytest.raises(ValueError):
        hw.save_capture("C-999", _scan())


def test_migracion_de_escaneos_anteriores(ctx):
    repo, hw = ctx
    code = repo.register_intake("Luis", "1", "SN-1", "Laptop", "Lento")
    viejo = {"format": "SD-DIAG", "version": 1, "scanned_at": "2026-09-01T08:00:00", "host": "PC-VIEJO",
             "summary": {"serial": "OLD123"}, "components": [], "metrics": {}}
    repo.save_scan(code, viejo)
    assert hw.migrate_legacy() == 1
    assert hw.migrate_legacy() == 0  # idempotente
    fila = hw.captures_for_case(code)[0]
    assert fila["source"] == "legacy" and fila["captured_at"] == "2026-09-01T08:00:00"
    assert hw.get_capture(fila["id"])["payload"] == viejo
    assert repo.get_scan(code) == viejo  # el escaneo original sigue intacto
    assert hw.identify([("serial", "OLD123")])["status"] == "encontrado"


def test_migracion_ignora_datos_danados(ctx):
    repo, hw = ctx
    code = repo.register_intake("Luis", "1", "SN-1", "Laptop", "Lento")
    repo.c.execute("INSERT INTO case_scans(case_code, scan) VALUES (?, ?)", (code, "{esto no es json"))
    repo.c.commit()
    assert hw.migrate_legacy() == 0
    assert repo.c.execute("SELECT scan FROM case_scans").fetchone()[0] == "{esto no es json"


def test_las_tablas_nuevas_no_tocan_los_datos_existentes(tmp_path):
    db = QAKM_Database(tmp_path / "t.db")
    repo = QAKM_Repository(db)
    code = repo.register_intake("Luis", "1", "SN-1", "Laptop", "Lento")
    QAKM_HardwareRepository(repo)
    QAKM_HardwareRepository(repo)  # crear dos veces no falla ni borra nada
    assert repo.get_case(code)["problem"] == "Lento"
    db.close()
