import os
import sqlite3
import time
from pathlib import Path

import pytest

from app import backup
from app.db.database import Database
from app.db.equipment_repo import EquipmentRepository
from app.db.repo import Repository
from app.db.users_repo import UsersRepository


@pytest.fixture
def ctx(tmp_path):
    db = Database(tmp_path / "test.db")
    yield Repository(db), tmp_path / "copias"
    db.close()


def test_backup_y_restauracion(ctx):
    repo, folder = ctx
    c1 = repo.register_intake("Ana", "1", "SN-1", "PC", "Lento")
    copia = backup.create_backup(repo.c, folder)
    repo.register_intake("Luis", "2", "SN-2", "Laptop", "Se apaga")
    assert len(repo.list_cases()) == 2
    seguridad = backup.restore_backup(repo.c, copia, folder)
    assert len(repo.list_cases()) == 1 and repo.get_case(c1)
    assert seguridad.exists() and seguridad.name.startswith(backup.SAFETY_PREFIX)


def test_validar_copias_invalidas(ctx):
    _repo, folder = ctx
    folder.mkdir()
    texto = folder / "x.db"
    texto.write_text("esto no es una base de datos")
    with pytest.raises(ValueError):
        backup.validate_backup(texto)
    vacia = folder / "vacia.db"
    con = sqlite3.connect(vacia)
    con.execute("CREATE TABLE t(a)")
    con.commit()
    con.close()
    with pytest.raises(ValueError, match="de este programa"):
        backup.validate_backup(vacia)
    with pytest.raises(ValueError):
        backup.validate_backup(folder / "nada.db")


def test_copia_a_archivo_elegido(ctx):
    repo, folder = ctx
    repo.register_intake("Ana", "1", "SN-1", "PC", "Lento")
    destino = folder / "usb" / "mi_copia.db"
    assert backup.backup_to(repo.c, destino) == destino
    backup.validate_backup(destino)


def test_no_sobrescribe_la_base_en_uso(ctx):
    repo, folder = ctx
    en_uso = Path(repo.c.execute("PRAGMA database_list").fetchone()[2])
    with pytest.raises(ValueError):
        backup.backup_to(repo.c, en_uso)
    with pytest.raises(ValueError):
        backup.restore_backup(repo.c, en_uso, folder)
    assert en_uso.exists()


def test_copia_automatica_por_intervalo(ctx):
    repo, folder = ctx
    a = backup.auto_backup(repo.c, folder)
    assert a is not None and a.name.startswith(backup.AUTO_PREFIX)
    assert backup.auto_backup(repo.c, folder) is None  # ya hay una reciente
    antiguo = time.time() - 48 * 3600
    os.utime(a, (antiguo, antiguo))
    assert backup.auto_backup(repo.c, folder) is not None


def test_rotacion_de_copias_automaticas(ctx):
    repo, folder = ctx
    ultimas = [backup.auto_backup(repo.c, folder, min_hours=0, keep=3) for _ in range(5)]
    assert len(list(folder.glob("auto_*.db"))) == 3
    assert ultimas[-1].exists()
    assert backup.last_backup_time(folder) is not None


def test_usuarios(ctx):
    repo, _ = ctx
    repo.create_user("tec-001", "clave123")
    repo.create_user("tec-002", "otra456")
    ur = UsersRepository(repo)
    assert [u["tech_id"] for u in ur.list_users()] == ["TEC-001", "TEC-002"]
    with pytest.raises(ValueError, match="actual"):
        ur.change_password("TEC-001", "mala", "nueva123")
    with pytest.raises(ValueError, match="6 caracteres"):
        ur.change_password("TEC-001", "clave123", "123")
    with pytest.raises(ValueError, match="distinta"):
        ur.change_password("TEC-001", "clave123", "clave123")
    ur.change_password("tec-001", "clave123", "nueva123")
    assert repo.verify_user("TEC-001", "nueva123")
    assert not repo.verify_user("TEC-001", "clave123")
    assert repo.verify_user("TEC-002", "otra456")


def test_listado_de_equipos(ctx):
    repo, _ = ctx
    repo.register_intake("Ana", "111", "SN-1", "PC Dell", "Lento")
    repo.register_intake("Ana", "111", "SN-1", "PC Dell", "Se apaga")
    repo.register_intake("Luis", "222", "SN-2", "Laptop HP", "Se calienta")
    er = EquipmentRepository(repo)
    todos = er.list_equipment()
    assert len(todos) == 2
    sn1 = [r for r in todos if r["serial"] == "SN-1"][0]
    assert sn1["n_casos"] == 2 and sn1["ultimo_code"] == "C-002"
    assert [r["serial"] for r in er.list_equipment("luis")] == ["SN-2"]
    assert er.list_equipment("nada") == []
