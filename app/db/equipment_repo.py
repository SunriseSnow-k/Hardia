import sqlite3

from .repo import Repository


class EquipmentRepository:
    """Consultas de la pantalla Equipos."""

    def __init__(self, repo: Repository):
        self.c = repo.c

    def list_equipment(self, text: str = "") -> list[sqlite3.Row]:
        like = f"%{text.strip()}%"
        return self.c.execute(
            """
            SELECT e.serial, e.description, e.cpu, e.ram, e.storage, e.os,
                   cl.name AS cliente, cl.phone,
                   COUNT(cs.id) AS n_casos, MAX(cs.created_at) AS ultimo,
                   (SELECT c2.code FROM cases c2 WHERE c2.equipment_id = e.id
                    ORDER BY c2.id DESC LIMIT 1) AS ultimo_code
            FROM equipment e
            LEFT JOIN clients cl ON cl.id = e.client_id
            LEFT JOIN cases cs ON cs.equipment_id = e.id
            WHERE e.serial LIKE ? OR e.description LIKE ? OR cl.name LIKE ? OR cl.phone LIKE ?
            GROUP BY e.id
            ORDER BY ultimo DESC, e.id DESC
            """,
            (like,) * 4,
        ).fetchall()