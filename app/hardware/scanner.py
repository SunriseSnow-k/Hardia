"""Lectura de hardware en Windows (psutil + WMI + LibreHardwareMonitorLib).

Cada categoría es independiente: si una falla, el resto sigue funcionando. Solo se
registran datos verificables; lo que no se pudo obtener se guarda con su motivo:
no disponible, no aplica, sin permisos o fallo de detección.
"""
import contextlib
import gc
import logging
import os
import platform
import re
import socket
from collections.abc import Callable
from datetime import datetime
from typing import Any

import psutil

from . import lhm
from .diag_file import FORMAT, VERSION
from .inventory import FALLO, NO_AUTORIZADO, NO_COMPATIBLE, NO_DISPONIBLE, OK, fmt_bytes

log = logging.getLogger(__name__)

try:
    import wmi
except Exception:  # pragma: no cover
    wmi = None
try:
    import pythoncom
except Exception:  # pragma: no cover
    pythoncom = None

COLECTORES_NOMBRES = [
    ("Identificación", "identity"), ("CPU", "cpu"), ("RAM", "memory"),
    ("Almacenamiento", "storage"), ("GPU", "graphics"), ("Placa base / BIOS", "motherboard"),
    ("Sistema operativo", "os"), ("Red", "network"), ("Batería", "battery"),
    ("Otros dispositivos", "other"), ("Temperaturas", "sensors"),
]
COMPONENT_NAMES = [n for n, _ in COLECTORES_NOMBRES]

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


# ---------------- utilidades ----------------
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


# ---------------- sensores (LibreHardwareMonitor) ----------------
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


# ---------------- colectores ----------------
def _identidad(env):
    cs, e1 = _consulta(env, "Win32_ComputerSystem")
    csp, e2 = _consulta(env, "Win32_ComputerSystemProduct")
    bios, e3 = _consulta(env, "Win32_BIOS")
    cs, csp, bios = (x[0] if x else None for x in (cs, csp, bios))
    tipo = str(_g(cs, "SystemType", "") or "").lower()
    arq = ("ARM64" if "arm64" in tipo else "x64" if "x64" in tipo else "x86" if "x86" in tipo
           else {"amd64": "x64", "x86_64": "x64", "arm64": "ARM64"}.get(env.machine().lower(), env.machine()))
    d = {"hostname": env.hostname(), "manufacturer": limpio(_g(cs, "Manufacturer")),
         "model": limpio(_g(cs, "Model")),
         "serial": serie_valida(_g(bios, "SerialNumber")) or serie_valida(_g(csp, "IdentifyingNumber")),
         "uuid": uuid_valido(_g(csp, "UUID")), "architecture": arq}
    faltan = []
    if not d["manufacturer"]:
        faltan.append(_faltante("Fabricante", e1))
    if not d["model"]:
        faltan.append(_faltante("Modelo", e1))
    if not d["serial"]:
        faltan.append(_faltante("N.º de serie", e3 or e2))
    if not d["uuid"]:
        faltan.append(_faltante("UUID del sistema", e2))
    desc = f'{d["manufacturer"]} {d["model"]}'.strip() or d["hostname"]
    detalle = f'{desc} · {d["hostname"]}' + (f' · Serie {d["serial"]}' if d["serial"] else "")
    return _res(OK, detalle, d, faltan, {"description": desc, "serial": d["serial"]})


