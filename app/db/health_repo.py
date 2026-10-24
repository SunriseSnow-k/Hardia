"""Resultados de la salud del equipo, pruebas de rendimiento y hallazgos incluidos en el
diagnóstico. Migración idempotente (CREATE TABLE IF NOT EXISTS): las bases existentes no
pierden datos. Cada evaluación se guarda solo si cambió respecto de la última del mismo caso,
captura y prueba, para no llenar la tabla al abrir la pantalla varias veces."""
import json
import sqlite3

from app.health import evaluate, load_references

from .database import ultimo_id
from .hardware_repo import QAKM_HardwareRepository
from .repo import QAKM_Repository


def _json(d) -> str:
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


class QAKM_HealthRepository:
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    def __init__(self, repo: QAKM_Repository):
        self.repo = repo
        self.c = repo.c
        self.hw = QAKM_HardwareRepository(repo)

    # ---------- resultados ----------
    def save_result(self, case_code: str, capture_id, result: dict, benchmark_id=None) -> int:
        ultimo = self.c.execute(
            "SELECT id, payload FROM health_results WHERE case_code=? AND capture_id IS ? AND benchmark_id IS ? "
            "ORDER BY id DESC LIMIT 1", (case_code, capture_id, benchmark_id)).fetchone()
        texto = _json(result)
        if ultimo and ultimo["payload"] == texto:
            return ultimo["id"]
        cur = self.c.execute(
            "INSERT INTO health_results(case_code, capture_id, benchmark_id, indice, payload) VALUES (?,?,?,?,?)",
            (case_code, capture_id, benchmark_id, (result.get("indice") or {}).get("valor"), texto))
        self.c.commit()
        return ultimo_id(cur)

    @staticmethod
    def _fila(row) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        return d

    def latest_for_case(self, case_code: str) -> dict | None:
        return self._fila(self.c.execute(
            "SELECT * FROM health_results WHERE case_code=? ORDER BY id DESC LIMIT 1", (case_code,)).fetchone())

    def latest_index_by_equipment(self) -> dict[int, dict]:
        """{equipment_id: {indice, case_code, created_at}} del último resultado de cada equipo."""
        filas = self.c.execute("""
            SELECT cs.equipment_id, h.indice, h.case_code, h.created_at
            FROM health_results h JOIN cases cs ON cs.code = h.case_code
            WHERE h.id = (SELECT MAX(h2.id) FROM health_results h2
                          JOIN cases c2 ON c2.code = h2.case_code
                          WHERE c2.equipment_id = cs.equipment_id)
        """).fetchall()
        return {f["equipment_id"]: {"indice": f["indice"], "case_code": f["case_code"],
                                    "created_at": f["created_at"]} for f in filas}

    def latest_index_for_case(self, case_code: str) -> float | None:
        r = self.c.execute("SELECT indice FROM health_results WHERE case_code=? ORDER BY id DESC LIMIT 1",
                           (case_code,)).fetchone()
        return r["indice"] if r else None

    # ---------- pruebas de rendimiento ----------
    def save_benchmark(self, case_code: str, capture_id, benchmark: dict) -> int:
        cur = self.c.execute("INSERT INTO health_benchmarks(case_code, capture_id, payload) VALUES (?,?,?)",
                             (case_code, capture_id, _json(benchmark)))
        self.c.commit()
        return ultimo_id(cur)

    def latest_benchmark(self, case_code: str, capture_id=None) -> tuple[int, dict] | None:
        r = self.c.execute(
            "SELECT id, payload FROM health_benchmarks WHERE case_code=? AND capture_id IS ? "
            "ORDER BY id DESC LIMIT 1", (case_code, capture_id)).fetchone()
        return (r["id"], json.loads(r["payload"])) if r else None

    # ---------- evaluación de un caso ----------
    def _captura_del_caso(self, case_code: str) -> dict | None:
        capturas = self.hw.captures_for_case(case_code)
        return self.hw.get_capture(capturas[0]["id"]) if capturas else None

    def evaluate_case(self, case_code: str, references: dict | None = None, guardar: bool = True) -> dict:
        """Evalúa la última captura del caso con su última prueba de rendimiento (si existe)
        y guarda el resultado. Devuelve {resultado, captura, benchmark_id, result_id}."""
        refs = references if references is not None else load_references()
        cap = self._captura_del_caso(case_code)
        if cap is None:
            return {"resultado": evaluate(None, refs), "captura": None, "benchmark_id": None, "result_id": None}
        bench = self.latest_benchmark(case_code, cap["id"])
        bid, bdata = bench if bench else (None, None)
        resultado = evaluate(cap["payload"], refs, bdata)
        rid = None
        if guardar and resultado["componentes"]:
            rid = self.save_result(case_code, cap["id"], resultado, bid)
        return {"resultado": resultado, "captura": cap, "benchmark_id": bid, "result_id": rid,
                "benchmark": bdata}

    def history_for_equipment(self, equipment_id: int, references: dict | None = None) -> list[dict]:
        """Evaluación de cada captura del equipo, de la más antigua a la más reciente."""
        refs = references if references is not None else load_references()
        salida = []
        for fila in reversed(self.hw.captures_for_equipment(equipment_id)):
            cap = self.hw.get_capture(fila["id"])
            if cap is None:  # borrada entre la consulta y la lectura
                continue
            bench = self.latest_benchmark(fila["case_code"], fila["id"])
            salida.append({"case_code": fila["case_code"], "captured_at": fila["captured_at"],
                           "capture_id": fila["id"],
                           "resultado": evaluate(cap["payload"], refs, bench[1] if bench else None)})
        return salida

    # ---------- hallazgos incluidos en el diagnóstico ----------
    def include_in_diagnosis(self, case_code: str, clave: str, texto: str) -> bool:
        """True si se agregó; False si ese componente ya estaba incluido (se actualiza el texto)."""
        texto = (texto or "").strip()
        if not texto:
            raise ValueError("El hallazgo está vacío.")
        if self.c.execute("SELECT 1 FROM cases WHERE code=?", (case_code,)).fetchone() is None:
            raise ValueError(f"No existe el caso {case_code}.")
        try:
            self.c.execute("INSERT INTO health_diag_items(case_code, clave, texto) VALUES (?,?,?)",
                           (case_code, clave, texto))
            nuevo = True
        except sqlite3.IntegrityError:
            self.c.execute("UPDATE health_diag_items SET texto=? WHERE case_code=? AND clave=?",
                           (texto, case_code, clave))
            nuevo = False
        self.c.commit()
        return nuevo

    def included_for_case(self, case_code: str) -> list[dict]:
        return [dict(r) for r in self.c.execute(
            "SELECT clave, texto, created_at FROM health_diag_items WHERE case_code=? ORDER BY id",
            (case_code,)).fetchall()]
