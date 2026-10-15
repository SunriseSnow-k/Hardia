import sqlite3

from .repo import Repository


class ReportsRepository:
    """Registro de los reportes PDF generados."""

    def __init__(self, repo: Repository):
        self.c = repo.c

    def add(self, case_code: str, kind: str, path: str) -> None:
        self.c.execute(
            "INSERT INTO reports(case_code, kind, path) VALUES (?,?,?)",
            (case_code, kind, path),
        )
        self.c.commit()

    def recent(self, limit: int = 100) -> list[sqlite3.Row]:
        return self.c.execute(
            "SELECT r.id, r.case_code, r.kind, r.path, r.created_at, "
            "       e.description AS equipo, cl.name AS cliente, cs.priority "
            "FROM reports r "
            "JOIN cases cs ON cs.code = r.case_code "
            "JOIN equipment e ON e.id = cs.equipment_id "
            "LEFT JOIN clients cl ON cl.id = e.client_id "
            "ORDER BY r.id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def for_case(self, case_code: str) -> list[sqlite3.Row]:
        """Reportes generados para un caso, del más reciente al más antiguo."""
        return self.c.execute(
            "SELECT id, case_code, kind, path, created_at FROM reports "
            "WHERE case_code = ? ORDER BY id DESC",
            (case_code,),
        ).fetchall()