def _cpu(env):
    procs, err = _consulta(env, "Win32_Processor")
    uso = env.psutil.cpu_percent(interval=0.6)
    fisicos = env.psutil.cpu_count(logical=False) or env.psutil.cpu_count()
    hilos = env.psutil.cpu_count()
    faltan = []
    if procs:
        p = procs[0]
        nombre = limpio(_g(p, "Name")) or env.processor()
        fab = limpio(_g(p, "Manufacturer"))
        d = {"manufacturer": _FABRICANTE_CPU.get(fab.lower(), fab),
             "name": nombre, "architecture": _ARQ_CPU.get(_num(_g(p, "Architecture"), int)),
             "cores": sum(_num(_g(x, "NumberOfCores"), int) or 0 for x in procs) or fisicos,
             "threads": sum(_num(_g(x, "NumberOfLogicalProcessors"), int) or 0 for x in procs) or hilos,
             "max_mhz": _num(_g(p, "MaxClockSpeed"), int), "sockets": len(procs), "usage_pct": uso}
    else:
        d = {"name": limpio(env.processor()), "cores": fisicos, "threads": hilos, "usage_pct": uso}
        faltan = [_faltante(c, err) for c in ("Fabricante", "Frecuencia máxima declarada")]
    if not d.get("name"):
        return _res(err or NO_DISPONIBLE, "No se pudo identificar el procesador")
    sen = _cpu_sensores(_lhm(env)["lecturas"])
    d.update({k: sen[k] for k in ("temp_c", "temp_max_core_c", "power_w", "clock_mhz") if sen.get(k) is not None})
    detalle = f'{d["name"]} · {d["cores"]} núcleos / {d["threads"]} hilos · {uso:.0f} % de uso'
    if d.get("temp_c") is not None:
        detalle += f' · {d["temp_c"]:.0f} °C'
    return _res(OK, detalle, d, faltan, {"cpu": d["name"]}, {"cpu_usage": uso})


def _memoria(env):
    vm = env.psutil.virtual_memory()
    total = round(vm.total / 1024 ** 3, 1)
    modulos_wmi, err = _consulta(env, "Win32_PhysicalMemory")
    modulos = []
    for m in modulos_wmi:
        cap = _num(_g(m, "Capacity"))
        modulos.append({
            "slot": limpio(_g(m, "DeviceLocator")) or limpio(_g(m, "BankLabel")),
            "capacity_gb": round(cap / 1024 ** 3, 1) if cap else None,
            "type": _TIPO_RAM.get(_num(_g(m, "SMBIOSMemoryType"), int)),
            "speed_mhz": _num(_g(m, "ConfiguredClockSpeed"), int) or _num(_g(m, "Speed"), int),
            # Campos opcionales (formato .diag 2): velocidad nominal del módulo y la configurada
            # por el equipo. Sirven para comparar con la de fábrica; pueden faltar.
            "nominal_mhz": _num(_g(m, "Speed"), int) or None,
            "configured_mhz": _num(_g(m, "ConfiguredClockSpeed"), int) or None,
            "form_factor": _FORMA_RAM.get(_num(_g(m, "FormFactor"), int)),
            "manufacturer": limpio(_g(m, "Manufacturer")), "part_number": limpio(_g(m, "PartNumber"))})
    d = {"total_gb": total, "available_gb": round(vm.available / 1024 ** 3, 1),
         "used_pct": vm.percent, "modules": modulos}
    faltan = [] if modulos else [_faltante("Módulos individuales", err)]
    detalle = f"{total:g} GB · {vm.percent:.0f} % en uso" + (f" · {len(modulos)} módulo(s)" if modulos else "")
    return _res(OK, detalle, d, faltan, {"ram": f"{round(vm.total / 1024 ** 3)} GB"},
                {"ram_usage": vm.percent})


