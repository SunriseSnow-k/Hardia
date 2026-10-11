import json
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
        """Crea o actualiza un equipo. Los datos de hardware solo se
        sobrescriben si se entregan valores nuevos (no vacíos)."""
        serial = serial.strip().upper()
        row = self.c.execute("SELECT id FROM equipment WHERE serial = ?", (serial,)).fetchone()
        if row:
            self.c.execute(
                "UPDATE equipment SET description=?, client_id=?, "
                "cpu=COALESCE(NULLIF(?,''), cpu), ram=COALESCE(NULLIF(?,''), ram), "
                "storage=COALESCE(NULLIF(?,''), storage), os=COALESCE(NULLIF(?,''), os) "
                "WHERE id=?",
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

    def register_intake(self, cliente: str, telefono: str, serie: str,
                        equipo: str, problema: str, prioridad: str = "Media") -> str:
        """Recepción rápida: cliente + equipo + caso en una sola operación."""
        cid = self.add_client(cliente.strip(), telefono.strip())
        eid = self.upsert_equipment(serie, equipo.strip(), cid)
        return self.create_case(eid, problema.strip(), prioridad)

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

    def get_case(self, code: str) -> sqlite3.Row | None:
        return self.c.execute(self._SELECT_CASOS + " WHERE cs.code = ?", (code,)).fetchone()

    def list_cases(self, status: str | None = None) -> list[sqlite3.Row]:
        sql = self._SELECT_CASOS + (" WHERE cs.status = ?" if status else "") + " ORDER BY cs.id DESC"
        return self.c.execute(sql, (status,) if status else ()).fetchall()

    def previous_cases(self, serial: str) -> list[sqlite3.Row]:
        """Casos anteriores de un equipo (aviso de reingreso)."""
        return self.c.execute(
            self._SELECT_CASOS + " WHERE e.serial = ? ORDER BY cs.id DESC",
            (serial.strip().upper(),),
        ).fetchall()

    def other_cases(self, serial: str, exclude_code: str) -> list[sqlite3.Row]:
        return [r for r in self.previous_cases(serial) if r["code"] != exclude_code]

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

    # ---------- Escaneos y diagnósticos por caso ----------
    def save_scan(self, code: str, scan: dict) -> None:
        self.c.execute(
            "INSERT INTO case_scans(case_code, scan) VALUES (?,?) "
            "ON CONFLICT(case_code) DO UPDATE SET scan=excluded.scan",
            (code, json.dumps(scan, ensure_ascii=False)),
        )
        self.c.commit()

    def get_scan(self, code: str) -> dict | None:
        row = self.c.execute("SELECT scan FROM case_scans WHERE case_code=?", (code,)).fetchone()
        return json.loads(row["scan"]) if row else None

    def save_diagnosis(self, code: str, result: dict, method: str = "Reglas") -> None:
        """Guarda el resultado y actualiza la prioridad, el método y el estado del caso."""
        self.c.execute(
            "INSERT INTO diagnoses(case_code, result, method) VALUES (?,?,?)",
            (code, json.dumps(result, ensure_ascii=False), method),
        )
        if result.get("causes"):
            self.c.execute("UPDATE cases SET priority=? WHERE code=?",
                           (result["causes"][0]["priority"], code))
        self.c.execute("UPDATE cases SET method=? WHERE code=?", (method, code))
        self.c.execute("UPDATE cases SET status='En diagnóstico' WHERE code=? AND status='Recibido'",
                       (code,))
        self.c.commit()

    def get_diagnosis(self, code: str) -> dict | None:
        row = self.c.execute(
            "SELECT result, method, created_at FROM diagnoses WHERE case_code=? "
            "ORDER BY id DESC LIMIT 1", (code,),
        ).fetchone()
        if not row:
            return None
        return {"result": json.loads(row["result"]), "method": row["method"],
                "created_at": row["created_at"]}