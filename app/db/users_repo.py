import sqlite3

from .repo import Repository
from .security import hash_password, verify_password

ROLES = {"admin": "Administrador", "tecnico": "Técnico"}
MIN_PASSWORD = 6


def validar_password(nueva: str) -> None:
    if len(nueva) < MIN_PASSWORD:
        raise ValueError(f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres.")


class UsersRepository:
    """Cuentas de los técnicos: listado, roles, activación, contraseñas e intentos fallidos.
    Los permisos (quién puede hacer qué) se comprueban en app/servicios/cuentas.py."""

    def __init__(self, repo: Repository):
        self.repo = repo
        self.c = repo.c

    @staticmethod
    def _id(tech_id: str) -> str:
        return (tech_id or "").strip().upper()

    def list_users(self) -> list[sqlite3.Row]:
        return self.c.execute(
            "SELECT tech_id, name, role, active, created_at FROM users ORDER BY id").fetchall()

    def get(self, tech_id: str) -> sqlite3.Row | None:
        return self.c.execute("SELECT * FROM users WHERE tech_id=?", (self._id(tech_id),)).fetchone()

    def role(self, tech_id: str) -> str | None:
        u = self.get(tech_id)
        return u["role"] if u and u["active"] else None

    def active_admins(self) -> int:
        return self.c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]

    def password_ok(self, tech_id: str, password: str) -> bool:
        u = self.get(tech_id)
        return bool(u) and verify_password(password, u["pw_hash"], u["salt"])

    def set_password(self, tech_id: str, nueva: str) -> None:
        validar_password(nueva)
        h, s = hash_password(nueva)
        self.c.execute("UPDATE users SET pw_hash=?, salt=? WHERE tech_id=?", (h, s, self._id(tech_id)))
        self.c.commit()

    def change_password(self, tech_id: str, actual: str, nueva: str) -> None:
        if not self.repo.verify_user(tech_id, actual):
            raise ValueError("La contraseña actual no es correcta.")
        if nueva == actual:
            raise ValueError("La nueva contraseña debe ser distinta de la actual.")
        self.set_password(tech_id, nueva)

    def set_role(self, tech_id: str, role: str) -> None:
        if role not in ROLES:
            raise ValueError("Rol no válido.")
        self.c.execute("UPDATE users SET role=? WHERE tech_id=?", (role, self._id(tech_id)))
        self.c.commit()

    def set_active(self, tech_id: str, active: bool) -> None:
        self.c.execute("UPDATE users SET active=?, failed_attempts=0, locked_until='' WHERE tech_id=?",
                       (1 if active else 0, self._id(tech_id)))
        self.c.commit()

    # ---------- intentos fallidos ----------
    def register_failure(self, tech_id: str, locked_until: str = "") -> int:
        """Suma un intento fallido y, si se indica, bloquea la cuenta hasta esa fecha. Devuelve el total."""
        self.c.execute("UPDATE users SET failed_attempts = failed_attempts + 1, "
                       "locked_until = CASE WHEN ? <> '' THEN ? ELSE locked_until END WHERE tech_id=?",
                       (locked_until, locked_until, self._id(tech_id)))
        self.c.commit()
        u = self.get(tech_id)
        return u["failed_attempts"] if u else 0

    def reset_failures(self, tech_id: str) -> None:
        self.c.execute("UPDATE users SET failed_attempts=0, locked_until='' WHERE tech_id=?", (self._id(tech_id),))
        self.c.commit()
