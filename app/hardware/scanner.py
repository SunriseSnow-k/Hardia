"""Lectura de hardware en Windows (psutil + WMI). Cada componente es
independiente: si uno falla, el resto sigue funcionando."""
import gc
import os
import platform
import socket
from datetime import datetime

import psutil

from .diag_file import FORMAT, VERSION

try:
    import wmi
except Exception:  # pragma: no cover
    wmi = None
try:
    import pythoncom
except Exception:  # pragma: no cover
    pythoncom = None

COMPONENT_NAMES = [
    "CPU", "RAM", "Almacenamiento", "GPU",
    "Placa base / BIOS", "Sistema operativo", "Temperaturas",
]
_JUNK = {"", "to be filled by o.e.m.", "default string", "system serial number",
         "none", "0", "n/a", "not specified"}


def _clean(valor) -> str:
    texto = ("" if valor is None else str(valor)).strip()
    return "" if texto.lower() in _JUNK else texto


def _capacidad(bytes_: int) -> str:
    """Capacidad comercial (decimal): 512 GB, 1 TB."""
    gb = bytes_ / 1e9
    if gb >= 950:
        return f"{round(gb / 1000, 1):g} TB"
    return f"{round(gb):d} GB"


# ---------------- Componentes ----------------
def _cpu(c):
    uso = psutil.cpu_percent(interval=0.6)
    nombre = platform.processor() or "Procesador"
    if c:
        nombre = c.Win32_Processor()[0].Name.strip()
    nucleos = psutil.cpu_count(logical=False) or psutil.cpu_count()
    hilos = psutil.cpu_count()
    detalle = f"{nombre} · {nucleos} núcleos / {hilos} hilos · {uso:.0f} % de uso"
    return detalle, "ok", {"summary": {"cpu": nombre}, "metrics": {"cpu_usage": uso}}


def _ram(c):
    vm = psutil.virtual_memory()
    total = round(vm.total / 1024 ** 3)
    detalle = f"{total} GB · {vm.percent:.0f} % en uso"
    return detalle, "ok", {"summary": {"ram": f"{total} GB"}, "metrics": {"ram_usage": vm.percent}}


def _storage(c):
    unidad = os.environ.get("SystemDrive", "C:") + "\\"
    uso = psutil.disk_usage(unidad)
    tipo, tamano, estado = "Disco", uso.total, "Sin datos"
    if c:
        discos = c.Win32_DiskDrive()
        fijos = [d for d in discos if (d.MediaType or "").startswith("Fixed")] or discos
        if fijos:
            principal = fijos[0]
            tamano = int(principal.Size or uso.total)
            raw = (principal.Status or "").strip()
            estado = "Bueno" if raw.upper() == "OK" else (raw or "Sin datos")
        try:
            s = wmi.WMI(namespace=r"root\Microsoft\Windows\Storage")
            media = int(s.MSFT_PhysicalDisk()[0].MediaType)
            tipo = {3: "HDD", 4: "SSD"}.get(media, "Disco")
        except Exception:
            pass
    cap = _capacidad(tamano)
    libre = uso.free / 1e9
    detalle = f"{tipo} {cap} · {libre:.0f} GB libres · Estado: {estado}"
    return detalle, ("ok" if estado == "Bueno" else "warn"), {
        "summary": {"storage": f"{tipo} {cap}"},
        "metrics": {"disk_free_gb": round(libre, 1), "disk_used_pct": uso.percent},
    }


def _gpu(c):
    if not c:
        return "No se pudo consultar (WMI no disponible)", "warn", {}
    nombres = [_clean(g.Name) for g in c.Win32_VideoController() if _clean(g.Name)]
    if not nombres:
        return "No detectada", "warn", {}
    return " · ".join(nombres), "ok", {"summary": {"gpu": nombres[0]}}


def _board(c):
    if not c:
        return "No se pudo consultar (WMI no disponible)", "warn", {}
    bb, bios, cs = c.Win32_BaseBoard()[0], c.Win32_BIOS()[0], c.Win32_ComputerSystem()[0]
    placa = f"{_clean(bb.Manufacturer)} {_clean(bb.Product)}".strip() or "Placa no identificada"
    version = _clean(bios.SMBIOSBIOSVersion) or "s/d"
    descripcion = f"{_clean(cs.Manufacturer)} {_clean(cs.Model)}".strip()
    return f"{placa} · BIOS {version}", "ok", {
        "summary": {"description": descripcion, "serial": _clean(bios.SerialNumber)}
    }


def _os(c):
    if c:
        o = c.Win32_OperatingSystem()[0]
        nombre = (o.Caption or "").replace("Microsoft ", "").strip()
        return f"{nombre} · compilación {o.BuildNumber}", "ok", {"summary": {"os": nombre}}
    nombre = f"{platform.system()} {platform.release()}"
    return nombre, "ok", {"summary": {"os": nombre}}


def _temps(c):
    temp = None
    if wmi:
        try:  # LibreHardwareMonitor en ejecución (opcional)
            lhm = wmi.WMI(namespace=r"root\LibreHardwareMonitor")
            sensores = [s for s in lhm.Sensor() if s.SensorType == "Temperature"]
            cpu = [float(s.Value) for s in sensores if "cpu" in (s.Name or "").lower()]
            valores = cpu or [float(s.Value) for s in sensores]
            if valores:
                temp = max(valores)
        except Exception:
            pass
        if temp is None:
            try:  # Zona térmica ACPI (requiere administrador)
                zonas = wmi.WMI(namespace=r"root\wmi").MSAcpi_ThermalZoneTemperature()
                valores = [z.CurrentTemperature / 10 - 273.15 for z in zonas]
                if valores:
                    temp = max(valores)
            except Exception:
                pass
    if temp is not None and 0 < temp < 120:
        return f"CPU {temp:.0f} °C", "ok", {"metrics": {"cpu_temp": round(temp, 1)}}
    return ("No disponible: requiere permisos de administrador o LibreHardwareMonitor",
            "warn", {})


_FUNCIONES = [_cpu, _ram, _storage, _gpu, _board, _os, _temps]


def _escanear(progress) -> dict:
    """Lee todos los componentes. Los objetos WMI viven solo dentro de esta
    función, así se liberan antes de cerrar COM."""
    c = None
    if wmi:
        try:
            c = wmi.WMI()
        except Exception:
            c = None
    comps, metrics = [], {}
    summary = {"description": "", "serial": "", "cpu": "", "ram": "",
               "storage": "", "os": "", "gpu": ""}
    for i, (nombre, fn) in enumerate(zip(COMPONENT_NAMES, _FUNCIONES)):
        try:
            detalle, estado, info = fn(c)
        except Exception as e:
            detalle, estado, info = f"No se pudo leer ({type(e).__name__})", "error", {}
        summary.update({k: v for k, v in info.get("summary", {}).items() if v})
        metrics.update(info.get("metrics", {}))
        comps.append({"name": nombre, "detail": detalle, "status": estado})
        if progress:
            progress(i, nombre, detalle, estado)
    if not summary["description"]:
        summary["description"] = socket.gethostname()
    return {
        "format": FORMAT, "version": VERSION,
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "host": socket.gethostname(),
        "summary": summary, "components": comps, "metrics": metrics,
    }


def run_scan(progress=None) -> dict:
    """Escanea el equipo. `progress(i, nombre, detalle, estado)` se llama por componente."""
    if pythoncom:
        pythoncom.CoInitialize()
    try:
        return _escanear(progress)
    finally:
        gc.collect()  # libera los objetos WMI antes de cerrar COM
        if pythoncom:
            pythoncom.CoUninitialize()