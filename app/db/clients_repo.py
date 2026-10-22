"""Documento de identidad del cliente (opcional). La columna clients.doc_id la crea la
migración 3 (app/db/migraciones.py); los clientes anteriores quedan con el documento vacío."""
import re
import sqlite3

from .repo import Repository

MAX_DOC = 20


def normalize_doc(doc: str) -> str:
    """DNI, RUC o carné de extranjería: sin espacios ni guiones, en mayúsculas."""
    d = re.sub(r"[\s\-.]", "", doc or "").upper()
    if len(d) > MAX_DOC:
        raise ValueError(f"El documento no puede superar los {MAX_DOC} caracteres.")
    if d and not re.fullmatch(r"[0-9A-Z]+", d):
        raise ValueError("El documento solo puede tener letras y números.")
    return d


class ClientsRepository:
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    def __init__(self, repo: Repository):
        self.c = repo.c

    def set_doc(self, client_id: int, doc: str) -> None:
        self.c.execute("UPDATE clients SET doc_id=? WHERE id=?", (normalize_doc(doc), client_id))
        self.c.commit()

    def set_doc_for_case(self, case_code: str, doc: str) -> None:
        """Guarda el documento en el cliente del caso. Un documento vacío no borra el anterior."""
        d = normalize_doc(doc)
        if not d:
            return
        row = self.c.execute(
            "SELECT e.client_id FROM cases cs JOIN equipment e ON e.id = cs.equipment_id "
            "WHERE cs.code=?", (case_code,)).fetchone()
        if row is None or row[0] is None:
            raise ValueError(f"No existe el caso {case_code} o no tiene cliente.")
        self.set_doc(row[0], d)

    def doc_for_case(self, case_code: str) -> str:
        row = self.c.execute(
            "SELECT cl.doc_id FROM cases cs JOIN equipment e ON e.id = cs.equipment_id "
            "LEFT JOIN clients cl ON cl.id = e.client_id WHERE cs.code=?", (case_code,)).fetchone()
        return (row[0] or "") if row else ""

    def find_by_doc(self, doc: str) -> sqlite3.Row | None:
        """Cliente más reciente con ese documento (para completar la recepción)."""
        try:
            d = normalize_doc(doc)
        except ValueError:
            return None
        if not d:
            return None
        return self.c.execute(
            "SELECT id, name, phone, doc_id FROM clients WHERE doc_id=? ORDER BY id DESC LIMIT 1",
            (d,)).fetchone()
