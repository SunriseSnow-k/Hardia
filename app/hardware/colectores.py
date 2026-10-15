"""Un colector por categoría de hardware. Cada uno es independiente: si falla, los demás siguen.
Solo se registran datos verificables; lo que falta se guarda con su motivo."""
import logging
import os
import platform
import socket
from typing import Any

from . import lhm
from .comun import (
    _ARQ_CPU,
    _BUS,
    _FABRICANTE_CPU,
    _FORMA_RAM,
    _MEDIA,
    _SALUD,
    _TIPO_RAM,
    NS_ALMACENAMIENTO,
    NS_WMI,
    _consulta,
    _decodificar,
    _faltante,
    _fecha_wmi,
    _g,
    _num,
    _res,
    limpio,
    serie_valida,
    uuid_valido,
)
from .inventory import FALLO, NO_AUTORIZADO, NO_COMPATIBLE, NO_DISPONIBLE, OK, fmt_bytes
from .sensores import (
    _cpu_sensores,
    _disco_sensores,
    _gpu_sensores,
    _lhm,
    _parecido,
    _que_falta_para_cpu,
    _sin_permisos,
    _temp_valida,
)

log = logging.getLogger(__name__)


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
