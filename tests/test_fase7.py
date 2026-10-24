import pytest

from app.db.database import QAKM_Database
from app.db.repo import QAKM_Repository
from app.db.reports_repo import QAKM_ReportsRepository
from app.diagnosis.engine import diagnose
from app.reports.cliente import client_summary
from app.reports.datos import load_report_data
from app.reports.service import generate_report

SCAN = {
    "scanned_at": "2026-10-06T10:42:00",
    "summary": {"ram": "16 GB", "storage": "SSD 512 GB"},
    "components": [
        {"name": "CPU", "detail": "Intel Core i5 · 4 núcleos", "status": "ok"},
        {"name": "Temperaturas", "detail": "CPU 87 °C", "status": "ok"},
    ],
    "metrics": {"cpu_temp": 87, "cpu_usage": 76, "ram_usage": 82,
                "disk_free_gb": 64, "disk_used_pct": 40},
}


@pytest.fixture
def ctx(tmp_path):
    db = QAKM_Database(tmp_path / "test.db")
    repo = QAKM_Repository(db)
    yield repo, QAKM_ReportsRepository(repo), tmp_path
    db.close()


def _caso_completo(repo):
    code = repo.register_intake("Luis Paredes", "987", "SN-1", "Laptop HP",
                                "Se calienta, ventilador ruidoso")
    repo.save_scan(code, SCAN)
    res = diagnose(repo.get_case(code)["problem"], SCAN)
    res["ai_analysis"] = "Condiciones compatibles con un posible problema térmico."
    res["ai_model"] = "llama3.2:3b"
    repo.save_diagnosis(code, res, "Reglas + IA local")
    return code


def _es_pdf(ruta):
    with open(ruta, "rb") as f:
        return f.read(5) == b"%PDF-"


def test_reporte_tecnico_completo(ctx):
    repo, rr, tmp = ctx
    code = _caso_completo(repo)
    ruta = generate_report(repo, rr, code, "tecnico", "TEC-001", out_dir=tmp)
    assert ruta.exists() and _es_pdf(ruta) and ruta.stat().st_size > 3000
    reg = rr.recent()
    assert len(reg) == 1 and reg[0]["kind"] == "tecnico" and reg[0]["case_code"] == code


def test_reporte_cliente_sin_datos(ctx):
    repo, rr, tmp = ctx
    code = repo.register_intake("Ana", "1", "SN-2", "PC", "Lento")
    ruta = generate_report(repo, rr, code, "cliente", "TEC-001", out_dir=tmp)
    assert ruta.exists() and _es_pdf(ruta)


def test_caracteres_especiales(ctx):
    repo, rr, tmp = ctx
    code = repo.register_intake('Peña & Hijos <S.A.>', "1", "SN-3", "Equipo <Pro> & Cía",
                                'Pantalla <azul> & "ruido" ñ áéíóú')
    for tipo in ("tecnico", "cliente"):
        assert _es_pdf(generate_report(repo, rr, code, tipo, "TEC-001", out_dir=tmp))


def test_nombres_unicos(ctx):
    repo, rr, tmp = ctx
    code = _caso_completo(repo)
    a = generate_report(repo, rr, code, "tecnico", out_dir=tmp)
    b = generate_report(repo, rr, code, "tecnico", out_dir=tmp)
    assert a != b and a.exists() and b.exists()
    assert len(rr.recent()) == 2


def test_errores(ctx):
    repo, rr, tmp = ctx
    with pytest.raises(ValueError):
        generate_report(repo, rr, "C-999", "tecnico", out_dir=tmp)
    code = repo.register_intake("Ana", "1", "SN-4", "PC", "Lento")
    with pytest.raises(ValueError):
        generate_report(repo, rr, code, "otro", out_dir=tmp)


def test_client_summary():
    res = diagnose("Se calienta, ventilador ruidoso, se apaga solo", SCAN)
    resumen = client_summary(res)
    assert 1 <= len(resumen) <= 3
    assert resumen[0][1] == "Conviene atenderlo pronto"
    assert client_summary({"causes": []}) == []


def test_datos_sin_diagnostico_guardado(ctx):
    repo, _rr, _tmp = ctx
    code = repo.register_intake("Ana", "1", "SN-5", "PC", "Disco lleno")
    d = load_report_data(repo, code)
    assert d["diag_saved"] is False and d["method"] == "Reglas"
    assert d["business"] == "Mi taller"
    repo.set_setting("business_name", "Taller TecnoPC")
    assert load_report_data(repo, code)["business"] == "Taller TecnoPC"