def _almacenamiento(env):
    discos, e1 = _consulta(env, "Win32_DiskDrive")
    msft, e2 = _consulta(env, "MSFT_PhysicalDisk", NS_ALMACENAMIENTO)
    por_indice = {str(_g(x, "DeviceId")): x for x in msft}
    fisicas = []
    for dk in discos:
        medio = str(_g(dk, "MediaType", "") or "").lower()
        if "removable" in medio:
            continue
        idx = _g(dk, "Index")
        ms = por_indice.get(str(idx))
        salud = _SALUD.get(_num(_g(ms, "HealthStatus"), int)) if ms is not None else None
        rpm = _num(_g(ms, "SpindleSpeed"), int) if ms is not None else None
        rpm = rpm if rpm and 0 < rpm < 0xFFFFFFFF else None  # 0 = SSD; 0xFFFFFFFF = desconocido
        bus = _BUS.get(_num(_g(ms, "BusType"), int)) if ms is not None else None
        fisicas.append({
            "index": idx, "model": limpio(_g(dk, "Model")), "manufacturer": limpio(_g(dk, "Manufacturer")),
            "size_bytes": _num(_g(dk, "Size"), int),
            "media": _MEDIA.get(_num(_g(ms, "MediaType"), int)) if ms is not None else None,
            "bus": bus or limpio(_g(dk, "InterfaceType")) or None,
            "external": "external" in medio, "rpm": rpm,
            "health": salud, "health_source": "Windows Storage (MSFT_PhysicalDisk)" if salud else None})
    logicas = []
    vols, e3 = _consulta(env, "Win32_LogicalDisk")
    for v in vols:
        if _num(_g(v, "DriveType"), int) != 3:
            continue
        size, libre = _num(_g(v, "Size"), int), _num(_g(v, "FreeSpace"), int)
        if not size:
            continue
        logicas.append({"drive": limpio(_g(v, "DeviceID")), "label": limpio(_g(v, "VolumeName")),
                        "filesystem": limpio(_g(v, "FileSystem")), "size_bytes": size,
                        "free_bytes": libre or 0, "used_bytes": size - (libre or 0),
                        "used_pct": 100 * (size - (libre or 0)) / size})
    if not logicas:  # respaldo con psutil
        for p in env.psutil.disk_partitions(all=False):
            if "cdrom" in p.opts.lower() or "removable" in p.opts.lower():
                continue
            try:
                u = env.psutil.disk_usage(p.mountpoint)
            except OSError:
                continue
            logicas.append({"drive": p.mountpoint.rstrip("\\"), "label": "", "filesystem": p.fstype,
                            "size_bytes": u.total, "free_bytes": u.free, "used_bytes": u.used,
                            "used_pct": u.percent})
    if not fisicas and not logicas:
        return _res(e1 or NO_DISPONIBLE, "No se detectaron unidades de almacenamiento")
    sen_discos = _disco_sensores(_lhm(env)["lecturas"])
    internos = [f for f in fisicas if not f["external"]]
    for f in fisicas:
        s = next((x for x in sen_discos if _parecido(x["device"], f["model"])), None)
        if s is None and len(sen_discos) == 1 and internos == [f]:
            s = sen_discos[0]
        if s:
            f.update({k: s[k] for k in ("temp_c", "life_pct", "spare_pct", "written_gb")})
            f["sensor_source"] = lhm.FUENTE
    faltan = []
    if fisicas and all(f.get("temp_c") is None and f.get("life_pct") is None for f in fisicas):
        faltan.append(_faltante("Temperatura y vida útil del disco (SMART)",
                                NO_AUTORIZADO if _sin_permisos(env) else NO_DISPONIBLE))
    if fisicas and any(not f["health"] for f in fisicas):
        faltan.append(_faltante("Estado de salud del disco", e2))
    if fisicas and any(not f["media"] for f in fisicas):
        faltan.append(_faltante("Tipo de unidad (SSD/HDD)", e2))
    sistema = os.environ.get("SYSTEMDRIVE", "C:").upper()
    vol = next((v for v in logicas if v["drive"].upper().startswith(sistema)), logicas[0] if logicas else None)
    metricas = {}
    if vol:
        metricas = {"disk_free_gb": round(vol["free_bytes"] / 1e9, 1), "disk_used_pct": vol["used_pct"]}
    t_discos = [f["temp_c"] for f in fisicas if f.get("temp_c") is not None]
    vidas = [f["life_pct"] for f in fisicas if f.get("life_pct") is not None]
    if t_discos:
        metricas["disk_temp_max"] = max(t_discos)
    if vidas:
        metricas["disk_life_min_pct"] = min(vidas)
    if any(f["health"] in ("Advertencia", "No saludable") for f in fisicas):
        metricas["disk_health_warning"] = 1
    principal = min((f for f in fisicas if not f["external"]), key=lambda f: _num(f["index"], int) or 0,
                    default=None)
    resumen = {}
    if principal and principal["size_bytes"]:
        resumen = {"storage": f'{principal["media"] or "Disco"} {fmt_bytes(principal["size_bytes"])}'}
    alerta = (any(f["health"] in ("Advertencia", "No saludable") for f in fisicas)
              or any(v < 20 for v in vidas) or any(t >= 60 for t in t_discos))
    partes = [f'{f["media"] or "Disco"} {fmt_bytes(f["size_bytes"])}' for f in fisicas if f["size_bytes"]]
    detalle = f'{len(fisicas)} unidad(es): ' + ", ".join(partes) if partes else f"{len(logicas)} volumen(es)"
    if vol:
        detalle += f' · {vol["drive"]} {vol["free_bytes"] / 1e9:.0f} GB libres'
    saludes = {f["health"] for f in fisicas if f["health"]}
    if saludes:
        detalle += " · Salud: " + ", ".join(sorted(saludes))
    if t_discos:
        detalle += f" · {max(t_discos):.0f} °C"
    if vidas:
        detalle += f" · vida útil restante {min(vidas):.0f} %"
    return _res(OK, detalle, {"physical": fisicas, "logical": logicas}, faltan, resumen, metricas, alerta)


