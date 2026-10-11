import sqlite3

from .repo import Repository


class ReportsRepository:
    """Registro de los reportes PDF generados."""

    def __init__(self, repo: Repository):
        self.c = repo.c
        self.c.execute(
            "CREATE TABLE IF NOT EXISTS reports ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " case_code TEXT NOT NULL,"
            " kind TEXT NOT NULL,"
            " path TEXT NOT NULL,"
            " created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))"
        )
        self.c.commit()

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