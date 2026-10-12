"""Lectura de hardware en Windows (psutil + WMI).

Cada categoría es independiente: si una falla, el resto sigue funcionando. Solo se
registran datos verificables; lo que no se pudo obtener se guarda con su motivo:
no disponible, no aplica, sin permisos o fallo de detección.
"""
import gc
import os
import platform
import re
import socket
from datetime import datetime

import psutil

from .diag_file import FORMAT, VERSION
from .inventory import FALLO, NO_AUTORIZADO, NO_COMPATIBLE, NO_DISPONIBLE, OK, fmt_bytes

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
    detalle = f'{d["name"]} · {d["cores"]} núcleos / {d["threads"]} hilos · {uso:.0f} % de uso'
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
        bus = _BUS.get(_num(_g(ms, "BusType"), int)) if ms is not None else None
        fisicas.append({
            "index": idx, "model": limpio(_g(dk, "Model")), "manufacturer": limpio(_g(dk, "Manufacturer")),
            "size_bytes": _num(_g(dk, "Size"), int),
            "media": _MEDIA.get(_num(_g(ms, "MediaType"), int)) if ms is not None else None,
            "bus": bus or limpio(_g(dk, "InterfaceType")) or None,
            "external": "external" in medio,
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
    faltan = []
    if fisicas and any(not f["health"] for f in fisicas):
        faltan.append(_faltante("Estado de salud del disco", e2))
    if fisicas and any(not f["media"] for f in fisicas):
        faltan.append(_faltante("Tipo de unidad (SSD/HDD)", e2))
    sistema = os.environ.get("SystemDrive", "C:").upper()
    vol = next((v for v in logicas if v["drive"].upper().startswith(sistema)), logicas[0] if logicas else None)
    metricas = {}
    if vol:
        metricas = {"disk_free_gb": round(vol["free_bytes"] / 1e9, 1), "disk_used_pct": vol["used_pct"]}
    principal = min((f for f in fisicas if not f["external"]), key=lambda f: _num(f["index"], int) or 0,
                    default=None)
    resumen = {}
    if principal and principal["size_bytes"]:
        resumen = {"storage": f'{principal["media"] or "Disco"} {fmt_bytes(principal["size_bytes"])}'}
    alerta = any(f["health"] in ("Advertencia", "No saludable") for f in fisicas)
    partes = [f'{f["media"] or "Disco"} {fmt_bytes(f["size_bytes"])}' for f in fisicas if f["size_bytes"]]
    detalle = f'{len(fisicas)} unidad(es): ' + ", ".join(partes) if partes else f"{len(logicas)} volumen(es)"
    if vol:
        detalle += f' · {vol["drive"]} {vol["free_bytes"] / 1e9:.0f} GB libres'
    saludes = {f["health"] for f in fisicas if f["health"]}
    if saludes:
        detalle += " · Salud: " + ", ".join(sorted(saludes))
    return _res(OK, detalle, {"physical": fisicas, "logical": logicas}, faltan, resumen, metricas, alerta)


def _graficos(env):
    gpus, err = _consulta(env, "Win32_VideoController")
    if not gpus:
        return _res(err or NO_DISPONIBLE, "No se detectaron adaptadores gráficos")
    adaptadores = []
    for g in gpus:
        ram = _num(_g(g, "AdapterRAM"), int)
        adaptadores.append({
            "name": limpio(_g(g, "Name")), "manufacturer": limpio(_g(g, "AdapterCompatibility")),
            # WMI limita AdapterRAM a 32 bits: valores de 4 GB o más no son fiables
            "vram_gb": round(ram / 1024 ** 3, 1) if ram and ram < 4294967295 else None,
            "driver_version": limpio(_g(g, "DriverVersion"))})
    adaptadores = [a for a in adaptadores if a["name"]]
    faltan = ([_faltante("Memoria gráfica (WMI no la informa o supera los 4 GB)", NO_DISPONIBLE)]
              if any(not a["vram_gb"] for a in adaptadores) else [])
    nombres = " · ".join(a["name"] for a in adaptadores)
    return _res(OK, nombres or "Sin nombre", {"adapters": adaptadores}, faltan,
                {"gpu": adaptadores[0]["name"]} if adaptadores else {})


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
    temps, ventiladores, errores = [], [], []
    sensores, e1 = _consulta(env, "Sensor", NS_LHM)
    cpu_temp, fuente_cpu = None, None
    for s in sensores:
        tipo, valor = str(_g(s, "SensorType", "")), _num(_g(s, "Value"))
        nombre = limpio(_g(s, "Name"))
        if valor is None:
            continue
        if tipo == "Temperature" and 0 < valor < 120:
            temps.append({"name": nombre, "value": valor, "source": "LibreHardwareMonitor"})
        elif tipo == "Fan" and 0 <= valor < 20000:
            ventiladores.append({"name": nombre, "rpm": valor})
    candidatos = [t["value"] for t in temps if "cpu" in t["name"].lower()]
    if candidatos:
        cpu_temp, fuente_cpu = max(candidatos), "LibreHardwareMonitor"
    if e1:
        errores.append(e1)
    if not temps:
        zonas, e2 = _consulta(env, "MSAcpi_ThermalZoneTemperature", NS_WMI)
        for z in zonas:
            ct = _num(_g(z, "CurrentTemperature"))
            valor = ct / 10 - 273.15 if ct else None
            if valor is not None and 0 < valor < 120:
                temps.append({"name": limpio(_g(z, "InstanceName")) or "Zona térmica",
                              "value": round(valor, 1), "source": "ACPI (no es necesariamente la CPU)"})
        if temps:
            cpu_temp, fuente_cpu = max(t["value"] for t in temps), "ACPI"
        if e2:
            errores.append(e2)
    if not temps and not ventiladores:
        estado = (NO_AUTORIZADO if NO_AUTORIZADO in errores else
                  FALLO if FALLO in errores and NO_DISPONIBLE not in errores else NO_DISPONIBLE)
        return _res(estado, "No disponible: requiere permisos de administrador o LibreHardwareMonitor")
    partes = []
    if cpu_temp is not None:
        partes.append(f"CPU {cpu_temp:.0f} °C ({fuente_cpu})")
    elif temps:
        partes.append(f"{len(temps)} sensor(es) de temperatura")
    if ventiladores:
        partes.append(f"{len(ventiladores)} ventilador(es)")
    metricas = {"cpu_temp": round(cpu_temp, 1)} if cpu_temp is not None else {}
    return _res(OK, " · ".join(partes), {"temperatures": temps, "fans": ventiladores,
                                         "cpu_temp_source": fuente_cpu}, [], None, metricas)


_FUNCIONES = {"identity": _identidad, "cpu": _cpu, "memory": _memoria, "storage": _almacenamiento,
              "graphics": _graficos, "motherboard": _placa, "os": _sistema, "network": _red,
              "battery": _bateria, "other": _otros, "sensors": _sensores}


# ---------------- entorno y ejecución ----------------
class _Entorno:
    """Acceso al sistema. Las pruebas lo sustituyen por uno simulado."""

    def __init__(self, c, ns):
        self.c, self._ns, self.psutil = c, ns, psutil

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


def _crear_entorno():
    c = ns = None
    if wmi:
        try:
            c = wmi.WMI()
            ns = lambda nombre: wmi.WMI(namespace=nombre)
        except Exception:
            c = ns = None
    return _Entorno(c, ns)


_ESTADO_COMPONENTE = {OK: "ok", NO_COMPATIBLE: "ok", NO_DISPONIBLE: "warn",
                      NO_AUTORIZADO: "warn", FALLO: "error"}


def _escanear(progress, env) -> dict:
    """Lee todas las categorías. Los objetos WMI viven solo dentro de esta función."""
    comps, metricas, inventario, disp = [], {}, {}, {}
    resumen = {"description": "", "serial": "", "cpu": "", "ram": "", "storage": "", "os": "", "gpu": ""}
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
    if not resumen["description"]:
        resumen["description"] = env.hostname()
    return {"format": FORMAT, "version": VERSION,
            "scanned_at": datetime.now().isoformat(timespec="seconds"),
            "host": env.hostname(), "summary": resumen, "components": comps, "metrics": metricas,
            "inventory": inventario, "availability": disp}


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