def _graficos(env):
    gpus, err = _consulta(env, "Win32_VideoController")
    if not gpus:
        return _res(err or NO_DISPONIBLE, "No se detectaron adaptadores gráficos")
    adaptadores: list[dict[str, Any]] = []
    for g in gpus:
        ram = _num(_g(g, "AdapterRAM"), int)
        adaptadores.append({
            "name": limpio(_g(g, "Name")), "manufacturer": limpio(_g(g, "AdapterCompatibility")),
            # WMI limita AdapterRAM a 32 bits: valores de 4 GB o más no son fiables
            "vram_gb": round(ram / 1024 ** 3, 1) if ram and ram < 4294967295 else None,
            "driver_version": limpio(_g(g, "DriverVersion"))})
    adaptadores = [a for a in adaptadores if a["name"]]
    sen_gpus = _gpu_sensores(_lhm(env)["lecturas"])
    for a in adaptadores:
        s = next((x for x in sen_gpus if _parecido(x["device"], a["name"])), None)
        if s is None and len(sen_gpus) == 1 and len(adaptadores) == 1:
            s = sen_gpus[0]
        if s:
            a.update({k: s[k] for k in ("temp_c", "hotspot_c", "load_pct", "fan_rpm", "mem_used_mb",
                                        "mem_total_mb")})
            a["sensor_source"] = lhm.FUENTE
            if not a["vram_gb"] and s.get("mem_total_mb"):
                a["vram_gb"] = round(s["mem_total_mb"] / 1024, 1)
    faltan = ([_faltante("Memoria gráfica (WMI no la informa o supera los 4 GB)", NO_DISPONIBLE)]
              if any(not a["vram_gb"] for a in adaptadores) else [])
    metricas: dict[str, float] = {}
    for clave, campo in (("gpu_temp", "temp_c"), ("gpu_hotspot", "hotspot_c"), ("gpu_load", "load_pct")):
        valores = [a[campo] for a in adaptadores if a.get(campo) is not None]
        if valores:
            metricas[clave] = max(valores)
    partes = []
    for a in adaptadores:
        extra = [f'{a["temp_c"]:.0f} °C' if a.get("temp_c") is not None else "",
                 f'{a["load_pct"]:.0f} % de uso' if a.get("load_pct") is not None else ""]
        partes.append(a["name"] + "".join(f" · {e}" for e in extra if e))
    return _res(OK, " | ".join(partes) or "Sin nombre", {"adapters": adaptadores}, faltan,
                {"gpu": adaptadores[0]["name"]} if adaptadores else {}, metricas,
                alerta=metricas.get("gpu_temp", 0) >= 90)


