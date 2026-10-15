"""Capturas de hardware por equipo y caso, e identificación fiable de equipos.

Cada captura se conserva: volver a analizar un equipo agrega una captura nueva y
nunca reemplaza las anteriores. Los identificadores (UUID, serie, serie de la placa
y MAC) permiten reconocer un equipo sin depender de su nombre.
"""
import json
import sqlite3

from app.hardware.inventory import FUERTES, identifiers_from_scan

from .database import transaccional
from .repo import Repository

ORIGENES = {"local_scan": "Escaneo local", "imported_file": "Archivo importado", "legacy": "Migrado"}


def _resumen(scan: dict) -> dict:
    r = scan.get("summary")
    return r if isinstance(r, dict) else {}


class HardwareRepository:
    def __init__(self, repo: Repository):
        self.repo = repo
        self.c = repo.c

    # ---------- identificación ----------

    @transaccional
    def add_identifiers(self, equipment_id: int, identifiers) -> list[dict]:
        """Asocia identificadores al equipo. Si alguno ya pertenece a OTRO equipo no se
        reasigna: se devuelve como conflicto para que el técnico lo revise."""
        conflictos = []
        for kind, value in identifiers:
            row = self.c.execute("SELECT equipment_id FROM equipment_identifiers WHERE kind=? AND value=?",
                                 (kind, value)).fetchone()
            if row is None:
                self.c.execute("INSERT INTO equipment_identifiers(equipment_id, kind, value) VALUES (?,?,?)",
                               (equipment_id, kind, value))
            elif row[0] != equipment_id:
                conflictos.append({"kind": kind, "value": value, "equipment_id": row[0]})
        self.c.commit()
        return conflictos

    def _describe(self, equipment_id: int, tipos) -> dict:
        e = self.c.execute("SELECT id, serial, description FROM equipment WHERE id=?",
                           (equipment_id,)).fetchone()
        return {"equipment_id": e["id"], "serial": e["serial"], "description": e["description"],
                "matched": sorted(tipos)}

    def identify(self, identifiers) -> dict:
        """¿A qué equipo registrado corresponden estos identificadores?
        - encontrado: un solo equipo coincide por un identificador fuerte (UUID o serie).
        - ambiguo: identificadores fuertes que apuntan a equipos distintos.
        - probable: solo coincide algo débil (MAC): conviene confirmar.
        - nuevo: no hay coincidencias."""
        coincidencias: dict[int, set] = {}
        for kind, value in identifiers:
            filas = self.c.execute("SELECT equipment_id FROM equipment_identifiers WHERE kind=? AND value=?",
                                   (kind, value)).fetchall()
            if kind == "serial":  # equipos registrados antes de existir los identificadores
                filas += self.c.execute("SELECT id FROM equipment WHERE serial=?", (value,)).fetchall()
            for f in filas:
                coincidencias.setdefault(f[0], set()).add(kind)
        fuertes = [e for e, tipos in coincidencias.items() if tipos & set(FUERTES)]
        if len(fuertes) == 1:
            return {"status": "encontrado", "equipment_id": fuertes[0],
                    "candidates": [self._describe(fuertes[0], coincidencias[fuertes[0]])]}
        if len(fuertes) > 1:
            return {"status": "ambiguo", "equipment_id": None,
                    "candidates": [self._describe(e, coincidencias[e]) for e in sorted(fuertes)]}
        if coincidencias:
            return {"status": "probable", "equipment_id": None,
                    "candidates": [self._describe(e, t) for e, t in sorted(coincidencias.items())]}
        return {"status": "nuevo", "equipment_id": None, "candidates": []}

    def identify_scan(self, scan: dict) -> dict:
        return self.identify(identifiers_from_scan(scan))

    # ---------- capturas ----------
    @transaccional
    def save_capture(self, case_code: str, scan: dict) -> dict:
        """Guarda una captura nueva vinculada al caso y al equipo. Conserva las anteriores y
        mantiene al día el escaneo 'actual' del caso que usan el diagnóstico y los reportes."""
        equipment_id = self.repo.equipment_id_of_case(case_code)
        if equipment_id is None:
            raise ValueError(f"No existe el caso {case_code}.")
        inv: dict = scan["inventory"] if isinstance(scan.get("inventory"), dict) else {}
        ident: dict = inv["identity"] if isinstance(inv.get("identity"), dict) else {}
        prov: dict = scan["provenance"] if isinstance(scan.get("provenance"), dict) else {}
        cur = self.c.execute(
            "INSERT INTO hardware_captures(case_code, equipment_id, captured_at, source, source_file, "
            "schema_version, host, manufacturer, model, serial, uuid, payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (case_code, equipment_id, str(scan.get("scanned_at") or ""), prov.get("how", "local_scan"),
             prov.get("file"), int(scan.get("version") or 1), scan.get("host"), ident.get("manufacturer"),
             ident.get("model"), ident.get("serial") or _resumen(scan).get("serial"),
             ident.get("uuid"), json.dumps(scan, ensure_ascii=False)))
        self.c.commit()
        self.repo.save_scan(case_code, scan)
        conflictos = self.add_identifiers(equipment_id, identifiers_from_scan(scan))
        return {"capture_id": cur.lastrowid, "equipment_id": equipment_id, "conflicts": conflictos}

    def captures_for_equipment(self, equipment_id: int) -> list[sqlite3.Row]:
        return self.c.execute(
            "SELECT id, case_code, captured_at, recorded_at, source, source_file, schema_version "
            "FROM hardware_captures WHERE equipment_id=? ORDER BY captured_at DESC, id DESC",
            (equipment_id,)).fetchall()

    def captures_for_case(self, case_code: str) -> list[sqlite3.Row]:
        return self.c.execute(
            "SELECT id, case_code, captured_at, recorded_at, source, source_file, schema_version "
            "FROM hardware_captures WHERE case_code=? ORDER BY captured_at DESC, id DESC",
            (case_code,)).fetchall()

    def get_capture(self, capture_id: int) -> dict | None:
        row = self.c.execute("SELECT * FROM hardware_captures WHERE id=?", (capture_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        return d

    def latest_capture(self, equipment_id: int, exclude_case: str | None = None) -> dict | None:
        for r in self.captures_for_equipment(equipment_id):
            if exclude_case is None or r["case_code"] != exclude_case:
                return self.get_capture(r["id"])
        return None

    # ---------- datos anteriores ----------
    @transaccional
    def migrate_legacy(self) -> int:
        """Convierte los escaneos guardados antes de existir las capturas. No borra ni
        modifica nada: solo agrega las capturas que falten (idempotente)."""
        pendientes = self.c.execute(
            "SELECT s.case_code, s.scan, cs.equipment_id, cs.created_at FROM case_scans s "
            "JOIN cases cs ON cs.code = s.case_code "
            "WHERE NOT EXISTS (SELECT 1 FROM hardware_captures h WHERE h.case_code = s.case_code)"
        ).fetchall()
        n = 0
        for p in pendientes:
            try:
                scan = json.loads(p["scan"])
            except ValueError:
                continue
            if not isinstance(scan, dict):
                continue
            resumen = _resumen(scan)
            self.c.execute(
                "INSERT INTO hardware_captures(case_code, equipment_id, captured_at, source, schema_version, "
                "host, serial, payload) VALUES (?,?,?,?,?,?,?,?)",
                (p["case_code"], p["equipment_id"], str(scan.get("scanned_at") or p["created_at"]), "legacy",
                 int(scan.get("version") or 1), scan.get("host"), resumen.get("serial"), p["scan"]))
            self.add_identifiers(p["equipment_id"], identifiers_from_scan(scan))
            n += 1
        self.c.commit()
        return n
