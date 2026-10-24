import sqlite3
import time

import pytest

from app.db.database import QAKM_Database
from app.db.repo import QAKM_Repository
from app.db.reports_repo import QAKM_ReportsRepository
from app.db.search_repo import QAKM_SearchQueries, pages


@pytest.fixture
def repo(tmp_path):
    db = QAKM_Database(tmp_path / "t.db")
    r = QAKM_Repository(db)
    yield r
    db.close()


def _poblar(repo, n):
    for i in range(n):
        repo.register_intake(f"Cliente {i:03d}", f"9{i:08d}", f"SN-{i:04d}",
                             f"Laptop Marca{i % 4} Modelo{i % 3}", f"Problema número {i}",
                             ["Alta", "Media", "Baja"][i % 3])


def _codigos(res):
    return [r["code"] for r in res["rows"]]


def test_paginacion(repo):
    _poblar(repo, 120)
    q = QAKM_SearchQueries(repo.c)
    p1 = q.search_cases(limit=50, offset=0)
    p2 = q.search_cases(limit=50, offset=50)
    p3 = q.search_cases(limit=50, offset=100)
    assert p1["total"] == 120 and len(p1["rows"]) == 50 and len(p3["rows"]) == 20
    assert _codigos(p1)[0] == "C-120"
    todos = _codigos(p1) + _codigos(p2) + _codigos(p3)
    assert len(set(todos)) == 120
    assert pages(120) == 3 and pages(0) == 1 and pages(50) == 1 and pages(51) == 2


def test_busqueda_por_campos(repo):
    _poblar(repo, 30)
    q = QAKM_SearchQueries(repo.c)
    assert _codigos(q.search_cases(text="SN-0007")) == ["C-008"]
    assert _codigos(q.search_cases(text="900000012")) == ["C-013"]
    assert _codigos(q.search_cases(text="C-010")) == ["C-010"]
    assert q.search_cases(text="Marca1 Modelo2")["total"] == 3
    assert "C-026" in _codigos(q.search_cases(text="número 25"))
    assert q.search_cases(text="no existe")["total"] == 0


def test_varias_palabras_se_combinan(repo):
    _poblar(repo, 30)
    q = QAKM_SearchQueries(repo.c)
    assert q.search_cases(text="Marca1")["total"] == 8
    assert q.search_cases(text="Marca1 Cliente")["total"] == 8
    assert q.search_cases(text="Marca1 Modelo2")["total"] == 3


def test_busqueda_y_filtros_por_fecha(repo):
    _poblar(repo, 10)
    repo.c.execute("UPDATE cases SET created_at='2020-01-01 00:00:00'")
    for code, fecha in (("C-001", "2026-10-06 09:15:00"), ("C-002", "2026-10-06 18:00:00"),
                        ("C-003", "2026-09-25 10:00:00"), ("C-004", "2025-01-15 08:00:00")):
        repo.c.execute("UPDATE cases SET created_at=? WHERE code=?", (fecha, code))
    repo.c.commit()
    q = QAKM_SearchQueries(repo.c)
    for texto in ("2026-10-06", "06/10/2026", "2026-10", "10/2026"):
        assert sorted(_codigos(q.search_cases(text=texto))) == ["C-001", "C-002"], texto
    r = q.search_cases(date_from="2026-09-01", date_to="2026-10-06")
    assert sorted(_codigos(r)) == ["C-001", "C-002", "C-003"]
    assert q.search_cases(date_from="2026-10-07")["total"] == 0
    assert q.search_cases(date_from="2026-10-06", date_to="2025-01-01")["total"] == 4  # invertido
    with pytest.raises(ValueError):
        q.search_cases(date_from="no-es-fecha")


def test_filtros_combinados(repo):
    _poblar(repo, 30)
    repo.update_case_status("C-001", "Listo")
    repo.update_case_status("C-004", "Listo")
    q = QAKM_SearchQueries(repo.c)
    assert q.search_cases(status="Listo", priority="Alta")["total"] == 2
    assert q.search_cases(status="Listo", priority="Media")["total"] == 0
    assert _codigos(q.search_cases(status="Listo", text="Marca0")) == ["C-001"]
    assert q.search_cases(priority="Alta")["total"] == 10


