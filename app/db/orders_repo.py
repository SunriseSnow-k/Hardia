"""Orden de servicio: lo que el taller recibe junto con el equipo (accesorios, estado físico,
observaciones y fecha estimada de entrega). Es el comprobante que firma el cliente al dejar el equipo.

Una orden por caso; se puede corregir mientras el caso no se haya entregado.
"""
import sqlite3
from datetime import date

from .repo import Repository

ACCESORIOS = ("Cargador", "Batería", "Cable de poder", "Mouse", "Funda o maletín", "Disco externo")
MAX_TEXTO = 500
TERMINOS_PREDETERMINADOS = (
    "El diagnóstico se informa antes de realizar cualquier trabajo con costo.\n"
    "El taller no se responsabiliza por la información guardada en el equipo; se recomienda "
    "respaldarla antes de dejarlo.\n"
    "Presente esta orden (o su documento) para retirar el equipo.\n"
    "Los equipos no retirados dentro de los 90 días de avisado el cliente podrán generar un costo "
    "de almacenamiento."
)


def _limpio(texto, campo: str) -> str:
    texto = (texto or "").strip()
    if len(texto) > MAX_TEXTO:
        raise ValueError(f"{campo} supera los {MAX_TEXTO} caracteres.")
    return texto


class OrdersRepository:
    def __init__(self, repo: Repository):
        self.repo = repo
        self.c = repo.c
        self.c.execute("""
            CREATE TABLE IF NOT EXISTS service_orders (
                case_code      TEXT PRIMARY KEY REFERENCES cases(code),
                accessories    TEXT NOT NULL DEFAULT '',
                condition      TEXT NOT NULL DEFAULT '',
                observations   TEXT NOT NULL DEFAULT '',
                estimated_date TEXT NOT NULL DEFAULT '',
                received_by    TEXT NOT NULL DEFAULT '',
                created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            )""")
        self.c.commit()

    def save(self, case_code: str, accessories="", condition="", observations="",
             estimated_date="", received_by="") -> None:
        """Crea o corrige la orden del caso. `accessories` puede ser texto o una lista."""
        caso = self.c.execute("SELECT status FROM cases WHERE code=?", (case_code,)).fetchone()
        if caso is None:
            raise ValueError(f"No existe el caso {case_code}.")
        if caso["status"] == "Entregado":
            raise ValueError("El equipo ya fue entregado: la orden no se puede modificar.")
        if not isinstance(accessories, str):
            accessories = ", ".join(a.strip() for a in accessories if a and a.strip())
        estimada = (estimated_date or "").strip()
        if estimada:
            try:
                date.fromisoformat(estimada)
            except ValueError:
                raise ValueError("La fecha estimada de entrega no es válida.")
        valores = (_limpio(accessories, "Los accesorios"), _limpio(condition, "El estado físico"),
                   _limpio(observations, "Las observaciones"), estimada,
                   (received_by or "").strip().upper())
        self.c.execute(
            "INSERT INTO service_orders(case_code, accessories, condition, observations, estimated_date, "
            "received_by) VALUES (?,?,?,?,?,?) ON CONFLICT(case_code) DO UPDATE SET "
            "accessories=excluded.accessories, condition=excluded.condition, "
            "observations=excluded.observations, estimated_date=excluded.estimated_date, "
            "received_by=COALESCE(NULLIF(excluded.received_by,''), received_by)",
            (case_code, *valores),
        )
        self.c.commit()

    def get(self, case_code: str) -> sqlite3.Row | None:
        return self.c.execute("SELECT * FROM service_orders WHERE case_code=?", (case_code,)).fetchone()

    def terms(self) -> list[str]:
        """Condiciones del servicio (una por línea), editables en Configuración."""
        texto = self.repo.get_setting("service_terms", TERMINOS_PREDETERMINADOS)
        return [t.strip() for t in texto.splitlines() if t.strip()]
