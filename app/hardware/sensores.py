"""Interpretación de los sensores de LibreHardwareMonitor (CPU, GPU, discos) y diagnóstico de qué
falta para leer la temperatura."""
import logging
import re

from . import lhm
from .comun import NS_LHM, _consulta, _g, _num, clasificar_error, limpio

log = logging.getLogger(__name__)


T_MIN, T_MAX = 1.0, 125.0  # fuera de este rango la lectura no es válida (0 °C = sensor sin permisos)
_NOMBRES_TEMP_CPU = ("CPU Package", "Core (Tctl/Tdie)", "Core (Tctl)", "Core (Tdie)", "Tdie", "Tctl",
                     "Core Max", "Core Average")


def _norm(t) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(t or "").lower()).strip()


def _de_wmi(env):
    """Lecturas del WMI que publica LibreHardwareMonitor cuando está abierto como administrador."""
    sensores, err = _consulta(env, "Sensor", NS_LHM)
    hardware = _consulta(env, "Hardware", NS_LHM)[0] if sensores else []
    nombres = {str(_g(h, "Identifier")): (limpio(_g(h, "Name")), str(_g(h, "HardwareType", "") or ""))
               for h in hardware}
    salida = []
    for x in sensores:
        valor = _num(_g(x, "Value"))
        if valor is None:
            continue
        padre = str(_g(x, "Parent", "") or "")
        dispositivo, tipo_hw = nombres.get(padre, ("", ""))
        nombre = limpio(_g(x, "Name"))
        salida.append({"hw": lhm.categoria(tipo_hw, _g(x, "Identifier", "") or padre, nombre),
                       "device": dispositivo, "type": str(_g(x, "SensorType", "")), "name": nombre,
                       "value": valor})
    return salida, err


def _temp_valida(v) -> bool:
    return v is not None and T_MIN <= v <= T_MAX


def _hay_temperaturas(lecturas) -> bool:
    return any(l["type"] == "Temperature" and _temp_valida(l["value"]) for l in lecturas)


def _leer_lhm(env) -> dict:
    """{"lecturas", "via", "error"}: primero la biblioteca incluida y, si no da temperaturas,
    el WMI de LibreHardwareMonitor abierto (que sí puede estar como administrador)."""
    lecturas, via, error = [], None, None
    leer = getattr(env, "lhm", None)
    if leer is not None:
        try:
            lecturas, via = list(leer() or []), "biblioteca"
        except Exception as e:
            error = clasificar_error(e)
    if not _hay_temperaturas(lecturas):
        de_wmi, err = _de_wmi(env)
        if _hay_temperaturas(de_wmi) or (de_wmi and not lecturas):
            lecturas, via, error = de_wmi, "WMI", None
        elif not lecturas:
            error = err or error
    return {"lecturas": lecturas, "via": via, "error": error}


def _lhm(env) -> dict:
    """Lectura de LHM del escaneo en curso (se hace una vez y la comparten los colectores)."""
    cache = getattr(env, "_lhm_cache", None)
    return cache if cache is not None else _leer_lhm(env)


def _de(lecturas, hw=None, tipo=None, device=None):
    return [l for l in lecturas if (hw is None or l["hw"] == hw) and (tipo is None or l["type"] == tipo)
            and (device is None or l["device"] == device)]


def _buscar(lecturas, *nombres):
    """Valor del primer sensor cuyo nombre coincide, en el orden de preferencia dado."""
    for n in nombres:
        for l in lecturas:
            if _norm(l["name"]) == _norm(n):
                return l["value"]
    return None


def _redondear(d: dict) -> dict:
    return {k: (round(v, 1) if isinstance(v, float) else v) for k, v in d.items()}


