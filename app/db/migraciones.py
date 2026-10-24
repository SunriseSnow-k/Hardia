"""Migraciones del esquema de la base de datos, numeradas con PRAGMA user_version.

Al abrir la base se aplican, en orden y cada una en su propia transacción, las migraciones cuyo
número es mayor que la versión guardada. Antes de modificar una base que ya tiene datos se crea
una copia de seguridad. Una base creada por una versión MÁS NUEVA del programa no se abre, para
no dañar datos que esta versión no conoce.

Para cambiar el esquema: agregar una función `_vN(conn)` al final de MIGRACIONES con el número
siguiente. Nunca modificar una migración ya publicada; las bases de los talleres ya la aplicaron.
"""
import sqlite3
from pathlib import Path

SAFETY_PREFIX = "antes_de_actualizar_"


class QAKM_BaseMasNueva(RuntimeError):
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    """La base de datos fue creada por una versión más nueva del programa."""


def _ejecutar(conn, sql: str) -> None:
    """Como executescript, pero sin el COMMIT implícito (para poder usarlo dentro de una transacción)."""
    for sentencia in sql.split(";"):
        if sentencia.strip():
            conn.execute(sentencia)


def _columnas(conn, tabla: str) -> set[str]:
    return {f[1] for f in conn.execute(f"PRAGMA table_info({tabla})")}


