"""Presupuesto y pagos de un caso: solo el acceso a los datos. Las reglas (qué se puede modificar,
quién puede anular, auditoría) están en app/servicios/cobro.py.

Todos los importes son enteros en céntimos.
"""
import sqlite3

from .database import ultimo_id
from .repo import Repository

ESTADOS_PRESUPUESTO = ("Borrador", "Enviado", "Aprobado", "Rechazado")
TIPOS_LINEA = {"servicio": "Servicio", "repuesto": "Repuesto"}
METODOS_PAGO = ("Efectivo", "Tarjeta", "Transferencia", "Billetera digital")


class BillingRepository:
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    def __init__(self, repo: Repository):
        self.repo = repo
        self.c = repo.c

    # ---------- presupuesto ----------
    def quote(self, case_code: str) -> sqlite3.Row | None:
        return self.c.execute("SELECT * FROM quotes WHERE case_code=?", (case_code,)).fetchone()

    def ensure_quote(self, case_code: str) -> None:
        self.c.execute("INSERT OR IGNORE INTO quotes(case_code) VALUES (?)", (case_code,))

    def update_quote(self, case_code: str, **campos) -> None:
        """Actualiza columnas del presupuesto (nombres internos, nunca del usuario)."""
        permitidas = {"status", "discount", "notes", "decided_at", "decided_by"}
        if not campos or set(campos) - permitidas:
            raise ValueError("Campos de presupuesto no válidos.")
        self.ensure_quote(case_code)
        asignaciones = ", ".join(f"{k}=?" for k in campos)
        self.c.execute(f"UPDATE quotes SET {asignaciones}, updated_at=datetime('now','localtime') "
                       "WHERE case_code=?", (*campos.values(), case_code))
        self.c.commit()

    def items(self, case_code: str) -> list[sqlite3.Row]:
        return self.c.execute("SELECT * FROM quote_items WHERE case_code=? ORDER BY id", (case_code,)).fetchall()

    def add_item(self, case_code: str, kind: str, description: str, quantity: int, unit_price: int) -> int:
        self.ensure_quote(case_code)
        cur = self.c.execute(
            "INSERT INTO quote_items(case_code, kind, description, quantity, unit_price) VALUES (?,?,?,?,?)",
            (case_code, kind, description, quantity, unit_price))
        self.c.execute("UPDATE quotes SET updated_at=datetime('now','localtime') WHERE case_code=?", (case_code,))
        self.c.commit()
        return ultimo_id(cur)

    def item(self, item_id: int) -> sqlite3.Row | None:
        return self.c.execute("SELECT * FROM quote_items WHERE id=?", (item_id,)).fetchone()

    def delete_item(self, item_id: int) -> None:
        self.c.execute("DELETE FROM quote_items WHERE id=?", (item_id,))
        self.c.commit()

    def subtotal(self, case_code: str) -> int:
        return self.c.execute("SELECT COALESCE(SUM(quantity * unit_price), 0) FROM quote_items WHERE case_code=?",
                              (case_code,)).fetchone()[0]

    # ---------- pagos ----------
    def payments(self, case_code: str) -> list[sqlite3.Row]:
        return self.c.execute("SELECT * FROM payments WHERE case_code=? ORDER BY id", (case_code,)).fetchall()

    def payment(self, payment_id: int) -> sqlite3.Row | None:
        return self.c.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()

    def add_payment(self, case_code: str, amount: int, method: str, note: str, tech_id: str) -> int:
        cur = self.c.execute("INSERT INTO payments(case_code, amount, method, note, tech_id) VALUES (?,?,?,?,?)",
                             (case_code, amount, method, note, tech_id))
        self.c.commit()
        return ultimo_id(cur)

    def void_payment(self, payment_id: int, tech_id: str, reason: str) -> None:
        self.c.execute("UPDATE payments SET voided_at=datetime('now','localtime'), voided_by=?, void_reason=? "
                       "WHERE id=? AND voided_at=''", (tech_id, reason, payment_id))
        self.c.commit()

    def paid(self, case_code: str) -> int:
        return self.c.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE case_code=? AND voided_at=''",
                              (case_code,)).fetchone()[0]
