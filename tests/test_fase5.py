import pytest

from app.db.database import Database
from app.db.repo import Repository
from app.diagnosis.engine import diagnose, load_rules, normalizar, OPERADORES

SCAN_CALOR = {
    "summary": {"ram": "16 GB", "storage": "SSD 512 GB"},
    "metrics": {"cpu_temp": 87, "cpu_usage": 76, "ram_usage": 82,
                "disk_free_gb": 64, "disk_used_pct": 40},
}


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    yield Repository(db)
    db.close()


def test_reglas_validas():
    reglas = load_rules()
    ids = [r["id"] for r in reglas]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 10
    for r in reglas:
        assert r["priority"] in ("Alta", "Media", "Baja")
        assert r["symptoms"] or r["conditions"]
        assert r["recommendations"]
        for c in r["conditions"]:
            assert c["label"]
            if "metric" in c:
                assert c["op"] in OPERADORES and "value" in c
            else:
                assert c["field"] and c["regex"]


def test_sobrecalentamiento():
    res = diagnose("Se calienta, ventilador ruidoso, se apaga solo", SCAN_CALOR)
    top = res["causes"][0]
    assert top["id"] == "R-001" and top["priority"] == "Alta"
    assert top["confidence"] >= 0.9
    assert res["status"] == "ATENCIÓN REQUERIDA"
    assert any(c["id"] == "R-002" for c in res["causes"])


def test_disco_lleno():
    scan = {"summary": {"storage": "SSD 256 GB"},
            "metrics": {"disk_free_gb": 8, "disk_used_pct": 96}}
    res = diagnose("Disco lleno", scan)
    assert res["causes"][0]["id"] == "R-006"
    assert res["causes"][0]["confidence"] >= 0.7


def test_sin_datos_suficientes():
    res = diagnose("Lento")
    assert res["causes"] == []
    assert res["status"] == "DATOS INSUFICIENTES"


def test_normalizacion_y_mayusculas():
    assert normalizar("Pantalla Azul tras ACTUALIZACIÓN") == "pantalla azul tras actualizacion"
    assert diagnose("PANTALLA AZUL")["causes"][0]["id"] == "R-012"


def test_scan_por_caso(repo):
    code = repo.register_intake("Ana", "1", "SN-1", "PC", "Lento")
    assert repo.get_scan(code) is None
    repo.save_scan(code, SCAN_CALOR)
    assert repo.get_scan(code)["metrics"]["cpu_temp"] == 87
    repo.save_scan(code, {"summary": {}, "metrics": {"cpu_temp": 50}})
    assert repo.get_scan(code)["metrics"]["cpu_temp"] == 50


def test_guardar_diagnostico(repo):
    code = repo.register_intake("Luis", "9", "SN-2", "Laptop",
                                "Se calienta, ventilador ruidoso", "Media")
    repo.save_scan(code, SCAN_CALOR)
    res = diagnose(repo.get_case(code)["problem"], repo.get_scan(code))
    assert repo.get_diagnosis(code) is None
    repo.save_diagnosis(code, res)
    caso = repo.get_case(code)
    assert caso["priority"] == "Alta" and caso["status"] == "En diagnóstico"
    assert repo.get_diagnosis(code)["result"]["causes"][0]["id"] == res["causes"][0]["id"]