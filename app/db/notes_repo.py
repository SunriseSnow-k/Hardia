"""Notas de un caso: observaciones del técnico, trabajo realizado y notas para el cliente.

Las notas no se editan ni se borran desde el programa: quedan como registro del caso.
"""
import sqlite3

from .repo import Repository

TIPOS = {
    "observacion": "Observación técnica",
    "trabajo": "Trabajo realizado",
    "cliente": "Nota para el cliente",
}
TIPOS_CLIENTE = ("trabajo", "cliente")  # las observaciones técnicas son internas
MAX_TEXTO = 2000


class NotesRepository:
    def __init__(self, repo: Repository):
        self.c = repo.c
        self.c.executescript("""
            CREATE TABLE IF NOT EXISTS case_notes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                case_code  TEXT NOT NULL REFERENCES cases(code),
                kind       TEXT NOT NULL,
                text       TEXT NOT NULL,
                author     TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );
            CREATE INDEX IF NOT EXISTS idx_notes_case ON case_notes(case_code);
        """)
        self.c.commit()

    def add(self, case_code: str, kind: str, text: str, author: str = "") -> int:
        if kind not in TIPOS:
            raise ValueError("Tipo de nota no válido.")
        texto = (text or "").strip()
        if not texto:
            raise ValueError("La nota está vacía.")
        if len(texto) > MAX_TEXTO:
            raise ValueError(f"La nota supera los {MAX_TEXTO} caracteres.")
        if self.c.execute("SELECT 1 FROM cases WHERE code=?", (case_code,)).fetchone() is None:
            raise ValueError(f"No existe el caso {case_code}.")
        cur = self.c.execute(
            "INSERT INTO case_notes(case_code, kind, text, author) VALUES (?,?,?,?)",
            (case_code, kind, texto, (author or "").strip().upper()),
        )
        self.c.commit()
        return cur.lastrowid

    def for_case(self, case_code: str, kinds=None) -> list[sqlite3.Row]:
        """Notas del caso en orden cronológico (la más antigua primero)."""
        sql = "SELECT id, case_code, kind, text, author, created_at FROM case_notes WHERE case_code=?"
        params: list = [case_code]
        if kinds:
            kinds = list(kinds)
            sql += " AND kind IN (" + ",".join("?" * len(kinds)) + ")"
            params += kinds
        return self.c.execute(sql + " ORDER BY id", params).fetchall()
