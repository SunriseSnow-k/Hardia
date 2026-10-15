"""Búsqueda y filtros de casos y reportes.

Solo lectura y consultas parametrizadas: nunca se construye SQL con el texto
del usuario. Los resultados se paginan (LIMIT/OFFSET) y el total se calcula
con COUNT(*), sin cargar todos los registros en memoria.

Además de cliente, teléfono, código, serie, equipo y problema, se busca por el
documento del cliente y por la marca o el modelo de cualquier captura de
hardware del equipo (útil cuando el técnico escribió un nombre distinto).
"""
import re
import sqlite3
from datetime import date, datetime, timedelta
from math import ceil

from .repo import Repository

PAGE_SIZE = 50
MAX_PALABRAS = 8
_ESC = "ESCAPE '\\'"

_CASOS_FROM = (" FROM cases cs JOIN equipment e ON e.id = cs.equipment_id"
               " LEFT JOIN clients cl ON cl.id = e.client_id")
_CASOS_COLS = ("cs.code, cs.problem, cs.priority, cs.status, cs.method, cs.created_at, "
               "e.serial, e.description AS equipo, cl.name AS cliente, cl.phone, "
               "EXISTS(SELECT 1 FROM diagnoses d WHERE d.case_code = cs.code) AS has_diagnosis")
# Marca o modelo en cualquier captura del equipo. Lleva sus propios marcadores "?".
_CAPTURA = (f"EXISTS(SELECT 1 FROM hardware_captures h WHERE h.equipment_id = e.id"
            f" AND (h.manufacturer LIKE ? {_ESC} OR h.model LIKE ? {_ESC}))")
_CASOS_CAMPOS = ("cl.name", "cl.phone", "cl.doc_id", "cs.code", "e.serial", "e.description",
                 "cs.problem", _CAPTURA)

_REPORTES_FROM = (" FROM reports r JOIN cases cs ON cs.code = r.case_code"
                  " JOIN equipment e ON e.id = cs.equipment_id"
                  " LEFT JOIN clients cl ON cl.id = e.client_id")
_REPORTES_COLS = ("r.id AS report_id, r.case_code, r.kind, r.path, r.created_at, "
                  "e.description AS equipo, e.serial, cl.name AS cliente, "
                  "cs.priority, cs.status AS case_status")
_REPORTES_CAMPOS = ("cl.name", "cl.phone", "cl.doc_id", "r.case_code", "e.serial", "e.description",
                    "cs.problem", _CAPTURA)


def pages(total: int, size: int = PAGE_SIZE) -> int:
    return max(1, ceil(total / size))


def _like(token: str) -> str:
    t = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{t}%"


def _a_fecha(valor) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor))
    except ValueError:
        raise ValueError(f"Fecha no válida: {valor}") from None


def _token_fecha(token: str):
    """Reconoce 2026-10-06, 2026-10, 06/10/2026 y 10/2026. Devuelve el prefijo ISO."""
    m = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?", token)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
    else:
        m = re.fullmatch(r"(?:(\d{1,2})/)?(\d{1,2})/(\d{4})", token)
        if not m:
            return None
        d, mo, y = m.group(1), m.group(2), m.group(3)
    if not 1 <= int(mo) <= 12 or (d is not None and not 1 <= int(d) <= 31):
        return None
    return f"{y}-{int(mo):02d}" + (f"-{int(d):02d}" if d else "")


def _texto(texto: str, campos, campo_fecha: str):
    conds, params = [], []
    for tok in (texto or "").split()[:MAX_PALABRAS]:
        fecha = _token_fecha(tok)
        if fecha:
            conds.append(f"{campo_fecha} LIKE ? {_ESC}")
            params.append(fecha + "%")
        else:
            partes = [c if "?" in c else f"{c} LIKE ? {_ESC}" for c in campos]
            conds.append("(" + " OR ".join(partes) + ")")
            params += [_like(tok)] * sum(p.count("?") for p in partes)
    return conds, params


def _rango(campo: str, desde, hasta):
    if desde and hasta and _a_fecha(desde) > _a_fecha(hasta):
        desde, hasta = hasta, desde
    conds, params = [], []
    if desde:
        conds.append(f"{campo} >= ?")
        params.append(f"{_a_fecha(desde):%Y-%m-%d} 00:00:00")
    if hasta:
        conds.append(f"{campo} < ?")
        params.append(f"{_a_fecha(hasta) + timedelta(days=1):%Y-%m-%d} 00:00:00")
    return conds, params


class SearchQueries:
    """Consultas de búsqueda. Solo ejecuta SELECT; funciona con una conexión de solo lectura."""

    def __init__(self, conn: sqlite3.Connection):
        self.c = conn

    def _paginar(self, cols, frm, conds, params, orden, limit, offset) -> dict:
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        total = self.c.execute("SELECT COUNT(*)" + frm + where, params).fetchone()[0]
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        filas = self.c.execute(
            f"SELECT {cols}{frm}{where} ORDER BY {orden} LIMIT ? OFFSET ?",
            [*params, limit, offset]).fetchall()
        return {"rows": [dict(f) for f in filas], "total": total,
                "page_size": limit, "offset": offset}

    def search_cases(self, text="", status=None, priority=None, method=None,
                     diagnosis=None, date_from=None, date_to=None,
                     limit=PAGE_SIZE, offset=0) -> dict:
        conds, params = _texto(text, _CASOS_CAMPOS, "cs.created_at")
        for campo, valor in (("cs.status", status), ("cs.priority", priority), ("cs.method", method)):
            if valor:
                conds.append(f"{campo} = ?")
                params.append(valor)
        if diagnosis in ("con", "sin"):
            conds.append(("" if diagnosis == "con" else "NOT ") +
                         "EXISTS(SELECT 1 FROM diagnoses d WHERE d.case_code = cs.code)")
        c2, p2 = _rango("cs.created_at", date_from, date_to)
        return self._paginar(_CASOS_COLS, _CASOS_FROM, conds + c2, params + p2,
                             "cs.id DESC", limit, offset)

    def search_reports(self, text="", kind=None, case_status=None,
                       date_from=None, date_to=None,
                       limit=PAGE_SIZE, offset=0) -> dict:
        conds, params = _texto(text, _REPORTES_CAMPOS, "r.created_at")
        if kind:
            conds.append("r.kind = ?")
            params.append(kind)
        if case_status:
            conds.append("cs.status = ?")
            params.append(case_status)
        c2, p2 = _rango("r.created_at", date_from, date_to)
        return self._paginar(_REPORTES_COLS, _REPORTES_FROM, conds + c2, params + p2,
                             "r.id DESC", limit, offset)