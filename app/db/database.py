import sqlite3

VERSION_ESQUEMA = 2

ESQUEMA = """
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
"""


class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(ESQUEMA)
        self.conn.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
        self.conn.commit()

    def close(self):
        self.conn.close()