# ---------------- Migraciones ----------------
def _v3_esquema_consolidado(conn) -> None:
    """Las versiones 1 y 2 creaban parte de las tablas al usarlas por primera vez. Esta migración
    reúne todo el esquema en un solo lugar; es idempotente, así que sirve igual para una base
    nueva que para una creada por cualquier versión anterior."""
    _ejecutar(conn, """
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            tech_id    TEXT NOT NULL UNIQUE,
            name       TEXT NOT NULL,
            pw_hash    TEXT NOT NULL,
            salt       TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS clients (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT NOT NULL,
            phone TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS equipment (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            serial      TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL,
            client_id   INTEGER REFERENCES clients(id),
            cpu         TEXT DEFAULT '',
            ram         TEXT DEFAULT '',
            storage     TEXT DEFAULT '',
            os          TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS cases (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            code         TEXT NOT NULL UNIQUE,
            equipment_id INTEGER NOT NULL REFERENCES equipment(id),
            problem      TEXT NOT NULL,
            priority     TEXT NOT NULL DEFAULT 'Media',
            status       TEXT NOT NULL DEFAULT 'Recibido',
            method       TEXT NOT NULL DEFAULT 'Reglas',
            created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS case_scans (
            case_code TEXT PRIMARY KEY REFERENCES cases(code),
            scan      TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS diagnoses (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            case_code  TEXT NOT NULL REFERENCES cases(code),
            result     TEXT NOT NULL,
            method     TEXT NOT NULL DEFAULT 'Reglas',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_cases_equipment ON cases(equipment_id);
        CREATE INDEX IF NOT EXISTS idx_diagnoses_case ON diagnoses(case_code);

        CREATE TABLE IF NOT EXISTS hardware_captures (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            case_code     TEXT NOT NULL REFERENCES cases(code),
            equipment_id  INTEGER NOT NULL REFERENCES equipment(id),
            captured_at   TEXT NOT NULL,
            recorded_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            source        TEXT NOT NULL,
            source_file   TEXT,
            schema_version INTEGER NOT NULL,
            host          TEXT, manufacturer TEXT, model TEXT, serial TEXT, uuid TEXT,
            payload       TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_captures_equipment ON hardware_captures(equipment_id, captured_at);
        CREATE INDEX IF NOT EXISTS idx_captures_case ON hardware_captures(case_code);
        CREATE TABLE IF NOT EXISTS equipment_identifiers (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id INTEGER NOT NULL REFERENCES equipment(id),
            kind         TEXT NOT NULL,
            value        TEXT NOT NULL,
            first_seen   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(kind, value)
        );

        CREATE TABLE IF NOT EXISTS health_benchmarks (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            case_code  TEXT NOT NULL REFERENCES cases(code),
            capture_id INTEGER REFERENCES hardware_captures(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            payload    TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_bench_case ON health_benchmarks(case_code);
        CREATE TABLE IF NOT EXISTS health_results (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            case_code    TEXT NOT NULL REFERENCES cases(code),
            capture_id   INTEGER REFERENCES hardware_captures(id),
            benchmark_id INTEGER REFERENCES health_benchmarks(id),
            created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            indice       REAL,
            payload      TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_health_case ON health_results(case_code);
        CREATE TABLE IF NOT EXISTS health_diag_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            case_code  TEXT NOT NULL REFERENCES cases(code),
            clave      TEXT NOT NULL,
            texto      TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(case_code, clave)
        );

        CREATE TABLE IF NOT EXISTS case_notes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            case_code  TEXT NOT NULL REFERENCES cases(code),
            kind       TEXT NOT NULL,
            text       TEXT NOT NULL,
            author     TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_notes_case ON case_notes(case_code);

        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_code TEXT NOT NULL,
            kind TEXT NOT NULL,
            path TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS service_orders (
            case_code      TEXT PRIMARY KEY REFERENCES cases(code),
            accessories    TEXT NOT NULL DEFAULT '',
            condition      TEXT NOT NULL DEFAULT '',
            observations   TEXT NOT NULL DEFAULT '',
            estimated_date TEXT NOT NULL DEFAULT '',
            received_by    TEXT NOT NULL DEFAULT '',
            created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    if "doc_id" not in _columnas(conn, "clients"):
        conn.execute("ALTER TABLE clients ADD COLUMN doc_id TEXT NOT NULL DEFAULT ''")
    _ejecutar(conn, """
        CREATE INDEX IF NOT EXISTS idx_clients_doc ON clients(doc_id);
        CREATE INDEX IF NOT EXISTS idx_cases_created ON cases(created_at);
        CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
        CREATE INDEX IF NOT EXISTS idx_clients_name ON clients(name);
        CREATE INDEX IF NOT EXISTS idx_reports_case ON reports(case_code);
        CREATE INDEX IF NOT EXISTS idx_reports_created ON reports(created_at)
    """)


def _v4_roles_y_auditoria(conn) -> None:
    """Roles (administrador/técnico), cuentas desactivables, bloqueo por intentos fallidos y
    registro de auditoría. El técnico más antiguo (quien instaló el programa) queda como administrador."""
    _ejecutar(conn, """
        ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'tecnico';
        ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1;
        ALTER TABLE users ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE users ADD COLUMN locked_until TEXT NOT NULL DEFAULT '';
        UPDATE users SET role = 'admin' WHERE id = (SELECT MIN(id) FROM users);
        CREATE TABLE audit_log (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            tech_id TEXT NOT NULL DEFAULT '',
            action  TEXT NOT NULL,
            detail  TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX idx_audit_at ON audit_log(at)
    """)


def _v5_presupuesto_y_cobro(conn) -> None:
    """Presupuesto por caso (líneas de servicio y repuestos) y pagos. Los importes se guardan en
    céntimos (enteros) para no acumular errores de redondeo. Los pagos nunca se borran: se anulan
    indicando el motivo."""
    _ejecutar(conn, """
        CREATE TABLE quotes (
            case_code   TEXT PRIMARY KEY REFERENCES cases(code),
            status      TEXT NOT NULL DEFAULT 'Borrador',
            discount    INTEGER NOT NULL DEFAULT 0,
            notes       TEXT NOT NULL DEFAULT '',
            decided_at  TEXT NOT NULL DEFAULT '',
            decided_by  TEXT NOT NULL DEFAULT '',
            updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE quote_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            case_code   TEXT NOT NULL REFERENCES cases(code),
            kind        TEXT NOT NULL,
            description TEXT NOT NULL,
            quantity    INTEGER NOT NULL DEFAULT 1,
            unit_price  INTEGER NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX idx_quote_items_case ON quote_items(case_code);
        CREATE TABLE payments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            case_code   TEXT NOT NULL REFERENCES cases(code),
            amount      INTEGER NOT NULL,
            method      TEXT NOT NULL,
            note        TEXT NOT NULL DEFAULT '',
            tech_id     TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            voided_at   TEXT NOT NULL DEFAULT '',
            voided_by   TEXT NOT NULL DEFAULT '',
            void_reason TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX idx_payments_case ON payments(case_code);
        CREATE INDEX idx_payments_created ON payments(created_at)
    """)


MIGRACIONES = [
    (3, "Esquema consolidado", _v3_esquema_consolidado),
    (4, "Roles, bloqueo de acceso y auditoría", _v4_roles_y_auditoria),
    (5, "Presupuesto y cobro", _v5_presupuesto_y_cobro),
]
VERSION_ACTUAL = MIGRACIONES[-1][0]


# ---------------- Aplicación ----------------
def version(conn) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _tiene_datos(conn) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cases'").fetchone() is not None


def migrar(conn, carpeta_copias=None) -> list[int]:
    """Aplica las migraciones pendientes y devuelve sus números. Si la base ya tenía datos y se
    indica `carpeta_copias`, antes se guarda una copia de seguridad de la base tal como estaba."""
    actual = version(conn)
    if actual > VERSION_ACTUAL:
        raise QAKM_BaseMasNueva(
            f"La base de datos fue creada por una versión más nueva del programa (esquema {actual}; "
            f"esta versión conoce hasta el {VERSION_ACTUAL}). Instale la versión más reciente.")
    pendientes = [m for m in MIGRACIONES if m[0] > actual]
    if not pendientes:
        return []
    if carpeta_copias is not None and _tiene_datos(conn):
        from app import backup  # importación diferida: backup no depende de la capa de datos
        backup.create_backup(conn, carpeta_copias, SAFETY_PREFIX)
    aplicadas = []
    for numero, _descripcion, aplicar in pendientes:
        with conn.transaccion():
            aplicar(conn)
            conn.execute(f"PRAGMA user_version = {int(numero)}")
        aplicadas.append(numero)
    return aplicadas


def comprobar_compatible(path) -> None:
    """Para validar copias de seguridad: rechaza las de una versión más nueva del programa."""
    con = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    try:
        v = version(con)
    finally:
        con.close()
    if v > VERSION_ACTUAL:
        raise ValueError("La copia fue creada por una versión más nueva del programa; "
                         "instale la versión más reciente para restaurarla.")