def _placa(env):
    bb, e1 = _consulta(env, "Win32_BaseBoard")
    bios, e2 = _consulta(env, "Win32_BIOS")
    if not bb and not bios:
        return _res(e1 or e2 or NO_DISPONIBLE, "No se pudo leer la placa base ni el BIOS")
    b, s = (bb[0] if bb else None), (bios[0] if bios else None)
    d = {"manufacturer": limpio(_g(b, "Manufacturer")), "model": limpio(_g(b, "Product")),
         "serial": serie_valida(_g(b, "SerialNumber")), "version": limpio(_g(b, "Version")),
         "bios_vendor": limpio(_g(s, "Manufacturer")), "bios_version": limpio(_g(s, "SMBIOSBIOSVersion")),
         "bios_date": _fecha_wmi(_g(s, "ReleaseDate"))}
    faltan = [_faltante("N.º de serie de la placa", e1 or NO_DISPONIBLE)] if not d["serial"] else []
    placa = f'{d["manufacturer"]} {d["model"]}'.strip() or "Placa no identificada"
    return _res(OK, f'{placa} · BIOS {d["bios_version"] or "s/d"}', d, faltan)


def _sistema(env):
    lista, err = _consulta(env, "Win32_OperatingSystem")
    if not lista:
        nombre = f"{platform.system()} {platform.release()}".strip()
        return _res(OK, nombre, {"name": nombre}, [_faltante("Versión y compilación", err)], {"os": nombre})
    o = lista[0]
    nombre = limpio(_g(o, "Caption")).replace("Microsoft ", "").strip()
    d = {"name": nombre, "version": limpio(_g(o, "Version")), "build": limpio(_g(o, "BuildNumber")),
         "architecture": limpio(_g(o, "OSArchitecture"))}
    return _res(OK, f'{nombre} · compilación {d["build"]}', d, [], {"os": nombre})


def _tipo_red(nombre: str, conexion: str):
    t = f"{nombre} {conexion}".lower()
    if any(x in t for x in ("wi-fi", "wifi", "wireless", "wlan", "802.11")):
        return "Inalámbrica (Wi-Fi)"
    if "bluetooth" in t:
        return "Bluetooth"
    if any(x in t for x in ("ethernet", "gbe", "lan", "gigabit")):
        return "Cableada (Ethernet)"
    return None


def _red(env):
    adaptadores_wmi, err = _consulta(env, "Win32_NetworkAdapter")
    try:
        direcciones = env.psutil.net_if_addrs()
    except Exception:
        direcciones = {}
    adaptadores = []
    for a in adaptadores_wmi:
        if not _g(a, "PhysicalAdapter"):
            continue
        conexion = limpio(_g(a, "NetConnectionID"))
        nombre = limpio(_g(a, "Name"))
        tipo = _tipo_red(nombre, conexion)
        ips = [x.address for x in direcciones.get(conexion, []) if x.family == socket.AF_INET]
        adaptadores.append({"name": nombre, "connection_name": conexion, "type": tipo,
                            "type_inferred": bool(tipo), "mac": limpio(_g(a, "MACAddress")),
                            "connected": _num(_g(a, "NetConnectionStatus"), int) == 2, "ipv4": ips,
                            "manufacturer": limpio(_g(a, "Manufacturer"))})
    if not adaptadores:
        return _res(err or NO_DISPONIBLE, "No se detectaron adaptadores de red físicos")
    resumen = ", ".join(f'{a["type"] or "Red"} ({"conectado" if a["connected"] else "desconectado"})'
                        for a in adaptadores)
    return _res(OK, resumen, {"adapters": adaptadores})


def _bateria(env):
    try:
        b = env.psutil.sensors_battery()
    except Exception:
        b = None
    if b is None:
        return _res(NO_COMPATIBLE, "No aplica: no se detectó batería (equipo de escritorio o sin batería)")
    d = {"percent": b.percent, "plugged": b.power_plugged}
    faltan = []
    diseno, e1 = _consulta(env, "BatteryStaticData", NS_WMI)
    completa, e2 = _consulta(env, "BatteryFullChargedCapacity", NS_WMI)
    cd = _num(_g(diseno[0], "DesignedCapacity"), int) if diseno else None
    cf = _num(_g(completa[0], "FullChargedCapacity"), int) if completa else None
    if cd and cf:
        d.update(design_mwh=cd, full_mwh=cf, wear_pct=round(max(0.0, (1 - cf / cd) * 100), 1))
    else:
        faltan.append(_faltante("Desgaste de la batería", e1 or e2))
    detalle = f"{b.percent:.0f} %" + (" · conectada" if b.power_plugged else " · en batería")
    if "wear_pct" in d:
        detalle += f' · desgaste estimado {d["wear_pct"]:.0f} %'
    return _res(OK, detalle, d, faltan)


