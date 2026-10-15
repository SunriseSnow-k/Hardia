"""Fase 16: roles, bloqueo por intentos fallidos y auditoría."""
from datetime import datetime, timedelta

import pytest

from app.db.audit_repo import AuditRepository
from app.db.database import Database
from app.db.repo import Repository
from app.db.users_repo import UsersRepository
from app.servicios import cuentas
from app.servicios.cuentas import AccesoBloqueado, SinPermiso, segundos_de_bloqueo

T0 = datetime(2026, 10, 15, 9, 0, 0)


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "c.db")
    r = Repository(db)
    cuentas.crear_cuenta_inicial(r, "admin-1", "secreto1")
    r.create_user("TEC-2", "tecnico2")
    yield r
    db.close()


def _acciones(repo) -> list[str]:
    return [a["action"] for a in AuditRepository(repo).recientes()]


# ---------------- Roles ----------------
def test_primera_cuenta_es_admin_y_las_demas_tecnicos(repo):
    users = UsersRepository(repo)
    assert users.role("ADMIN-1") == "admin" and users.role("TEC-2") == "tecnico"
    with pytest.raises(SinPermiso):
        cuentas.crear_cuenta_inicial(repo, "OTRO", "secreto1")


def test_migracion_hace_admin_al_tecnico_mas_antiguo(tmp_path):
    import sqlite3
    from tests.test_fase15_datos import _base_version_2
    ruta = tmp_path / "v2.db"
    _base_version_2(ruta)
    con = sqlite3.connect(ruta)
    con.executemany("INSERT INTO users(tech_id, name, pw_hash, salt) VALUES (?,?,?,?)",
                    [("TEC-001", "a", "x", "y"), ("TEC-002", "b", "x", "y")])
    con.commit()
    con.close()
    d = Database(ruta)
    try:
        users = UsersRepository(Repository(d))
        assert users.role("TEC-001") == "admin" and users.role("TEC-002") == "tecnico"
    finally:
        d.close()


# ---------------- Inicio de sesión y bloqueo ----------------
def test_inicio_correcto(repo):
    s = cuentas.iniciar_sesion(repo, " admin-1 ", "secreto1", T0)
    assert (s.tech_id, s.es_admin) == ("ADMIN-1", True)
    assert _acciones(repo)[0] == "sesion_iniciada"


def test_mensaje_igual_para_id_inexistente_y_clave_incorrecta(repo):
    with pytest.raises(ValueError) as a:
        cuentas.iniciar_sesion(repo, "NADIE", "xxxxxx", T0)
    with pytest.raises(ValueError) as b:
        cuentas.iniciar_sesion(repo, "TEC-2", "xxxxxx", T0)
    assert str(a.value) == str(b.value) == cuentas.CREDENCIALES_INVALIDAS


def test_politica_de_bloqueo():
    assert [segundos_de_bloqueo(n) for n in (4, 5, 6, 7, 20)] == [0, 30, 60, 120, 900]


def test_bloqueo_tras_cinco_fallos_y_desbloqueo_por_tiempo(repo):
    for _ in range(4):
        with pytest.raises(ValueError, match="incorrectos"):
            cuentas.iniciar_sesion(repo, "TEC-2", "mala", T0)
    with pytest.raises(AccesoBloqueado) as e:
        cuentas.iniciar_sesion(repo, "TEC-2", "mala", T0)
    assert e.value.segundos == 30 and "cuenta_bloqueada" in _acciones(repo)
    # durante el bloqueo, ni la contraseña correcta entra
    with pytest.raises(AccesoBloqueado):
        cuentas.iniciar_sesion(repo, "TEC-2", "tecnico2", T0 + timedelta(seconds=10))
    # pasado el bloqueo, entra y el contador vuelve a cero
    assert cuentas.iniciar_sesion(repo, "TEC-2", "tecnico2", T0 + timedelta(seconds=31)).tech_id == "TEC-2"
    assert UsersRepository(repo).get("TEC-2")["failed_attempts"] == 0


def test_bloqueo_crece_con_cada_fallo(repo):
    t = T0
    for _ in range(5):
        with pytest.raises(ValueError):
            cuentas.iniciar_sesion(repo, "TEC-2", "mala", t)
    t += timedelta(seconds=31)
    with pytest.raises(AccesoBloqueado) as e:
        cuentas.iniciar_sesion(repo, "TEC-2", "mala", t)
    assert e.value.segundos == 60


def test_cuenta_desactivada_no_entra(repo):
    cuentas.cambiar_activo(repo, "ADMIN-1", "TEC-2", False)
    with pytest.raises(ValueError, match="desactivada"):
        cuentas.iniciar_sesion(repo, "TEC-2", "tecnico2", T0)
    assert not repo.verify_user("TEC-2", "tecnico2")
    cuentas.cambiar_activo(repo, "ADMIN-1", "TEC-2", True)
    assert cuentas.iniciar_sesion(repo, "TEC-2", "tecnico2", T0).tech_id == "TEC-2"


