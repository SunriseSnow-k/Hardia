import pytest

from app import backup
from app.db.database import Database
from app.db.repo import Repository
from app.db.reports_repo import ReportsRepository
from app.hardware import diag_file
from app.reports.service import generate_report


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    yield Repository(db)
    db.close()


def test_inyeccion_sql_no_afecta(repo):
    raro = "'; DROP TABLE cases;--"
    code = repo.register_intake(raro, "1", "SN-X", "Equipo <b>&</b>", raro)
    assert repo.get_case(code)["problem"] == raro
    assert len(repo.search(raro)) == 1
    assert repo.count_by_status() == {"Recibido": 1}


def test_unicode_y_emojis(repo):
    texto = "Peña ñandú 😀 áéíóú"
    code = repo.register_intake("Peña ñandú 😀", "1", "SN-U", "Laptop ñ", texto)
    assert repo.get_case(code)["problem"] == texto
    assert len(repo.search("ñandú")) == 1


def test_serie_normalizada(repo):
    repo.register_intake("Ana", "1", "sn-1", "PC", "a")
    repo.register_intake("Ana", "1", " SN-1 ", "PC", "b")
    assert len(repo.previous_cases("Sn-1")) == 2


def test_texto_muy_largo(repo):
    largo = "x" * 100_000
    code = repo.register_intake("Ana", "1", "SN-L", "PC", largo)
    assert len(repo.get_case(code)["problem"]) == 100_000


def test_scan_corrupto_en_caso_y_reportes(repo, tmp_path):
    code = repo.register_intake("Ana", "1", "SN-C", "PC", "Se calienta, ventilador")
    repo.save_scan(code, {"summary": None, "metrics": {"cpu_temp": "caliente"}, "components": []})
    rr = ReportsRepository(repo)
    for tipo in ("tecnico", "cliente"):
        ruta = generate_report(repo, rr, code, tipo, "TEC-001", out_dir=tmp_path)
        assert ruta.exists() and ruta.read_bytes()[:5] == b"%PDF-"


@pytest.mark.parametrize("contenido", [
    b"\xff\xfe\x00\x01",                                   # binario
    b"",                                                   # vacío
    b'{"format": "SD-DIAG", "summary": {',                 # JSON truncado
    b"[]",                                                 # JSON de otro tipo
    b'{"format":"SD-DIAG"}',                               # faltan campos
    b'{"format":"SD-DIAG","summary":[],"components":[]}',  # summary no es objeto
    b'{"format":"SD-DIAG","summary":{},"components":["x"]}',               # componente inválido
    b'{"format":"SD-DIAG","summary":{},"components":[],"metrics":"x"}',    # métricas inválidas
])
def test_importar_archivo_corrupto(tmp_path, contenido):
    p = tmp_path / "x.diag"
    p.write_bytes(contenido)
    with pytest.raises(ValueError):
        diag_file.load_scan(p)


def test_usuarios_normalizacion(repo):
    repo.create_user("  tec-9 ", "contraseña_ñ😀")
    assert repo.verify_user("tec-9", "contraseña_ñ😀")
    assert not repo.verify_user("TEC-9", "contraseña_n")
    with pytest.raises(ValueError):
        repo.create_user("   ", "clave123")


def test_backup_de_base_vacia(repo, tmp_path):
    ruta = backup.create_backup(repo.c, tmp_path / "copias")
    backup.validate_backup(ruta)