def _otros(env):
    monitores_wmi, e1 = _consulta(env, "WmiMonitorID", NS_WMI)
    audio_wmi, e2 = _consulta(env, "Win32_SoundDevice")
    monitores = [{"name": _decodificar(_g(m, "UserFriendlyName")),
                  "manufacturer": _decodificar(_g(m, "ManufacturerName")),
                  "year": _num(_g(m, "YearOfManufacture"), int)} for m in monitores_wmi]
    audio = [{"name": limpio(_g(a, "Name")), "manufacturer": limpio(_g(a, "Manufacturer"))}
             for a in audio_wmi if limpio(_g(a, "Name"))]
    if not monitores and not audio:
        return _res(e1 or e2 or NO_DISPONIBLE, "No se detectaron monitor ni dispositivos de audio")
    faltan = ([_faltante("Monitor", e1)] if not monitores else []) + \
             ([_faltante("Audio", e2)] if not audio else [])
    detalle = f"{len(monitores)} monitor(es) · {len(audio)} dispositivo(s) de audio"
    return _res(OK, detalle, {"monitors": monitores, "audio": audio}, faltan)


def _sensores(env):
    """Temperaturas y ventiladores: LibreHardwareMonitor (biblioteca o WMI) y, si no hay, ACPI."""
    lec = _lhm(env)
    lecturas = lec["lecturas"]
    temps = [{"name": l["name"], "value": round(l["value"], 1), "source": lhm.FUENTE, "hw": l["hw"],
              "device": l["device"]}
             for l in lecturas if l["type"] == "Temperature" and _temp_valida(l["value"])]
    ventiladores = [{"name": l["name"], "rpm": l["value"], "hw": l["hw"], "device": l["device"]}
                    for l in lecturas if l["type"] == "Fan" and 0 <= l["value"] < 20000]
    cpu = _cpu_sensores(lecturas)
    cpu_temp, fuente_cpu = (cpu["temp_c"], lhm.FUENTE) if cpu["temp_c"] is not None else (None, None)
    if cpu_temp is None:  # lecturas sin categoría: se reconoce la CPU por el nombre del sensor
        candidatos = [t["value"] for t in temps if t["hw"] == "other" and "cpu" in t["name"].lower()]
        if candidatos:
            cpu_temp, fuente_cpu = max(candidatos), lhm.FUENTE
    errores = [lec["error"]] if lec["error"] else []
    if not temps:
        zonas, e2 = _consulta(env, "MSAcpi_ThermalZoneTemperature", NS_WMI)
        for z in zonas:
            ct = _num(_g(z, "CurrentTemperature"))
            valor = ct / 10 - 273.15 if ct else None
            if valor is not None and 0 < valor < 120:
                temps.append({"name": limpio(_g(z, "InstanceName")) or "Zona térmica",
                              "value": round(valor, 1), "source": "ACPI (no es necesariamente la CPU)"})
        if temps and cpu_temp is None:
            cpu_temp, fuente_cpu = max(t["value"] for t in temps), "ACPI"
        if e2:
            errores.append(e2)
    sin_permisos = _sin_permisos(env)
    requisito = _que_falta_para_cpu(env) if fuente_cpu != lhm.FUENTE else ""
    if not temps and not ventiladores:
        estado = (NO_AUTORIZADO if NO_AUTORIZADO in errores or sin_permisos else
                  FALLO if FALLO in errores and NO_DISPONIBLE not in errores else NO_DISPONIBLE)
        return _res(estado, "No disponible. " + (requisito or "El equipo no expone sensores de temperatura"))
    faltan = []
    if fuente_cpu != lhm.FUENTE:
        faltan.append(_faltante("Temperatura real de la CPU", NO_AUTORIZADO if sin_permisos else NO_DISPONIBLE))
    partes = []
    if cpu_temp is not None:
        partes.append(f"CPU {cpu_temp:.0f} °C ({fuente_cpu})")
    elif temps:
        partes.append(f"{len(temps)} sensor(es) de temperatura")
    for cat, nombre in (("gpu", "GPU"), ("storage", "Disco")):
        v = [t["value"] for t in temps if t.get("hw") == cat]
        if v:
            partes.append(f"{nombre} {max(v):.0f} °C")
    if ventiladores:
        partes.append(f"{len(ventiladores)} ventilador(es)")
    if requisito:
        partes.append(requisito)
    metricas = {"cpu_temp": round(cpu_temp, 1)} if cpu_temp is not None else {}
    if cpu.get("temp_max_core_c") is not None:
        metricas["cpu_temp_max_core"] = cpu["temp_max_core_c"]
    # Ventiladores del sistema (placa, refrigeración líquida); los de la GPU van aparte
    sistema = [f["rpm"] for f in ventiladores if f.get("hw") != "gpu"]
    if sistema:
        metricas["fan_max_rpm"] = max(sistema)
    alerta = fuente_cpu == lhm.FUENTE and cpu_temp is not None and cpu_temp >= 90
    datos = {"temperatures": temps, "fans": ventiladores, "cpu_temp_source": fuente_cpu, "reader": lec["via"]}
    return _res(OK, " · ".join(partes), datos, faltan, None, metricas, alerta)


