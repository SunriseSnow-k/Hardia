import sqlite3

from .repo import Repository
from .security import hash_password


class UsersRepository:
    """Gestión de técnicos: listado y cambio de contraseña."""

    def __init__(self, repo: Repository):
        self.repo = repo
        self.c = repo.c

    def list_users(self) -> list[sqlite3.Row]:
        return self.c.execute(
            "SELECT tech_id, name, created_at FROM users ORDER BY id").fetchall()

    def change_password(self, tech_id: str, actual: str, nueva: str) -> None:
        if not self.repo.verify_user(tech_id, actual):
            raise ValueError("La contraseña actual no es correcta.")
        if len(nueva) < 6:
            raise ValueError("La nueva contraseña debe tener al menos 6 caracteres.")
        if nueva == actual:
            raise ValueError("La nueva contraseña debe ser distinta de la actual.")
        h, s = hash_password(nueva)
        self.c.execute("UPDATE users SET pw_hash=?, salt=? WHERE tech_id=?",
                       (h, s, tech_id.strip().upper()))
        self.c.commit()