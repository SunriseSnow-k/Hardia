import pytest
from app.db.database import Database
from app.db.repo import Repository


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    yield Repository(db)
    db.close()


def test_usuario_valido_e_invalido(repo):
    repo.create_user("tec-001", "clave123")
    assert repo.verify_user("TEC-001", "clave123")
    assert not repo.verify_user("TEC-001", "otra")
    assert not repo.verify_user("NOEXISTE", "clave123")


def test_contrasena_corta_y_id_duplicado(repo):
    with pytest.raises(ValueError):
        repo.create_user("TEC-001", "123")
    repo.create_user("TEC-001", "clave123")
    with pytest.raises(ValueError):
        repo.create_user("TEC-001", "clave123")


def test_reingreso_y_busqueda(repo):
    cid = repo.add_client("Luis Paredes", "987000111")
    eid = repo.upsert_equipment("SN-1", "Laptop HP", cid)
    repo.create_case(eid, "Arranque lento", "Media", "Entregado")
    previos = repo.previous_cases("sn-1")
    assert len(previos) == 1 and previos[0]["problem"] == "Arranque lento"
    assert len(repo.search("Luis")) == 1
    assert len(repo.search("SN-1")) == 1
    assert repo.search("inexistente") == []


def test_codigos_consecutivos(repo):
    eid = repo.upsert_equipment("SN-2", "PC", repo.add_client("Ana"))
    assert repo.create_case(eid, "a") == "C-001"
    assert repo.create_case(eid, "b") == "C-002"