_FUNCIONES = {"identity": _identidad, "cpu": _cpu, "memory": _memoria, "storage": _almacenamiento,
              "graphics": _graficos, "motherboard": _placa, "os": _sistema, "network": _red,
              "battery": _bateria, "other": _otros, "sensors": _sensores}


# ---------------- entorno y ejecución ----------------
class _Entorno:
    """Acceso al sistema. Las pruebas lo sustituyen por uno simulado."""

    def __init__(self, c, ns):
        self.c, self._ns, self.psutil = c, ns, psutil
        self.lector = None  # lhm.Lector abierto, para lecturas repetidas

    def ns(self, nombre):
        if self._ns is None:
            raise RuntimeError("WMI no disponible")
        return self._ns(nombre)

    @staticmethod
    def hostname():
        return socket.gethostname()

    @staticmethod
    def machine():
        return platform.machine()

    @staticmethod
    def processor():
        return platform.processor() or "Procesador"

    def lhm(self):
        return self.lector.leer() if self.lector is not None else lhm.leer_sensores()

    @staticmethod
    def es_admin():
        return lhm.es_administrador()

    @staticmethod
    def pawnio():
        return lhm.pawnio_instalado()


def _crear_entorno():
    c: Any = None
    ns: Callable[[str], Any] | None = None
    if wmi:
        try:
            c = wmi.WMI()

            def ns(nombre):
                return wmi.WMI(namespace=nombre)
        except Exception:
            c = ns = None
    return _Entorno(c, ns)


_ESTADO_COMPONENTE = {OK: "ok", NO_COMPATIBLE: "ok", NO_DISPONIBLE: "warn",
                      NO_AUTORIZADO: "warn", FALLO: "error"}


def _escanear(progress, env) -> dict:
    """Lee todas las categorías. Los objetos WMI viven solo dentro de esta función."""
    comps: list[dict] = []
    metricas: dict[str, Any] = {}
    inventario: dict[str, Any] = {}
    disp: dict[str, Any] = {}
    resumen = {"description": "", "serial": "", "cpu": "", "ram": "", "storage": "", "os": "", "gpu": ""}
    env._lhm_cache = _leer_lhm(env)  # una sola lectura de sensores, compartida por los colectores
    try:
        _recorrer(progress, env, comps, metricas, inventario, disp, resumen)
    finally:
        env._lhm_cache = None
    if not resumen["description"]:
        resumen["description"] = env.hostname()
    return {"format": FORMAT, "version": VERSION,
            "scanned_at": datetime.now().isoformat(timespec="seconds"),
            "host": env.hostname(), "summary": resumen, "components": comps, "metrics": metricas,
            "inventory": inventario, "availability": disp}