def _cpu_sensores(lecturas) -> dict:
    cpu = _de(lecturas, "cpu")
    temps = [l for l in _de(cpu, tipo="Temperature") if _temp_valida(l["value"])]
    temp = _buscar(temps, *_NOMBRES_TEMP_CPU)
    if temp is None and temps:
        temp = max(l["value"] for l in temps)
    nucleos = [l["value"] for l in temps if "#" in l["name"]]
    potencia = _buscar(_de(cpu, tipo="Power"), "CPU Package", "Package")
    reloj = _buscar(_de(cpu, tipo="Clock"), "Cores (Average)", "Cores (Average Effective)")
    return _redondear({"device": cpu[0]["device"] if cpu else "", "temp_c": temp,
                       "temp_max_core_c": max(nucleos) if nucleos else None,
                       "load_pct": _buscar(_de(cpu, tipo="Load"), "CPU Total"),
                       "power_w": potencia or None, "clock_mhz": reloj or None})


def _gpu_sensores(lecturas) -> list[dict]:
    salida = []
    for disp in dict.fromkeys(l["device"] for l in _de(lecturas, "gpu")):
        g = _de(lecturas, "gpu", device=disp)
        temps = [l for l in _de(g, tipo="Temperature") if _temp_valida(l["value"])]
        nucleo = [l for l in temps if "hot spot" not in l["name"].lower()]
        temp = _buscar(temps, "GPU Core")
        if temp is None and nucleo:
            temp = max(l["value"] for l in nucleo)
        ventiladores = [l["value"] for l in _de(g, tipo="Fan") if 0 <= l["value"] < 20000]
        salida.append(_redondear({
            "device": disp, "temp_c": temp, "hotspot_c": _buscar(temps, "GPU Hot Spot"),
            "load_pct": _buscar(_de(g, tipo="Load"), "GPU Core", "D3D 3D"),
            "fan_rpm": max(ventiladores) if ventiladores else None,
            "mem_used_mb": _buscar(g, "GPU Memory Used"), "mem_total_mb": _buscar(g, "GPU Memory Total")}))
    return salida


def _disco_sensores(lecturas) -> list[dict]:
    salida = []
    for disp in dict.fromkeys(l["device"] for l in _de(lecturas, "storage")):
        d = _de(lecturas, "storage", device=disp)
        temps = [l for l in _de(d, tipo="Temperature") if _temp_valida(l["value"])]
        temp = _buscar(temps, "Temperature", "Composite Temperature")
        if temp is None and temps:
            temp = max(l["value"] for l in temps)
        niveles = _de(d, tipo="Level")
        vida = _buscar(niveles, "Remaining Life", "Life Remaining")
        usado = _buscar(niveles, "Percentage Used")  # NVMe: % de la vida nominal ya consumida
        if vida is None and usado is not None:
            vida = max(0.0, 100.0 - usado)
        salida.append(_redondear({
            "device": disp, "temp_c": temp, "life_pct": vida,
            "spare_pct": _buscar(niveles, "Available Spare"),
            "written_gb": _buscar(_de(d, tipo="Data"), "Data Written", "Total Bytes Written", "Host Writes")}))
    return salida


def _parecido(a, b) -> bool:
    a, b = _norm(a), _norm(b)
    return bool(a and b) and (a == b or a in b or b in a)


def _que_falta_para_cpu(env) -> str:
    """Texto para el técnico: qué hace falta para leer la temperatura real de la CPU."""
    falta = []
    if _sin_permisos(env):
        falta.append("ejecutar el programa como administrador")
    pawnio = getattr(env, "pawnio", None)
    try:
        if pawnio is not None and pawnio() is False:
            falta.append("instalar el controlador PawnIO (pawnio.eu)")
    except Exception:  # noqa: S110 (comprobación opcional; si falla solo se omite la sugerencia)
        pass
    return "Para leer la temperatura de la CPU: " + " e ".join(falta) if falta else ""


def _sin_permisos(env) -> bool:
    admin = getattr(env, "es_admin", None)
    try:
        return admin is not None and not admin()
    except Exception:
        return False
