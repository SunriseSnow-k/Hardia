import pytest

from app.db.database import Database
from app.db.repo import Repository


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    yield Repository(db)
    db.close()


def test_upsert_no_borra_hardware(repo):
    cid = repo.add_client("Ana", "1")
    repo.upsert_equipment("SN-9", "PC", cid, cpu="i5", ram="16 GB")
    repo.upsert_equipment("SN-9", "PC nueva", cid)
    fila = repo.c.execute(
        "SELECT cpu, ram, description FROM equipment WHERE serial='SN-9'"
    ).fetchone()
    assert fila["cpu"] == "i5" and fila["ram"] == "16 GB"
    assert fila["description"] == "PC nueva"


def test_recepcion_y_reingreso(repo):
    c1 = repo.register_intake("Luis", "987", "sn-5", "Laptop", "Lento", "Alta")
    c2 = repo.register_intake("Luis", "987", "SN-5", "Laptop", "Se apaga")
    assert c1 == "C-001" and c2 == "C-002"
    assert len(repo.previous_cases("SN-5")) == 2
    assert len(repo.other_cases("SN-5", c2)) == 1
    assert repo.count_by_status() == {"Recibido": 2}


def test_get_case_y_estado(repo):
    code = repo.register_intake("Marta", "555", "SN-7", "PC armada", "RAM elevada")
    assert repo.get_case(code)["problem"] == "RAM elevada"
    repo.update_case_status(code, "Listo")
    assert repo.get_case(code)["status"] == "Listo"
    assert repo.get_case("NO-EXISTE") is None
