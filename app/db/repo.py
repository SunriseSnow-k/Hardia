import sqlite3
from .database import Database
from .security import hash_password, verify_password

ESTADOS = ("Recibido", "En diagnóstico", "Listo", "Entregado")
PRIORIDADES = ("Alta", "Media", "Baja")


class Repository:
    def __init__(self, db: Database):
        self.db = db
        self.c = db.conn

    # ---------- Usuarios ----------
    def count_users(self) -> int:
        return self.c.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def create_user(self, tech_id: str, password: str, name: str = "") -> None:
        tech_id = tech_id.strip().upper()
        if not tech_id:
            raise ValueError("El ID de técnico es obligatorio.")
        if len(password) < 6:
            raise ValueError("La contraseña debe tener al menos 6 caracteres.")
        h, s = hash_password(password)
        try:
            self.c.execute(
                "INSERT INTO users(tech_id, name, pw_hash, salt) VALUES (?,?,?,?)",
                (tech_id, name or tech_id, h, s),
            )
            self.c.commit()
        except sqlite3.IntegrityError:
            raise ValueError("Ese ID de técnico ya existe.")

    def verify_user(self, tech_id: str, password: str) -> bool:
        row = self.c.execute(
            "SELECT pw_hash, salt FROM users WHERE tech_id = ?",
            (tech_id.strip().upper(),),
        ).fetchone()
        return bool(row) and verify_password(password, row["pw_hash"], row["salt"])

    # ---------- Clientes y equipos ----------
    def add_client(self, name: str, phone: str = "") -> int:
        row = self.c.execute(
            "SELECT id FROM clients WHERE name = ? AND phone = ?", (name, phone)
        ).fetchone()
        if row:
            return row["id"]
        cur = self.c.execute("INSERT INTO clients(name, phone) VALUES (?,?)", (name, phone))
        self.c.commit()
        return cur.lastrowid

    def upsert_equipment(self, serial: str, description: str, client_id: int,
                         cpu="", ram="", storage="", os_name="") -> int:
        serial = serial.strip().upper()
        row = self.c.execute("SELECT id FROM equipment WHERE serial = ?", (serial,)).fetchone()
        if row:
            self.c.execute(
                "UPDATE equipment SET description=?, client_id=?, cpu=?, ram=?, storage=?, os=? WHERE id=?",
                (description, client_id, cpu, ram, storage, os_name, row["id"]),
            )
            self.c.commit()
            return row["id"]
        cur = self.c.execute(
            "INSERT INTO equipment(serial, description, client_id, cpu, ram, storage, os) "
            "VALUES (?,?,?,?,?,?,?)",
            (serial, description, client_id, cpu, ram, storage, os_name),
        )
        self.c.commit()
        return cur.lastrowid

    # ---------- Casos ----------
    def create_case(self, equipment_id: int, problem: str, priority: str = "Media",
                    status: str = "Recibido", method: str = "Reglas") -> str:
        n = self.c.execute("SELECT COALESCE(MAX(id),0)+1 FROM cases").fetchone()[0]
        code = f"C-{n:03d}"
        self.c.execute(
            "INSERT INTO cases(code, equipment_id, problem, priority, status, method) "
            "VALUES (?,?,?,?,?,?)",
            (code, equipment_id, problem, priority, status, method),
        )
        self.c.commit()
        return code

    def update_case_status(self, code: str, status: str) -> None:
        self.c.execute("UPDATE cases SET status=? WHERE code=?", (status, code))
        self.c.commit()

    _SELECT_CASOS = """
        SELECT cs.code, cs.problem, cs.priority, cs.status, cs.method, cs.created_at,
               e.serial, e.description AS equipo, cl.name AS cliente, cl.phone
        FROM cases cs
        JOIN equipment e ON e.id = cs.equipment_id
        LEFT JOIN clients cl ON cl.id = e.client_id
    """

    def list_cases(self, status: str | None = None) -> list[sqlite3.Row]:
        sql = self._SELECT_CASOS + (" WHERE cs.status = ?" if status else "") + " ORDER BY cs.id DESC"
        return self.c.execute(sql, (status,) if status else ()).fetchall()

    def previous_cases(self, serial: str) -> list[sqlite3.Row]:
        """Casos anteriores de un equipo (aviso de reingreso)."""
        return self.c.execute(
            self._SELECT_CASOS + " WHERE e.serial = ? ORDER BY cs.id DESC",
            (serial.strip().upper(),),
        ).fetchall()

    def search(self, text: str) -> list[sqlite3.Row]:
        """Búsqueda global por cliente, teléfono, serie, equipo o código."""
        like = f"%{text.strip()}%"
        return self.c.execute(
            self._SELECT_CASOS + """
            WHERE cl.name LIKE ? OR cl.phone LIKE ? OR e.serial LIKE ?
               OR e.description LIKE ? OR cs.code LIKE ?
            ORDER BY cs.id DESC LIMIT 20""",
            (like,) * 5,
        ).fetchall()

    def count_by_status(self) -> dict[str, int]:
        filas = self.c.execute("SELECT status, COUNT(*) n FROM cases GROUP BY status").fetchall()
        return {f["status"]: f["n"] for f in filas}