def _recorrer(progress, env, comps, metricas, inventario, disp, resumen):
    for i, (nombre, clave) in enumerate(COLECTORES_NOMBRES):
        try:
            r = _FUNCIONES[clave](env)
        except Exception as e:
            r = _res(clasificar_error(e), f"No se pudo leer ({type(e).__name__})")
        estado = _ESTADO_COMPONENTE.get(r["status"], "error")
        if r["alert"] and estado == "ok":
            estado = "warn"
        detalle = r["detail"] + (" · datos parciales" if r["status"] == OK and r["faltantes"] else "")
        if r["status"] == OK:
            inventario[clave] = r["data"]
        disp[clave] = {"status": r["status"], "detail": r["detail"], "faltantes": r["faltantes"]}
        resumen.update({k: v for k, v in r["summary"].items() if v})
        metricas.update(r["metrics"])
        comps.append({"name": nombre, "detail": detalle, "status": estado})
        if progress:
            progress(i, nombre, detalle, estado)


def read_cpu_temperature(env=None) -> tuple[float | None, str | None]:
    """Temperatura máxima de la CPU en este momento y su fuente (para la prueba de rendimiento).
    Devuelve (None, None) si no hay lectura. Nunca lanza."""
    def leer(e):
        try:
            r = _sensores(e)
        except Exception:
            return None, None
        if r["status"] != OK:
            return None, None
        return r["metrics"].get("cpu_temp"), r["data"].get("cpu_temp_source")

    if env is not None:
        return leer(env)
    if pythoncom:
        pythoncom.CoInitialize()
    try:
        return leer(_crear_entorno())
    finally:
        gc.collect()
        if pythoncom:
            pythoncom.CoUninitialize()


class LectorTemperatura:
    """Lecturas repetidas de temperatura desde un hilo: abre WMI y LibreHardwareMonitor una sola vez.
    Uso: with LectorTemperatura() as lt: temp, fuente = lt.leer()"""

    def __init__(self, env=None):
        self._env_dado = env
        self.env = env

    def __enter__(self):
        if self._env_dado is None:
            if pythoncom:
                pythoncom.CoInitialize()
            self.env = _crear_entorno()
            try:
                self.env.lector = lhm.Lector().__enter__()
            except Exception:
                self.env.lector = None  # sin biblioteca: WMI de LHM o ACPI
        return self

    def leer(self) -> tuple[float | None, str | None]:
        return read_cpu_temperature(self.env)

    def __exit__(self, *exc):
        if self._env_dado is None:
            if self.env is not None and self.env.lector is not None:
                with contextlib.suppress(Exception):
                    self.env.lector.__exit__(None, None, None)
            self.env = None
            gc.collect()
            if pythoncom:
                pythoncom.CoUninitialize()
        return False


def local_identifiers(env=None) -> list[tuple[str, str]]:
    """Identificadores fuertes y MAC de ESTE equipo (para confirmar que una captura es de él)."""
    from .inventory import identifiers_from_scan

    def leer(e):
        inv = {}
        for clave, fn in (("identity", _identidad), ("motherboard", _placa), ("network", _red)):
            try:
                r = fn(e)
            except Exception:  # cada colector es independiente: el resto del inventario se conserva
                log.debug("Inventario: falló %s", clave, exc_info=True)
                continue
            if r["status"] == OK:
                inv[clave] = r["data"]
        return identifiers_from_scan({"inventory": inv})

    if env is not None:
        return leer(env)
    if pythoncom:
        pythoncom.CoInitialize()
    try:
        return leer(_crear_entorno())
    finally:
        gc.collect()
        if pythoncom:
            pythoncom.CoUninitialize()


def run_scan(progress=None, env=None) -> dict:
    """Escanea el equipo. `progress(i, nombre, detalle, estado)` se llama por categoría."""
    if env is not None:
        return _escanear(progress, env)
    if pythoncom:
        pythoncom.CoInitialize()
    try:
        return _escanear(progress, _crear_entorno())
    finally:
        gc.collect()  # libera los objetos WMI antes de cerrar COM
        if pythoncom:
            pythoncom.CoUninitialize()