def test_filtro_de_diagnostico_y_metodo(repo):
    _poblar(repo, 5)
    repo.save_diagnosis("C-002", {"causes": []}, "Reglas + IA local")
    q = QAKM_SearchQueries(repo.c)
    assert _codigos(q.search_cases(diagnosis="con")) == ["C-002"]
    assert q.search_cases(diagnosis="sin")["total"] == 4
    assert _codigos(q.search_cases(method="Reglas + IA local")) == ["C-002"]
    assert q.search_cases(diagnosis="con")["rows"][0]["has_diagnosis"] == 1


def test_comodines_sql_se_tratan_como_texto(repo):
    repo.register_intake("100%_real", "1", "SN-A", "PC", "x")
    repo.register_intake("Ana", "2", "SN-B", "PC", "y")
    repo.register_intake("Ana", "2", "SN-C", "PC", "z")
    q = QAKM_SearchQueries(repo.c)
    assert q.search_cases(text="%")["total"] == 1
    assert q.search_cases(text="_")["total"] == 1


def test_texto_malicioso_no_afecta(repo):
    _poblar(repo, 3)
    q = QAKM_SearchQueries(repo.c)
    assert q.search_cases(text="'; DROP TABLE cases;--")["total"] == 0
    assert q.search_cases()["total"] == 3


def test_busqueda_de_reportes(repo):
    c1 = repo.register_intake("Luis", "1", "SN-1", "Laptop HP", "a")
    c2 = repo.register_intake("Ana", "2", "SN-2", "PC Dell", "b")
    c3 = repo.register_intake("Luis", "1", "SN-3", "Laptop HP", "c")
    rr = QAKM_ReportsRepository(repo)
    for code, kind in ((c1, "tecnico"), (c1, "cliente"), (c2, "tecnico"), (c3, "cliente")):
        rr.add(code, kind, f"C:/x/{code}_{kind}.pdf")
    repo.c.execute("UPDATE reports SET created_at='2026-10-06 10:00:00'")
    repo.c.execute("UPDATE reports SET created_at='2026-09-01 10:00:00' WHERE id=1")
    repo.update_case_status(c2, "Listo")
    q = QAKM_SearchQueries(repo.c)
    assert q.search_reports(text="Luis")["total"] == 3
    assert q.search_reports(kind="tecnico")["total"] == 2
    assert q.search_reports(kind="cliente", text="Luis")["total"] == 2
    assert q.search_reports(date_to="2026-09-30")["total"] == 1
    assert q.search_reports(case_status="Listo")["total"] == 1
    assert q.search_reports(text="2026-09-01")["total"] == 1
    p = q.search_reports(limit=2)
    assert p["total"] == 4 and [r["report_id"] for r in p["rows"]] == [4, 3]


def test_reportes_de_un_caso(repo):
    c1 = repo.register_intake("Luis", "1", "SN-1", "Laptop", "a")
    c2 = repo.register_intake("Ana", "2", "SN-2", "PC", "b")
    rr = QAKM_ReportsRepository(repo)
    rr.add(c1, "tecnico", "a.pdf")
    rr.add(c1, "cliente", "b.pdf")
    rr.add(c2, "tecnico", "c.pdf")
    assert [r["kind"] for r in rr.for_case(c1)] == ["cliente", "tecnico"]
    assert rr.for_case("C-999") == []


def test_indices_y_conexion_de_solo_lectura(repo, tmp_path):
    nombres = {r[0] for r in repo.c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_cases_created", "idx_cases_status", "idx_reports_created"} <= nombres
    ro = sqlite3.connect(f"{(tmp_path / 't.db').resolve().as_uri()}?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("INSERT INTO settings(key, value) VALUES ('x','y')")
    finally:
        ro.close()


def test_rendimiento_con_20000_casos(repo):
    n = 20_000
    c = repo.c
    c.executemany("INSERT INTO clients(name, phone) VALUES (?,?)",
                  [(f"Cliente {i:05d}", f"9{i:08d}") for i in range(n)])
    c.executemany("INSERT INTO equipment(serial, description, client_id) VALUES (?,?,?)",
                  [(f"SN-{i:05d}", f"Laptop Marca{i % 4}", i + 1) for i in range(n)])
    c.executemany("INSERT INTO cases(code, equipment_id, problem) VALUES (?,?,?)",
                  [(f"C-{i + 1:05d}", i + 1, f"Problema {i}") for i in range(n)])
    c.commit()
    q = QAKM_SearchQueries(c)
    inicio = time.time()
    pagina = q.search_cases(limit=50, offset=10_000)
    busqueda = q.search_cases(text="Cliente 01234")
    assert time.time() - inicio < 2
    assert pagina["total"] == n and len(pagina["rows"]) == 50
    assert busqueda["total"] >= 1
