"""Fase 15: integridad de los datos (transacciones atómicas, migraciones versionadas y servicio
de recepción que guarda todo o nada)."""
import sqlite3
from datetime import date, timedelta

import pytest

from app import backup
from app.db import migraciones
from app.db.database import Database
from app.db.migraciones import BaseMasNueva, VERSION_ACTUAL
from app.db.orders_repo import OrdersRepository
from app.db.repo import Repository
from app.servicios import recepcion
from app.servicios.recepcion import DatosRecepcion


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.db")
    yield d
    d.close()


@pytest.fixture
def repo(db):
    return Repository(db)


def _contar(repo, tabla) -> int:
    return repo.c.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]


def _leer_desde_otra_conexion(path, sql):
    con = sqlite3.connect(path)
    try:
        return con.execute(sql).fetchone()[0]
    finally:
        con.close()


# ---------------- Transacciones ----------------
def test_transaccion_confirma_al_final(repo, tmp_path):
    with repo.transaccion():
        repo.set_setting("a", "1")  # set_setting hace commit(): dentro del bloque no confirma
        assert _leer_desde_otra_conexion(tmp_path / "t.db", "SELECT COUNT(*) FROM settings") == 0
    assert _leer_desde_otra_conexion(tmp_path / "t.db", "SELECT COUNT(*) FROM settings") == 1


def test_transaccion_deshace_todo_si_falla(repo):
    with pytest.raises(RuntimeError):
        with repo.transaccion():
            repo.set_setting("a", "1")
            repo.add_client("Ana", "1")
            raise RuntimeError("corte")
    assert _contar(repo, "settings") == 0 and _contar(repo, "clients") == 0
    assert not repo.c.en_transaccion


def test_transaccion_anidada_deshace_solo_el_paso(repo):
    with repo.transaccion():
        repo.set_setting("externo", "1")
        with pytest.raises(ValueError):
            with repo.transaccion():
                repo.set_setting("interno", "1")
                raise ValueError("paso opcional")
    assert repo.get_setting("externo") == "1" and repo.get_setting("interno") == ""


def test_register_intake_es_atomico(repo, monkeypatch):
    def falla(*a, **k):
        raise sqlite3.OperationalError("disco lleno")
    monkeypatch.setattr(repo, "create_case", falla)
    with pytest.raises(sqlite3.OperationalError):
        repo.register_intake("Ana", "1", "SN-1", "PC", "Lento")
    assert _contar(repo, "clients") == 0 and _contar(repo, "equipment") == 0


# ---------------- Migraciones ----------------
def test_base_nueva_queda_en_la_version_actual(db):
    assert migraciones.version(db.conn) == VERSION_ACTUAL
    assert db.migraciones_aplicadas == [m[0] for m in migraciones.MIGRACIONES]
    tablas = {f[0] for f in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"cases", "hardware_captures", "health_results", "case_notes", "reports",
            "service_orders"} <= tablas


