"""Cuentas y permisos: inicio de sesión con bloqueo por intentos fallidos, gestión de técnicos
(solo administradores) y registro de auditoría de cada acción sensible.

Política de bloqueo: a partir del 5.º intento fallido seguido, la cuenta se bloquea 30 segundos,
y el tiempo se duplica con cada nuevo fallo hasta un máximo de 15 minutos. Un acceso correcto
reinicia el contador. Los ID inexistentes reciben el mismo mensaje que una contraseña incorrecta.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.db.audit_repo import AuditRepository
from app.db.repo import Repository
from app.db.users_repo import ROLES, UsersRepository, validar_password

log = logging.getLogger(__name__)

MAX_INTENTOS = 5
BLOQUEO_INICIAL = 30  # segundos
BLOQUEO_MAXIMO = 15 * 60
FORMATO = "%Y-%m-%d %H:%M:%S"
CREDENCIALES_INVALIDAS = "ID o contraseña incorrectos."


class AccesoBloqueado(ValueError):
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    def __init__(self, segundos: int):
        self.segundos = segundos
        espera = f"{segundos} segundos" if segundos < 120 else f"{(segundos + 59) // 60} minutos"
        super().__init__(f"Demasiados intentos fallidos. Espere {espera} antes de volver a intentarlo.")


class SinPermiso(PermissionError):
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    pass


@dataclass
class Sesion:
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    tech_id: str
    role: str

    @property
    def es_admin(self) -> bool:
        return self.role == "admin"


def segundos_de_bloqueo(fallos: int) -> int:
    if fallos < MAX_INTENTOS:
        return 0
    return min(BLOQUEO_INICIAL * 2 ** (fallos - MAX_INTENTOS), BLOQUEO_MAXIMO)


def _auditar(repo, accion, tech_id="", detalle=""):
    try:
        AuditRepository(repo).registrar(accion, tech_id, detalle)
    except Exception:  # la auditoría nunca debe impedir la operación; queda en el registro de eventos
        log.exception("No se pudo registrar la auditoría %s", accion)


def iniciar_sesion(repo: Repository, tech_id: str, password: str, ahora: datetime | None = None) -> Sesion:
    ahora = ahora or datetime.now()
    tech_id = (tech_id or "").strip().upper()
    if not tech_id or not password:
        raise ValueError("Ingrese su ID y su contraseña.")
    users = UsersRepository(repo)
    u = users.get(tech_id)
    if u and u["locked_until"]:
        hasta = datetime.strptime(u["locked_until"], FORMATO)
        if hasta > ahora:
            raise AccesoBloqueado(int((hasta - ahora).total_seconds()) + 1)
    if u and users.password_ok(tech_id, password):
        if not u["active"]:
            raise ValueError("Esta cuenta está desactivada. Pida ayuda a un administrador.")
        users.reset_failures(tech_id)
        _auditar(repo, "sesion_iniciada", tech_id)
        return Sesion(tech_id, u["role"])
    _auditar(repo, "sesion_fallida", tech_id)
    if u:
        espera = segundos_de_bloqueo(u["failed_attempts"] + 1)
        bloqueo = (ahora + timedelta(seconds=espera)).strftime(FORMATO) if espera else ""
        users.register_failure(tech_id, bloqueo)
        if espera:
            _auditar(repo, "cuenta_bloqueada", tech_id, f"{espera} s")
            raise AccesoBloqueado(espera)
    raise ValueError(CREDENCIALES_INVALIDAS)


def crear_cuenta_inicial(repo: Repository, tech_id: str, password: str) -> Sesion:
    """Primer uso: la primera cuenta es administrador. Falla si ya hay cuentas."""
    if repo.count_users():
        raise SinPermiso("Ya existen cuentas en este programa.")
    repo.create_user(tech_id, password, role="admin")
    _auditar(repo, "usuario_creado", tech_id, "cuenta inicial (administrador)")
    return Sesion(tech_id.strip().upper(), "admin")


# ---------------- Gestión (solo administradores) ----------------
def requerir_admin(repo: Repository, actor: str) -> None:
    if UsersRepository(repo).role(actor) != "admin":
        raise SinPermiso("Solo un administrador puede realizar esta acción.")


def crear_tecnico(repo: Repository, actor: str, tech_id: str, password: str, role: str = "tecnico") -> None:
    requerir_admin(repo, actor)
    if role not in ROLES:
        raise ValueError("Rol no válido.")
    repo.create_user(tech_id, password, role=role)
    _auditar(repo, "usuario_creado", actor, f"{tech_id.strip().upper()} ({ROLES[role]})")


def restablecer_password(repo: Repository, actor: str, tech_id: str, nueva: str) -> None:
    """Para el técnico que olvidó su contraseña: el administrador le asigna una nueva."""
    requerir_admin(repo, actor)
    users = UsersRepository(repo)
    if users.get(tech_id) is None:
        raise ValueError("No existe ese técnico.")
    with repo.transaccion():
        users.set_password(tech_id, nueva)
        users.reset_failures(tech_id)
        _auditar(repo, "contrasena_restablecida", actor, tech_id.strip().upper())


def _no_dejar_sin_admin(users: UsersRepository, tech_id: str) -> None:
    u = users.get(tech_id)
    if u and u["role"] == "admin" and u["active"] and users.active_admins() <= 1:
        raise ValueError("Debe quedar al menos un administrador activo.")


def cambiar_rol(repo: Repository, actor: str, tech_id: str, role: str) -> None:
    requerir_admin(repo, actor)
    users = UsersRepository(repo)
    if users.get(tech_id) is None:
        raise ValueError("No existe ese técnico.")
    if role != "admin":
        _no_dejar_sin_admin(users, tech_id)
    with repo.transaccion():
        users.set_role(tech_id, role)
        _auditar(repo, "rol_cambiado", actor, f"{tech_id.strip().upper()} → {ROLES[role]}")


def cambiar_activo(repo: Repository, actor: str, tech_id: str, activo: bool) -> None:
    requerir_admin(repo, actor)
    users = UsersRepository(repo)
    if users.get(tech_id) is None:
        raise ValueError("No existe ese técnico.")
    if not activo:
        if tech_id.strip().upper() == actor.strip().upper():
            raise ValueError("No puede desactivar su propia cuenta.")
        _no_dejar_sin_admin(users, tech_id)
    with repo.transaccion():
        users.set_active(tech_id, activo)
        _auditar(repo, "usuario_activado" if activo else "usuario_desactivado", actor, tech_id.strip().upper())


def cambiar_mi_password(repo: Repository, tech_id: str, actual: str, nueva: str) -> None:
    validar_password(nueva)
    with repo.transaccion():
        UsersRepository(repo).change_password(tech_id, actual, nueva)
        _auditar(repo, "contrasena_cambiada", tech_id)


def auditar(repo: Repository, accion: str, tech_id: str = "", detalle: str = "") -> None:
    """Para acciones registradas desde otras pantallas (copias, datos del taller)."""
    _auditar(repo, accion, tech_id, detalle)