# ---------------- Permisos ----------------
@pytest.mark.parametrize("accion", [
    lambda r: cuentas.crear_tecnico(r, "TEC-2", "TEC-3", "secreto1"),
    lambda r: cuentas.restablecer_password(r, "TEC-2", "ADMIN-1", "nueva123"),
    lambda r: cuentas.cambiar_rol(r, "TEC-2", "TEC-2", "admin"),
    lambda r: cuentas.cambiar_activo(r, "TEC-2", "ADMIN-1", False),
    lambda r: cuentas.requerir_admin(r, "NADIE"),
])
def test_tecnico_no_puede_administrar(repo, accion):
    with pytest.raises(SinPermiso):
        accion(repo)


def test_admin_restablece_contrasena_y_desbloquea(repo):
    for _ in range(5):
        with pytest.raises(ValueError):
            cuentas.iniciar_sesion(repo, "TEC-2", "olvidada", T0)
    cuentas.restablecer_password(repo, "ADMIN-1", "TEC-2", "nueva123")
    assert cuentas.iniciar_sesion(repo, "TEC-2", "nueva123", T0).tech_id == "TEC-2"
    assert "contrasena_restablecida" in _acciones(repo)


def test_siempre_queda_un_admin_activo(repo):
    with pytest.raises(ValueError, match="al menos un administrador"):
        cuentas.cambiar_rol(repo, "ADMIN-1", "ADMIN-1", "tecnico")
    with pytest.raises(ValueError, match="propia cuenta"):
        cuentas.cambiar_activo(repo, "ADMIN-1", "ADMIN-1", False)
    cuentas.cambiar_rol(repo, "ADMIN-1", "TEC-2", "admin")
    cuentas.cambiar_rol(repo, "ADMIN-1", "ADMIN-1", "tecnico")  # ahora sí: TEC-2 es admin
    assert UsersRepository(repo).role("ADMIN-1") == "tecnico"


def test_cambiar_mi_contrasena_audita(repo):
    with pytest.raises(ValueError, match="actual no es correcta"):
        cuentas.cambiar_mi_password(repo, "TEC-2", "mala", "otra1234")
    cuentas.cambiar_mi_password(repo, "TEC-2", "tecnico2", "otra1234")
    assert repo.verify_user("TEC-2", "otra1234")
    assert _acciones(repo)[0] == "contrasena_cambiada"


def test_auditoria_rechaza_acciones_desconocidas(repo):
    with pytest.raises(ValueError):
        AuditRepository(repo).registrar("borrar_todo", "X")


# ---------------- Interfaz ----------------
@pytest.fixture
def ui(repo, monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    QApplication.instance() or QApplication([])
    return repo


def test_configuracion_para_tecnico_oculta_administracion(ui):
    from app.ui.pages.configuracion import ConfiguracionPage
    page = ConfiguracionPage(ui, "TEC-2")
    assert page.admin_box.isHidden() and page.p_audit.isHidden()
    assert not page.b_restaurar.isEnabled() and not page.b_negocio.isEnabled()
    page.nombre.setText("Taller pirata")
    page._guardar_negocio()
    assert ui.get_setting("business_name") == ""


def test_configuracion_para_admin(ui, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from app.ui.pages.configuracion import ConfiguracionPage
    page = ConfiguracionPage(ui, "ADMIN-1")
    assert not page.admin_box.isHidden() and not page.p_audit.isHidden() and page.b_restaurar.isEnabled()
    page.nu_id.setText("tec-3")
    page.nu_pw.setText("secreto3")
    page._crear_tecnico()
    assert UsersRepository(ui).role("TEC-3") == "tecnico" and "creado" in page.msg_us.text()
    fila = next(i for i in range(page.lista.count()) if page.lista.item(i).data(0x0100) == "TEC-3")
    page.lista.setCurrentRow(fila)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("nueva123", True)))
    page._restablecer_pw()
    assert ui.verify_user("TEC-3", "nueva123")
    page._cambiar_activo()
    assert "DESACTIVADO" in page.lista.item(fila).text()
    assert page.lista_audit.count() >= 3


def test_login_usa_el_bloqueo(ui):
    from app.ui.login import LoginDialog
    dlg = LoginDialog(ui)
    dlg.id_input.setText("TEC-2")
    for _ in range(5):
        dlg.pw_input.setText("mala")
        dlg.try_login()
    assert "Espere" in dlg.error.text() and dlg.user_id == ""
