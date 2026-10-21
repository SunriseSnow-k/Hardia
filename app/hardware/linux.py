"""Lectura de hardware en Linux: /sys, /proc y, si están instalados, dmidecode, smartctl, lspci y
nvidia-smi. Cada colector devuelve lo mismo que su par de Windows (colectores.py), así el
inventario, la salud y los reportes no distinguen el sistema.

Sin root, Linux no deja leer el número de serie, el UUID, los módulos de RAM ni el SMART de los
discos: esos datos quedan como "Sin permisos". Las temperaturas (hwmon) no necesitan root.
"""
import glob
import hashlib
import hmac
import json
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
from typing import Any

from app import plataforma

from .ayudante_root import NO_DISCO as _NO_DISCO
from .comun import _faltante, _num, _res, limpio, serie_valida, uuid_valido
from .inventory import NO_AUTORIZADO, NO_COMPATIBLE, NO_DISPONIBLE, OK, fmt_bytes
from .sensores import _cpu_sensores, _disco_sensores, _gpu_sensores, _parecido, _temp_valida

log = logging.getLogger(__name__)

FUENTE = "hwmon (Linux)"
FUENTE_SMART = "SMART (smartctl)"
_DMI = "/sys/class/dmi/id"
_FABRICANTE_PCI = {"0x10de": "NVIDIA", "0x1002": "AMD", "0x8086": "Intel"}
_FABRICANTE_CPU = {"genuineintel": "Intel", "authenticamd": "AMD"}
_ARQ = {"x86_64": "x64", "amd64": "x64", "aarch64": "ARM64", "arm64": "ARM64", "i686": "x86", "i386": "x86"}
# Sistemas de archivos que no son volúmenes de datos del usuario
_FS_VIRTUALES = {"squashfs", "tmpfs", "devtmpfs", "overlay", "iso9660", "udf", "efivarfs", "ramfs"}
# Chips de hwmon -> categoría propia (la misma que usa LibreHardwareMonitor en Windows)
_CHIP = {"coretemp": "cpu", "k10temp": "cpu", "zenpower": "cpu", "k8temp": "cpu", "cpu_thermal": "cpu",
         "amdgpu": "gpu", "radeon": "gpu", "nouveau": "gpu", "i915": "gpu", "xe": "gpu",
         "nvme": "storage", "drivetemp": "storage"}
_ETIQUETAS = {"edge": "GPU Core", "junction": "GPU Hot Spot", "mem": "GPU Memory", "composite": "Composite Temperature"}
# /sys/block/*/device/vendor de los discos SATA dice el bus ("ATA"), no la marca: se deduce del modelo
_VENDOR_BUS = {"ata", "nvme", "usb", "scsi", "generic"}
_MARCA_DISCO = (("WDC", "Western Digital"), ("WD", "Western Digital"), ("ST", "Seagate"), ("SAMSUNG", "Samsung"),
                ("MZ", "Samsung"), ("KINGSTON", "Kingston"), ("SA400", "Kingston"), ("CT", "Crucial"),
                ("CRUCIAL", "Crucial"), ("TOSHIBA", "Toshiba"), ("KIOXIA", "Kioxia"), ("HGST", "HGST"),
                ("HITACHI", "Hitachi"), ("SANDISK", "SanDisk"), ("INTEL", "Intel"), ("SSDPE", "Intel"),
                ("MICRON", "Micron"), ("SK HYNIX", "SK hynix"), ("HFM", "SK hynix"), ("ADATA", "ADATA"),
                ("LITEON", "Lite-On"), ("PNY", "PNY"), ("TEAM", "Team Group"), ("HP SSD", "HP"),
                ("APPLE", "Apple"), ("MAXTOR", "Maxtor"), ("LENOVO", "Lenovo"))
_TIPO_RAM = ("LPDDR5", "LPDDR4", "LPDDR3", "LPDDR2", "LPDDR", "DDR5", "DDR4", "DDR3", "DDR2", "DDR")


