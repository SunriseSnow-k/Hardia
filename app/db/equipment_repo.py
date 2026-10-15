import sqlite3

from .repo import Repository
from .search_repo import _CAPTURA, _ESC, MAX_PALABRAS, _like


class EquipmentRepository:
    """Consultas de la pantalla Equipos (solo lectura)."""

    _CAMPOS = ("e.serial", "e.description", "cl.name", "cl.phone", "cl.doc_id", _CAPTURA)

    def __init__(self, repo: Repository):
        self.c = repo.c

    def list_equipment(self, text: str = "") -> list[sqlite3.Row]:
        """Busca por serie, equipo, cliente, teléfono, documento y por la marca o el modelo
        de cualquier captura del equipo. Cada palabra debe aparecer en algún campo."""
        conds, params = [], []
        for tok in (text or "").split()[:MAX_PALABRAS]:
            partes = [c if "?" in c else f"{c} LIKE ? {_ESC}" for c in self._CAMPOS]
            conds.append("(" + " OR ".join(partes) + ")")
            params += [_like(tok)] * sum(p.count("?") for p in partes)
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        return self.c.execute(
            f"""
            SELECT e.id AS equipment_id, e.serial, e.description, e.cpu, e.ram, e.storage, e.os,
                   cl.name AS cliente, cl.phone,
                   COUNT(cs.id) AS n_casos, MAX(cs.created_at) AS ultimo,
                   (SELECT c2.code FROM cases c2 WHERE c2.equipment_id = e.id
                    ORDER BY c2.id DESC LIMIT 1) AS ultimo_code,
                   (SELECT c2.status FROM cases c2 WHERE c2.equipment_id = e.id
                    ORDER BY c2.id DESC LIMIT 1) AS ultimo_status
            FROM equipment e
            LEFT JOIN clients cl ON cl.id = e.client_id
            LEFT JOIN cases cs ON cs.equipment_id = e.id
            {where}
            GROUP BY e.id
            ORDER BY ultimo DESC, e.id DESC
            """,
            params,
        ).fetchall()
