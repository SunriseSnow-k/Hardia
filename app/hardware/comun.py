"""Utilidades comunes de la lectura de hardware: consultas WMI tolerantes a fallos, limpieza de
valores y el formato de resultado de cada colector."""
import logging
import re

from .inventory import FALLO, NO_AUTORIZADO, NO_DISPONIBLE

log = logging.getLogger(__name__)


_JUNK = {"", "to be filled by o.e.m.", "default string", "system serial number", "none", "0",
         "n/a", "not specified", "not applicable", "unknown", "system manufacturer",
         "system product name", "(standard disk drives)", "oem", "o.e.m."}


_ARQ_CPU = {0: "x86", 5: "ARM", 9: "x64", 12: "ARM64"}


_TIPO_RAM = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 27: "LPDDR", 28: "LPDDR2",
             29: "LPDDR3", 30: "LPDDR4", 34: "DDR5", 35: "LPDDR5"}


_FORMA_RAM = {8: "DIMM", 12: "SO-DIMM"}


_MEDIA = {3: "HDD", 4: "SSD", 5: "SCM"}


_BUS = {7: "USB", 8: "RAID", 11: "SATA", 17: "NVMe"}


_SALUD = {0: "Saludable", 1: "Advertencia", 2: "No saludable"}


_FABRICANTE_CPU = {"genuineintel": "Intel", "authenticamd": "AMD"}


NS_ALMACENAMIENTO = r"root\Microsoft\Windows\Storage"


NS_WMI = r"root\wmi"


NS_LHM = r"root\LibreHardwareMonitor"


def clasificar_error(exc: Exception) -> str:
    """Traduce una excepción de WMI/Windows al estado de disponibilidad."""
    t = f"{type(exc).__name__} {exc}".lower()
    if any(x in t for x in ("access denied", "acceso denegado", "0x80041003", "-2147217405",
                            "permission", "winerror 5")):
        return NO_AUTORIZADO
    if any(x in t for x in ("invalid namespace", "invalid class", "0x8004100e", "0x80041010",
                            "-2147217394", "-2147217392", "no disponible", "not found",
                            "not supported", "notimplemented")):
        return NO_DISPONIBLE
    return FALLO


def limpio(valor) -> str:
    t = ("" if valor is None else str(valor)).strip()
    return "" if t.lower() in _JUNK else t


def serie_valida(valor) -> str:
    s = limpio(valor)
    return "" if len(s) < 3 or len(set(s)) == 1 else s


def uuid_valido(valor) -> str:
    u = limpio(valor)
    if not re.fullmatch(r"[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", u):
        return ""
    plano = set(u.replace("-", "").lower())
    return "" if plano <= {"0"} or plano <= {"f"} else u.upper()


def _g(obj, nombre, defecto=None):
    try:
        return getattr(obj, nombre, defecto)
    except Exception:
        return defecto


def _num(valor, tipo=float):
    try:
        return tipo(valor)
    except (TypeError, ValueError):
        return None


def _consulta(env, clase: str, ns: str | None = None):
    """(lista, motivo_de_error). Nunca lanza."""
    try:
        origen = env.ns(ns) if ns else env.c
        if origen is None:
            raise RuntimeError("WMI no disponible")
        return list(getattr(origen, clase)()), None
    except Exception as e:
        return [], clasificar_error(e)


def _fecha_wmi(valor) -> str:
    m = re.match(r"(\d{4})(\d{2})(\d{2})", str(valor or ""))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def _decodificar(arreglo) -> str:
    """Los monitores de WMI entregan el texto como arreglo de enteros."""
    try:
        return bytes(int(x) for x in arreglo if int(x) != 0).decode("ascii", "ignore").strip()
    except (TypeError, ValueError):
        return ""


def _res(estado, detalle, datos=None, faltantes=None, resumen=None, metricas=None, alerta=False):
    return {"status": estado, "detail": detalle, "data": datos or {}, "faltantes": faltantes or [],
            "summary": resumen or {}, "metrics": metricas or {}, "alert": alerta}


def _faltante(campo, motivo):
    return {"campo": campo, "motivo": motivo or NO_DISPONIBLE}