class EntornoLinux:
    """Acceso al sistema en Linux. Las pruebas lo sustituyen por uno simulado con los mismos métodos."""

    sistema = "linux"

    def __init__(self):
        import psutil
        self.psutil = psutil
        self.lector = None
        self._cache: dict[tuple, Any] = {}
        self._archivos: dict[str, str] = {}
        self._privilegiado = False

    def usar_privilegiados(self, datos: dict) -> None:
        """Datos que leyó el ayudante con permisos (permisos_linux.py): los archivos protegidos de
        /sys y las salidas de dmidecode y smartctl se usan como si este proceso fuera root."""
        archivos = datos.get("archivos")
        if isinstance(archivos, dict):
            self._archivos.update({str(k): str(v).strip() for k, v in archivos.items() if isinstance(v, str)})
        for item in datos.get("comandos") or []:
            if isinstance(item, list) and len(item) == 2 and isinstance(item[0], list):
                self._cache[tuple(str(a) for a in item[0])] = item[1] if isinstance(item[1], str) else None
        self._privilegiado = True

    def leer(self, ruta: str) -> str | None:
        """Contenido de un archivo de texto (sin espacios a los lados) o None si no se puede leer."""
        if ruta in self._archivos:
            return self._archivos[ruta]
        try:
            with open(ruta, encoding="utf-8", errors="replace") as f:
                return f.read().strip()
        except OSError:
            return None

    @staticmethod
    def leer_bytes(ruta: str) -> bytes | None:
        try:
            with open(ruta, "rb") as f:
                return f.read()
        except OSError:
            return None

    @staticmethod
    def listar(patron: str) -> list[str]:
        return sorted(glob.glob(patron))

    @staticmethod
    def existe(ruta: str) -> bool:
        return os.path.exists(ruta)

    @staticmethod
    def ruta_real(ruta: str) -> str:
        return os.path.realpath(ruta)

    def ejecutar(self, *args: str) -> str | None:
        """Salida de un programa del sistema (o None si no está instalado o falla). Se recuerda
        durante el escaneo: smartctl y dmidecode se consultan una sola vez."""
        if args in self._cache:
            return self._cache[args]
        salida = None
        programa = shutil.which(args[0])
        if programa:
            try:
                r = subprocess.run([programa, *args[1:]], capture_output=True, text=True,  # noqa: S603 (programas fijos, sin shell)
                                   timeout=20, errors="replace", env={**os.environ, "LC_ALL": "C"})
                # smartctl usa bits del código de salida como avisos: hay datos aunque no sea 0
                salida = r.stdout if r.stdout.strip() else None
            except (OSError, subprocess.SubprocessError):
                salida = None
        self._cache[args] = salida
        return salida

    @staticmethod
    def tiene(programa: str) -> bool:
        return shutil.which(programa) is not None

    @staticmethod
    def hostname():
        return socket.gethostname()

    @staticmethod
    def machine():
        return platform.machine()

    @staticmethod
    def processor():
        return platform.processor() or "Procesador"

    @staticmethod
    def release():
        return platform.release()

    def es_admin(self):
        return self._privilegiado or plataforma.es_administrador()


# ---------------- utilidades ----------------
def _dmi(env, campo: str) -> str:
    return limpio(env.leer(f"{_DMI}/{campo}"))


def _sin_root(env) -> bool:
    try:
        return not env.es_admin()
    except Exception:
        return False


def _motivo_root(env) -> str:
    return NO_AUTORIZADO if _sin_root(env) else NO_DISPONIBLE


def _fecha_dmi(valor: str) -> str:
    """'06/12/2023' -> '2023-06-12'."""
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", valor or "")
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else ""


def _cpuinfo(env) -> list[dict]:
    """Bloques de /proc/cpuinfo (uno por procesador lógico)."""
    bloques: list[dict] = []
    actual: dict[str, str] = {}
    for linea in (env.leer("/proc/cpuinfo") or "").splitlines():
        if not linea.strip():
            if actual:
                bloques.append(actual)
            actual = {}
            continue
        clave, _, valor = linea.partition(":")
        actual[clave.strip().lower()] = valor.strip()
    if actual:
        bloques.append(actual)
    return bloques


def _arquitectura(env) -> str:
    m = env.machine()
    return _ARQ.get(m.lower(), m)


# ---------------- sensores (hwmon) ----------------
def _etiqueta(chip: str, etiqueta: str, n: str) -> str:
    """Nombres de hwmon -> los de LibreHardwareMonitor, para interpretar igual en los dos sistemas."""
    e = etiqueta.strip()
    if not e:
        return "Temperature"
    if chip == "coretemp":
        if e.lower().startswith("package id"):
            return "CPU Package"
        m = re.fullmatch(r"Core (\d+)", e)
        if m:
            return f"Core #{m.group(1)}"
    return _ETIQUETAS.get(e.lower(), e)


def _dispositivo(env, carpeta: str, chip: str) -> str:
    """Nombre del dispositivo de un chip de hwmon (modelo del disco NVMe/SATA o el chip)."""
    for ruta in (f"{carpeta}/device/model", f"{carpeta}/device/device/model"):
        modelo = limpio(env.leer(ruta))
        if modelo:
            return modelo
    return chip


def _hwmon(env) -> list[dict]:
    """[{hw, device, type, name, value}] de /sys/class/hwmon."""
    salida = []
    for carpeta in env.listar("/sys/class/hwmon/hwmon*"):
        chip = (env.leer(f"{carpeta}/name") or "").strip()
        cat = _CHIP.get(chip, "motherboard" if env.listar(f"{carpeta}/fan*_input") else "other")
        if chip == "acpitz":
            cat = "other"
        disp = _dispositivo(env, carpeta, chip)
        for entrada in env.listar(f"{carpeta}/temp*_input"):
            n = re.search(r"temp(\d+)_input$", entrada)
            valor = _num(env.leer(entrada))
            if n is None or valor is None:
                continue
            etiqueta = env.leer(f"{carpeta}/temp{n.group(1)}_label") or ""
            nombre = _etiqueta(chip, etiqueta, n.group(1))
            if chip == "acpitz":
                nombre = f"Zona térmica {n.group(1)}"
            salida.append({"hw": cat, "device": disp, "type": "Temperature", "name": nombre, "value": valor / 1000})
        for entrada in env.listar(f"{carpeta}/fan*_input"):
            n = re.search(r"fan(\d+)_input$", entrada)
            valor = _num(env.leer(entrada))
            if n is None or valor is None:
                continue
            nombre = env.leer(f"{carpeta}/fan{n.group(1)}_label") or f"Fan #{n.group(1)}"
            salida.append({"hw": cat, "device": disp, "type": "Fan", "name": nombre, "value": valor})
        if chip == "amdgpu":
            uso = _num(env.leer(f"{carpeta}/device/gpu_busy_percent"))
            if uso is not None:
                salida.append({"hw": "gpu", "device": disp, "type": "Load", "name": "GPU Core", "value": uso})
    return salida