def _base_version_2(ruta):
    """Base como la dejaba la versión 2: tablas básicas, clients sin doc_id y sin tablas nuevas."""
    con = sqlite3.connect(ruta)
    con.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, tech_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL, pw_hash TEXT NOT NULL, salt TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
        CREATE TABLE clients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            phone TEXT NOT NULL DEFAULT '');
        CREATE TABLE equipment (id INTEGER PRIMARY KEY AUTOINCREMENT, serial TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL, client_id INTEGER REFERENCES clients(id), cpu TEXT DEFAULT '',
            ram TEXT DEFAULT '', storage TEXT DEFAULT '', os TEXT DEFAULT '');
        CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE,
            equipment_id INTEGER NOT NULL REFERENCES equipment(id), problem TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'Media', status TEXT NOT NULL DEFAULT 'Recibido',
            method TEXT NOT NULL DEFAULT 'Reglas',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
        INSERT INTO clients(name, phone) VALUES ('Peña', '987');
        INSERT INTO equipment(serial, description, client_id) VALUES ('SN-1', 'Laptop', 1);
        INSERT INTO cases(code, equipment_id, problem) VALUES ('C-001', 1, 'Lento');
        PRAGMA user_version = 2;
    """)
    con.close()


def test_migra_base_antigua_sin_perder_datos_y_con_copia(tmp_path):
    ruta, copias = tmp_path / "vieja.db", tmp_path / "copias"
    _base_version_2(ruta)
    d = Database(ruta, carpeta_copias=copias)
    try:
        assert d.migraciones_aplicadas == [3]
        repo = Repository(d)
        caso = repo.get_case("C-001")
        assert (caso["cliente"], caso["serial"]) == ("Peña", "SN-1")
        assert d.conn.execute("SELECT doc_id FROM clients").fetchone()[0] == ""
        OrdersRepository(repo).save("C-001", ["Cargador"])  # las tablas nuevas ya existen
    finally:
        d.close()
    respaldo = list(copias.glob(f"{migraciones.SAFETY_PREFIX}*.db"))
    assert len(respaldo) == 1
    assert _leer_desde_otra_conexion(respaldo[0], "PRAGMA user_version") == 2  # copia tal como estaba
    d2 = Database(ruta, carpeta_copias=copias)  # al reabrir no hay nada pendiente
    try:
        assert d2.migraciones_aplicadas == []
    finally:
        d2.close()
    assert len(list(copias.glob("*.db"))) == 1


def test_base_nueva_no_crea_copia(tmp_path):
    Database(tmp_path / "nueva.db", carpeta_copias=tmp_path / "copias").close()
    assert not (tmp_path / "copias").exists() or not list((tmp_path / "copias").glob("*.db"))


def test_migracion_fallida_no_deja_cambios(tmp_path, monkeypatch):
    ruta = tmp_path / "vieja.db"
    _base_version_2(ruta)

    def rota(conn):
        conn.execute("CREATE TABLE a_medias (x)")
        raise sqlite3.OperationalError("fallo a mitad")
    monkeypatch.setattr(migraciones, "MIGRACIONES", [*migraciones.MIGRACIONES, (VERSION_ACTUAL + 1, "rota", rota)])
    monkeypatch.setattr(migraciones, "VERSION_ACTUAL", VERSION_ACTUAL + 1)
    with pytest.raises(sqlite3.OperationalError):
        Database(ruta)
    assert _leer_desde_otra_conexion(ruta, "PRAGMA user_version") == VERSION_ACTUAL  # la 3 sí quedó
    assert _leer_desde_otra_conexion(
        ruta, "SELECT COUNT(*) FROM sqlite_master WHERE name='a_medias'") == 0


def test_no_abre_base_de_version_mas_nueva(tmp_path):
    ruta = tmp_path / "futura.db"
    con = sqlite3.connect(ruta)
    con.execute(f"PRAGMA user_version = {VERSION_ACTUAL + 1}")
    con.close()
    with pytest.raises(BaseMasNueva, match="más nueva"):
        Database(ruta)


def test_no_restaura_copia_de_version_mas_nueva(repo, tmp_path):
    copia = backup.create_backup(repo.c, tmp_path / "copias")
    con = sqlite3.connect(copia)
    con.execute(f"PRAGMA user_version = {VERSION_ACTUAL + 1}")
    con.close()
    with pytest.raises(ValueError, match="más nueva"):
        backup.validate_backup(copia)


# ---------------- Servicio de recepción ----------------
def _datos(**extra):
    return DatosRecepcion(**{"cliente": "Ana Díaz", "equipo": "Laptop HP", "serie": "SN-1",
                             "problema": "Lento", "telefono": "987", **extra})


def test_registrar_completo(repo):
    res = recepcion.registrar(repo, _datos(documento="12345678", accesorios=["Cargador"], tecnico="TEC"))
    assert res.code == "C-001" and res.avisos == [] and res.orden_guardada
    assert OrdersRepository(repo).get("C-001")["accessories"] == "Cargador"
    assert repo.c.execute("SELECT doc_id FROM clients").fetchone()[0] == "12345678"


@pytest.mark.parametrize("extra, mensaje", [
    ({"cliente": " "}, "Complete"),
    ({"documento": "12-34 ¿?"}, "letras y números"),
    ({"fecha_estimada": "15/10/2026"}, "no es válida"),
    ({"fecha_estimada": (date.today() - timedelta(days=1)).isoformat()}, "anterior a hoy"),
])
def test_registrar_valida_antes_de_escribir(repo, extra, mensaje):
    with pytest.raises(ValueError, match=mensaje):
        recepcion.registrar(repo, _datos(**extra))
    assert _contar(repo, "clients") == 0 and _contar(repo, "cases") == 0


def test_paso_opcional_fallido_no_pierde_la_recepcion(repo, monkeypatch):
    def falla(*a, **k):
        raise sqlite3.OperationalError("tabla bloqueada")
    monkeypatch.setattr(OrdersRepository, "save", falla)
    res = recepcion.registrar(repo, _datos())
    assert repo.get_case(res.code) is not None
    assert not res.orden_guardada and "orden de servicio" in res.avisos[0]


def test_captura_fallida_se_deshace_completa(repo, monkeypatch):
    from app.db.hardware_repo import HardwareRepository

    def a_medias(self, case_code, scan):
        self.c.execute("INSERT INTO case_scans(case_code, scan) VALUES (?, '{}')", (case_code,))
        raise RuntimeError("falla al guardar identificadores")
    monkeypatch.setattr(HardwareRepository, "save_capture", a_medias)
    res = recepcion.registrar(repo, _datos(), hw={"summary": {"cpu": "Intel"}})
    assert "captura de hardware" in res.avisos[0]
    assert _contar(repo, "case_scans") == 0  # el paso fallido no deja datos a medias
    assert repo.get_case(res.code) is not None and res.orden_guardada


def test_paso_obligatorio_fallido_no_guarda_nada(repo, monkeypatch):
    def falla(*a, **k):
        raise sqlite3.OperationalError("disco lleno")
    monkeypatch.setattr(repo, "create_case", falla)
    with pytest.raises(sqlite3.OperationalError):
        recepcion.registrar(repo, _datos(accesorios=["Cargador"]))
    assert _contar(repo, "clients") == 0 and _contar(repo, "service_orders") == 0