def _nvidia(env) -> list[dict]:
    """Lecturas de las GPU NVIDIA con el controlador propietario (no publica hwmon)."""
    texto = env.ejecutar("nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu,memory.total,"
                         "memory.used,fan.speed", "--format=csv,noheader,nounits")
    salida = []
    for linea in (texto or "").splitlines():
        campos = [c.strip() for c in linea.split(",")]
        if len(campos) < 6:
            continue
        nombre = campos[0]
        for tipo, sensor, valor in (("Temperature", "GPU Core", campos[1]), ("Load", "GPU Core", campos[2]),
                                    ("SmallData", "GPU Memory Total", campos[3]),
                                    ("SmallData", "GPU Memory Used", campos[4])):
            v = _num(valor)
            if v is not None:
                salida.append({"hw": "gpu", "device": nombre, "type": tipo, "name": sensor, "value": v})
    return salida


def leer_sensores(env) -> dict:
    """{"lecturas", "via", "error"}: el mismo formato que la lectura de LibreHardwareMonitor."""
    try:
        lecturas = _hwmon(env) + _nvidia(env)
    except Exception as e:
        log.debug("Linux: falló la lectura de hwmon", exc_info=True)
        return {"lecturas": [], "via": None, "error": NO_DISPONIBLE if isinstance(e, OSError) else "fallo"}
    return {"lecturas": lecturas, "via": "hwmon" if lecturas else None, "error": None}


def _lecturas(env) -> list[dict]:
    cache = getattr(env, "_lhm_cache", None)
    return (cache if cache is not None else leer_sensores(env))["lecturas"]


def requisitos_sensores(env=None) -> list[str]:
    """Lo que falta en este equipo para leer todos los sensores (vacío si no falta nada)."""
    env = env or EntornoLinux()
    falta = []
    if not env.tiene("smartctl"):
        falta.append("instalar smartmontools (sudo apt install smartmontools) para el estado SMART de los discos")
    if _sin_root(env):
        from .permisos_linux import disponible
        como = ("escanear con permisos de administrador (botón «Escanear con permisos»)" if disponible()
                else "ejecutar el programa con sudo")
        falta.append(f"{como}: número de serie, módulos de RAM y SMART de los discos")
    if not any(l["hw"] == "cpu" and l["type"] == "Temperature" for l in _hwmon(env)):
        falta.append("el sensor de temperatura de la CPU (paquete lm-sensors: sudo sensors-detect)")
    return falta


# ---------------- colectores ----------------
def _id_maquina(env) -> str:
    """Identificador de esta instalación de Linux propio del programa: HMAC de /etc/machine-id (el
    valor original no se guarda, como recomienda systemd). Legible sin root."""
    mid = (env.leer("/etc/machine-id") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", mid):
        return ""
    return hmac.new(bytes.fromhex(mid), b"SistemaDiagnostico", hashlib.sha256).hexdigest()[:32].upper()


def _identidad(env):
    d = {"hostname": env.hostname(), "manufacturer": _dmi(env, "sys_vendor"),
         "model": _dmi(env, "product_name"),
         "serial": serie_valida(env.leer(f"{_DMI}/product_serial")),
         "uuid": uuid_valido(env.leer(f"{_DMI}/product_uuid")), "architecture": _arquitectura(env),
         "machine_id": _id_maquina(env)}
    faltan = []
    if not d["manufacturer"]:
        faltan.append(_faltante("Fabricante", NO_DISPONIBLE))
    if not d["model"]:
        faltan.append(_faltante("Modelo", NO_DISPONIBLE))
    if not d["serial"]:
        faltan.append(_faltante("N.º de serie", _motivo_root(env)))
    if not d["uuid"]:
        faltan.append(_faltante("UUID del sistema", _motivo_root(env)))
    desc = f'{d["manufacturer"]} {d["model"]}'.strip() or d["hostname"]
    detalle = f'{desc} · {d["hostname"]}' + (f' · Serie {d["serial"]}' if d["serial"] else "")
    return _res(OK, detalle, d, faltan, {"description": desc, "serial": d["serial"]})


def _cpu(env):
    uso = env.psutil.cpu_percent(interval=0.6)
    fisicos = env.psutil.cpu_count(logical=False) or env.psutil.cpu_count()
    hilos = env.psutil.cpu_count()
    bloques = _cpuinfo(env)
    b = bloques[0] if bloques else {}
    nombre = limpio(b.get("model name") or b.get("hardware") or b.get("processor")) or limpio(env.processor())
    if nombre.isdigit():  # en ARM "processor" es el número de núcleo, no el modelo
        nombre = limpio(env.processor())
    fab = limpio(b.get("vendor_id"))
    maximo = _num(env.leer("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq"), int)
    d = {"manufacturer": _FABRICANTE_CPU.get(fab.lower(), fab), "name": nombre,
         "architecture": _arquitectura(env), "cores": fisicos, "threads": hilos,
         "max_mhz": maximo // 1000 if maximo else None,
         "sockets": len({x.get("physical id") for x in bloques if x.get("physical id")}) or 1,
         "usage_pct": uso}
    if not d["name"]:
        return _res(NO_DISPONIBLE, "No se pudo identificar el procesador")
    faltan = [] if d["max_mhz"] else [_faltante("Frecuencia máxima declarada", NO_DISPONIBLE)]
    sen = _cpu_sensores(_lecturas(env))
    d.update({k: sen[k] for k in ("temp_c", "temp_max_core_c", "power_w", "clock_mhz") if sen.get(k) is not None})
    detalle = f'{d["name"]} · {d["cores"]} núcleos / {d["threads"]} hilos · {uso:.0f} % de uso'
    if d.get("temp_c") is not None:
        detalle += f' · {d["temp_c"]:.0f} °C'
    return _res(OK, detalle, d, faltan, {"cpu": d["name"]}, {"cpu_usage": uso})


def _mhz(texto: str):
    m = re.match(r"(\d+)\s*(MT/s|MHz)", texto or "")
    return int(m.group(1)) if m else None


def _modulos_ram(env) -> list[dict]:
    """Módulos de RAM según dmidecode (requiere root)."""
    texto = env.ejecutar("dmidecode", "-t", "17")
    modulos = []
    for bloque in (texto or "").split("\n\n"):
        if "Memory Device" not in bloque:
            continue
        campos = {}
        for linea in bloque.splitlines():
            clave, sep, valor = linea.strip().partition(":")
            if sep:
                campos[clave.strip()] = valor.strip()
        m = re.match(r"(\d+)\s*(GB|MB|kB)", campos.get("Size", ""))
        if not m:
            continue  # "No Module Installed"
        cap = int(m.group(1)) / {"GB": 1, "MB": 1024, "kB": 1024 ** 2}[m.group(2)]
        tipo = next((t for t in _TIPO_RAM if campos.get("Type", "").upper() == t), None)
        forma = campos.get("Form Factor", "").upper().replace("-", "")
        nominal, conf = _mhz(campos.get("Speed", "")), _mhz(campos.get("Configured Memory Speed", ""))
        modulos.append({
            "slot": limpio(campos.get("Locator")) or limpio(campos.get("Bank Locator")),
            "capacity_gb": round(cap, 1), "type": tipo, "speed_mhz": conf or nominal,
            "nominal_mhz": nominal, "configured_mhz": conf,
            "form_factor": {"DIMM": "DIMM", "SODIMM": "SO-DIMM"}.get(forma),
            "manufacturer": limpio(campos.get("Manufacturer")), "part_number": limpio(campos.get("Part Number"))})
    return modulos


def _memoria(env):
    vm = env.psutil.virtual_memory()
    total = round(vm.total / 1024 ** 3, 1)
    modulos = _modulos_ram(env)
    d = {"total_gb": total, "available_gb": round(vm.available / 1024 ** 3, 1),
         "used_pct": vm.percent, "modules": modulos}
    faltan = [] if modulos else [_faltante("Módulos individuales", _motivo_root(env))]
    detalle = f"{total:g} GB · {vm.percent:.0f} % en uso" + (f" · {len(modulos)} módulo(s)" if modulos else "")
    return _res(OK, detalle, d, faltan, {"ram": f"{round(vm.total / 1024 ** 3)} GB"},
                {"ram_usage": vm.percent})


def _bus(env, nombre: str) -> str | None:
    ruta = env.ruta_real(f"/sys/block/{nombre}")
    if nombre.startswith("nvme") or "/nvme" in ruta:
        return "NVMe"
    if "/usb" in ruta:
        return "USB"
    if "/ata" in ruta:
        return "SATA"
    if nombre.startswith("mmcblk"):
        return "MMC"
    return None


def _smart(env, dispositivo: str) -> dict:
    """Salud, temperatura y vida útil según smartctl (requiere root y smartmontools)."""
    texto = env.ejecutar("smartctl", "-j", "-a", dispositivo)
    try:
        s = json.loads(texto) if texto else {}
    except ValueError:
        return {}
    salida: dict[str, Any] = {}
    rpm = _num(s.get("rotation_rate"), int)
    if rpm and rpm > 0:  # 0 = SSD
        salida["rpm"] = rpm
    if s.get("model_family"):
        salida["family"] = limpio(s["model_family"])
    estado = (s.get("smart_status") or {}).get("passed")
    if estado is not None:
        salida["health"] = "Saludable" if estado else "No saludable"
        salida["health_source"] = FUENTE_SMART
    temp = _num((s.get("temperature") or {}).get("current"))
    if _temp_valida(temp):
        salida["temp_c"] = temp
    nvme = s.get("nvme_smart_health_information_log") or {}
    if nvme.get("percentage_used") is not None:
        salida["life_pct"] = max(0.0, 100.0 - float(nvme["percentage_used"]))
        if salida.get("health") == "Saludable" and float(nvme["percentage_used"]) >= 90:
            salida["health"] = "Advertencia"
    if nvme.get("available_spare") is not None:
        salida["spare_pct"] = float(nvme["available_spare"])
    if nvme.get("data_units_written"):
        salida["written_gb"] = round(nvme["data_units_written"] * 512_000 / 1e9, 1)
    for a in (s.get("ata_smart_attributes") or {}).get("table") or []:
        if a.get("id") in (231, 233, 202, 169) and "life_pct" not in salida:
            valor = _num(a.get("value"))
            if valor is not None and 0 <= valor <= 100:
                salida["life_pct"] = valor
        if a.get("id") == 5 and (_num((a.get("raw") or {}).get("value")) or 0) > 0 \
                and salida.get("health") == "Saludable":
            salida["health"] = "Advertencia"  # sectores reasignados
    return salida


def _marca_disco(vendor: str, modelo: str, familia: str = "") -> str:
    """Fabricante del disco: el de sysfs si es una marca, si no se deduce del modelo o la familia SMART."""
    if vendor and vendor.lower() not in _VENDOR_BUS:
        return vendor
    for texto in (modelo, familia):
        t = (texto or "").upper()
        for prefijo, marca in _MARCA_DISCO:
            if t.startswith(prefijo):
                return marca
    return ""


def _discos(env) -> list[dict]:
    fisicas: list[dict] = []
    for carpeta in env.listar("/sys/block/*"):
        nombre = carpeta.rsplit("/", 1)[-1]
        if nombre.startswith(_NO_DISCO) or re.search(r"boot\d+$|rpmb$", nombre):
            continue
        if (env.leer(f"{carpeta}/removable") or "0") == "1":
            continue  # memorias USB y lectores de tarjetas
        sectores = _num(env.leer(f"{carpeta}/size"), int)
        if not sectores:
            continue
        bus = _bus(env, nombre)
        rotacional = env.leer(f"{carpeta}/queue/rotational")
        media = "SSD" if bus == "NVMe" or rotacional == "0" else "HDD" if rotacional == "1" else None
        modelo = limpio(env.leer(f"{carpeta}/device/model")) or limpio(env.leer(f"{carpeta}/device/name"))
        disco = {"index": len(fisicas), "device": f"/dev/{nombre}", "model": modelo,
                 "manufacturer": limpio(env.leer(f"{carpeta}/device/vendor")),
                 "size_bytes": sectores * 512, "media": media, "bus": bus, "external": bus == "USB",
                 "rpm": None, "health": None, "health_source": None}
        smart = _smart(env, disco["device"])
        disco["manufacturer"] = _marca_disco(disco["manufacturer"], modelo, smart.get("family", ""))
        if smart.get("rpm"):
            disco["rpm"] = smart["rpm"]
        disco.update({k: v for k, v in smart.items() if k in ("health", "health_source")})
        disco.update({k: v for k, v in smart.items() if k in ("temp_c", "life_pct", "spare_pct", "written_gb")})
        if any(k in smart for k in ("temp_c", "life_pct")):
            disco["sensor_source"] = FUENTE_SMART
        fisicas.append(disco)
    return fisicas


def _volumenes(env) -> list[dict]:
    logicas, vistos = [], set()
    for p in env.psutil.disk_partitions(all=False):
        if p.fstype in _FS_VIRTUALES or p.mountpoint.startswith(("/snap", "/boot", "/media", "/run/media")):
            continue
        if p.device in vistos:  # btrfs monta el mismo volumen varias veces (subvolúmenes)
            continue
        try:
            u = env.psutil.disk_usage(p.mountpoint)
        except OSError:
            continue
        if not u.total:
            continue
        vistos.add(p.device)
        logicas.append({"drive": p.mountpoint, "label": p.device.rsplit("/", 1)[-1], "filesystem": p.fstype,
                        "size_bytes": u.total, "free_bytes": u.free, "used_bytes": u.used,
                        "used_pct": u.percent})
    return logicas


def _almacenamiento(env):
    fisicas, logicas = _discos(env), _volumenes(env)
    if not fisicas and not logicas:
        return _res(NO_DISPONIBLE, "No se detectaron unidades de almacenamiento")
    sen_discos = _disco_sensores(_lecturas(env))
    internos = [f for f in fisicas if not f["external"]]
    for f in fisicas:
        s = next((x for x in sen_discos if _parecido(x["device"], f["model"])), None)
        if s is None and len(sen_discos) == 1 and internos == [f]:
            s = sen_discos[0]
        if s:
            for k in ("temp_c", "life_pct", "spare_pct", "written_gb"):
                if f.get(k) is None and s.get(k) is not None:
                    f[k] = s[k]
            f.setdefault("sensor_source", FUENTE)
    for f in fisicas:
        for k in ("temp_c", "life_pct", "spare_pct", "written_gb"):
            f.setdefault(k, None)
    faltan = []
    if fisicas and all(f.get("life_pct") is None and not f["health"] for f in fisicas):
        motivo = NO_AUTORIZADO if _sin_root(env) else NO_DISPONIBLE
        faltan.append(_faltante("Estado SMART del disco (salud y vida útil)", motivo))
    if fisicas and any(not f["media"] for f in fisicas):
        faltan.append(_faltante("Tipo de unidad (SSD/HDD)", NO_DISPONIBLE))
    vol = next((v for v in logicas if v["drive"] == "/"), logicas[0] if logicas else None)
    metricas: dict[str, float] = {}
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
    principal = internos[0] if internos else None
    resumen = {"storage": f'{principal["media"] or "Disco"} {fmt_bytes(principal["size_bytes"])}'} if principal else {}
    alerta = (any(f["health"] in ("Advertencia", "No saludable") for f in fisicas)
              or any(v < 20 for v in vidas) or any(t >= 60 for t in t_discos))
    partes = [f'{f["media"] or "Disco"} {fmt_bytes(f["size_bytes"])}' for f in fisicas]
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


def _lspci(env, ranura: str) -> tuple[str, str]:
    """(fabricante, nombre) de un dispositivo PCI según lspci -mm."""
    texto = env.ejecutar("lspci", "-mm", "-s", ranura)
    campos = re.findall(r'"([^"]*)"', texto or "")
    return (limpio(campos[1]), limpio(campos[2])) if len(campos) >= 3 else ("", "")


def _graficos(env):
    adaptadores: list[dict[str, Any]] = []
    for carpeta in env.listar("/sys/class/drm/card*"):
        if not re.search(r"/card\d+$", carpeta):
            continue  # card0-HDMI-A-1: conectores, no adaptadores
        dev = f"{carpeta}/device"
        ranura = env.ruta_real(dev).rsplit("/", 1)[-1]
        if any(a["slot"] == ranura for a in adaptadores):
            continue
        fab_id = (env.leer(f"{dev}/vendor") or "").lower()
        fab, nombre = _lspci(env, ranura)
        fab = fab or _FABRICANTE_PCI.get(fab_id, "")
        comercial = re.search(r"\[([^\]]+)\]\s*$", nombre)  # 'TigerLake-LP GT2 [Iris Xe Graphics]'
        if comercial:
            marca = _FABRICANTE_PCI.get(fab_id, "")
            nombre = f"{marca} {comercial.group(1)}".strip() if marca and marca not in comercial.group(1) \
                else comercial.group(1)
        nombre = nombre or (f"GPU {fab}" if fab else "")
        if not nombre:
            continue
        controlador = ""
        for linea in (env.leer(f"{dev}/uevent") or "").splitlines():
            if linea.startswith("DRIVER="):
                controlador = linea.split("=", 1)[1]
        vram = _num(env.leer(f"{dev}/mem_info_vram_total"), int)
        adaptadores.append({"slot": ranura, "name": nombre, "manufacturer": _FABRICANTE_PCI.get(fab_id, fab),
                            "vram_gb": round(vram / 1024 ** 3, 1) if vram else None,
                            "driver_version": controlador})
    if not adaptadores:
        return _res(NO_DISPONIBLE, "No se detectaron adaptadores gráficos")
    sen_gpus = _gpu_sensores(_lecturas(env))
    for a in adaptadores:
        s = next((x for x in sen_gpus if _parecido(x["device"], a["name"])), None)
        if s is None and len(sen_gpus) == 1 and len(adaptadores) == 1:
            s = sen_gpus[0]
        if s is None:  # el chip de hwmon se llama como el controlador (amdgpu, nouveau)
            s = next((x for x in sen_gpus if x["device"] == a["driver_version"]), None)
        if s:
            a.update({k: s[k] for k in ("temp_c", "hotspot_c", "load_pct", "fan_rpm", "mem_used_mb",
                                        "mem_total_mb")})
            a["sensor_source"] = FUENTE
            if not a["vram_gb"] and s.get("mem_total_mb"):
                a["vram_gb"] = round(s["mem_total_mb"] / 1024, 1)
    faltan = ([_faltante("Memoria gráfica", NO_DISPONIBLE)]
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
    return _res(OK, " | ".join(partes), {"adapters": adaptadores}, faltan, {"gpu": adaptadores[0]["name"]},
                metricas, alerta=metricas.get("gpu_temp", 0) >= 90)


def _placa(env):
    d = {"manufacturer": _dmi(env, "board_vendor"), "model": _dmi(env, "board_name"),
         "serial": serie_valida(env.leer(f"{_DMI}/board_serial")), "version": _dmi(env, "board_version"),
         "bios_vendor": _dmi(env, "bios_vendor"), "bios_version": _dmi(env, "bios_version"),
         "bios_date": _fecha_dmi(_dmi(env, "bios_date"))}
    if not any(d.values()):
        return _res(NO_DISPONIBLE, "No se pudo leer la placa base ni el BIOS")
    faltan = [_faltante("N.º de serie de la placa", _motivo_root(env))] if not d["serial"] else []
    placa = f'{d["manufacturer"]} {d["model"]}'.strip() or "Placa no identificada"
    return _res(OK, f'{placa} · BIOS {d["bios_version"] or "s/d"}', d, faltan)


def _sistema(env):
    datos = {}
    for linea in (env.leer("/etc/os-release") or "").splitlines():
        clave, sep, valor = linea.partition("=")
        if sep:
            datos[clave.strip()] = valor.strip().strip('"')
    nombre = datos.get("PRETTY_NAME") or datos.get("NAME") or "Linux"
    bits = "64-bit" if platform.architecture()[0] == "64bit" else "32-bit"
    d = {"name": nombre, "version": datos.get("VERSION_ID", ""), "kernel": env.release(), "architecture": bits}
    return _res(OK, f'{nombre} · kernel {d["kernel"]}', d, [], {"os": nombre})


def _red(env):
    try:
        direcciones = env.psutil.net_if_addrs()
    except Exception:
        direcciones = {}
    adaptadores = []
    for carpeta in env.listar("/sys/class/net/*"):
        nombre = carpeta.rsplit("/", 1)[-1]
        if nombre == "lo" or not env.existe(f"{carpeta}/device"):
            continue  # solo adaptadores físicos (no puentes, VPN ni contenedores)
        if env.existe(f"{carpeta}/wireless") or env.existe(f"{carpeta}/phy80211"):
            tipo = "Inalámbrica (Wi-Fi)"
        elif env.leer(f"{carpeta}/type") == "1":
            tipo = "Cableada (Ethernet)"
        else:
            tipo = None
        ips = [x.address for x in direcciones.get(nombre, []) if x.family == socket.AF_INET]
        mac = limpio(env.leer(f"{carpeta}/address"))
        adaptadores.append({"name": nombre, "connection_name": nombre, "type": tipo, "type_inferred": False,
                            "mac": "" if mac == "00:00:00:00:00:00" else mac.upper(),
                            "connected": env.leer(f"{carpeta}/operstate") == "up", "ipv4": ips,
                            "manufacturer": ""})
    if not adaptadores:
        return _res(NO_DISPONIBLE, "No se detectaron adaptadores de red físicos")
    resumen = ", ".join(f'{a["type"] or "Red"} ({"conectado" if a["connected"] else "desconectado"})'
                        for a in adaptadores)
    return _res(OK, resumen, {"adapters": adaptadores})


def _capacidades_bateria(env) -> tuple[int | None, int | None]:
    """(diseño, máxima actual) en mWh (o en proporción equivalente si solo hay carga en µAh)."""
    for carpeta in env.listar("/sys/class/power_supply/BAT*"):
        diseno = _num(env.leer(f"{carpeta}/energy_full_design"), int)
        actual = _num(env.leer(f"{carpeta}/energy_full"), int)
        if diseno and actual:
            return diseno // 1000, actual // 1000  # µWh -> mWh
        diseno = _num(env.leer(f"{carpeta}/charge_full_design"), int)
        actual = _num(env.leer(f"{carpeta}/charge_full"), int)
        voltaje = _num(env.leer(f"{carpeta}/voltage_min_design"), int)
        if diseno and actual and voltaje:
            return diseno * voltaje // 10 ** 9, actual * voltaje // 10 ** 9  # µAh × µV -> mWh
    return None, None


def _bateria(env):
    try:
        b = env.psutil.sensors_battery()
    except Exception:
        b = None
    if b is None:
        return _res(NO_COMPATIBLE, "No aplica: no se detectó batería (equipo de escritorio o sin batería)")
    d = {"percent": b.percent, "plugged": b.power_plugged}
    faltan = []
    cd, cf = _capacidades_bateria(env)
    if cd and cf:
        d.update(design_mwh=cd, full_mwh=cf, wear_pct=round(max(0.0, (1 - cf / cd) * 100), 1))
    else:
        faltan.append(_faltante("Desgaste de la batería", NO_DISPONIBLE))
    detalle = f"{b.percent:.0f} %" + (" · conectada" if b.power_plugged else " · en batería")
    if "wear_pct" in d:
        detalle += f' · desgaste estimado {d["wear_pct"]:.0f} %'
    return _res(OK, detalle, d, faltan)


def _edid(datos: bytes) -> dict | None:
    """Nombre, fabricante (código PNP) y año de un monitor a partir de su EDID."""
    if len(datos) < 128 or datos[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return None
    codigo = (datos[8] << 8) | datos[9]
    fab = "".join(chr(((codigo >> s) & 0x1F) + 64) for s in (10, 5, 0))
    nombre = ""
    for i in range(54, 126, 18):
        if datos[i:i + 3] == b"\x00\x00\x00" and datos[i + 3] == 0xFC:
            nombre = datos[i + 5:i + 18].split(b"\n")[0].decode("ascii", "ignore").strip()
    return {"name": nombre, "manufacturer": fab, "year": datos[17] + 1990 if datos[17] else None}


def _otros(env):
    monitores = []
    for carpeta in env.listar("/sys/class/drm/card*-*"):
        if env.leer(f"{carpeta}/status") != "connected":
            continue
        monitor = _edid(env.leer_bytes(f"{carpeta}/edid") or b"")
        if monitor:
            monitores.append(monitor)
    audio = []
    for linea in (env.leer("/proc/asound/cards") or "").splitlines():
        m = re.match(r"\s*\d+\s+\[[^\]]*\]:\s*(.*?)\s+-\s+(.*)$", linea)
        if m:
            audio.append({"name": limpio(m.group(2)), "manufacturer": ""})
    if not monitores and not audio:
        return _res(NO_DISPONIBLE, "No se detectaron monitor ni dispositivos de audio")
    faltan = ([_faltante("Monitor", NO_DISPONIBLE)] if not monitores else []) + \
             ([_faltante("Audio", NO_DISPONIBLE)] if not audio else [])
    detalle = f"{len(monitores)} monitor(es) · {len(audio)} dispositivo(s) de audio"
    return _res(OK, detalle, {"monitors": monitores, "audio": audio}, faltan)


def _zonas_termicas(env) -> list[dict]:
    """Zonas térmicas del kernel (como ACPI en Windows: no son necesariamente la CPU)."""
    temps = []
    for carpeta in env.listar("/sys/class/thermal/thermal_zone*"):
        valor = _num(env.leer(f"{carpeta}/temp"))
        if valor is not None and 0 < valor / 1000 < 120:
            temps.append({"name": env.leer(f"{carpeta}/type") or "Zona térmica", "value": round(valor / 1000, 1),
                          "source": "zona térmica del kernel (no es necesariamente la CPU)"})
    return temps


def _sensores(env):
    lecturas = _lecturas(env)
    temps = [{"name": l["name"], "value": round(l["value"], 1), "source": FUENTE, "hw": l["hw"],
              "device": l["device"]}
             for l in lecturas if l["type"] == "Temperature" and _temp_valida(l["value"])]
    ventiladores = [{"name": l["name"], "rpm": l["value"], "hw": l["hw"], "device": l["device"]}
                    for l in lecturas if l["type"] == "Fan" and 0 <= l["value"] < 20000]
    cpu = _cpu_sensores(lecturas)
    cpu_temp, fuente_cpu = (cpu["temp_c"], FUENTE) if cpu["temp_c"] is not None else (None, None)
    if not temps:
        temps = _zonas_termicas(env)
        if temps:
            cpu_temp, fuente_cpu = max(t["value"] for t in temps), "zona térmica"
    if not temps and not ventiladores:
        return _res(NO_DISPONIBLE, "No disponible. El equipo no expone sensores de temperatura "
                                   "(pruebe instalar lm-sensors y ejecutar sudo sensors-detect)")
    faltan = [] if fuente_cpu == FUENTE else [_faltante("Temperatura real de la CPU", NO_DISPONIBLE)]
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
    metricas = {"cpu_temp": round(cpu_temp, 1)} if cpu_temp is not None else {}
    if cpu.get("temp_max_core_c") is not None:
        metricas["cpu_temp_max_core"] = cpu["temp_max_core_c"]
    sistema = [f["rpm"] for f in ventiladores if f.get("hw") != "gpu"]
    if sistema:
        metricas["fan_max_rpm"] = max(sistema)
    alerta = fuente_cpu == FUENTE and cpu_temp is not None and cpu_temp >= 90
    datos = {"temperatures": temps, "fans": ventiladores, "cpu_temp_source": fuente_cpu, "reader": "hwmon"}
    return _res(OK, " · ".join(partes), datos, faltan, None, metricas, alerta)


FUNCIONES = {"identity": _identidad, "cpu": _cpu, "memory": _memoria, "storage": _almacenamiento,
             "graphics": _graficos, "motherboard": _placa, "os": _sistema, "network": _red,
             "battery": _bateria, "other": _otros, "sensors": _sensores}


def unidades_extraibles(env=None) -> list[str]:
    """Puntos de montaje de memorias USB y tarjetas (dispositivo extraíble o conectado por USB)."""
    env = env or EntornoLinux()
    salida = []
    for p in env.psutil.disk_partitions(all=False):
        if not p.device.startswith("/dev/"):
            continue
        nombre = p.device.rsplit("/", 1)[-1]
        base = re.sub(r"p?\d+$", "", nombre) if not nombre.startswith(("nvme", "mmcblk")) else \
            re.sub(r"p\d+$", "", nombre)
        extraible = (env.leer(f"/sys/block/{base}/removable") or "0") == "1"
        if extraible or "/usb" in env.ruta_real(f"/sys/block/{base}"):
            salida.append(p.mountpoint)
    return salida
