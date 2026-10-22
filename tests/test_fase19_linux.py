"""Fase 19: el programa en Linux. Los colectores se prueban con un Linux simulado (archivos de /sys y
/proc y salidas de dmidecode, smartctl y lspci), así las pruebas corren en cualquier sistema."""
import io
import json
import socket
import sys
import tarfile
from fnmatch import fnmatchcase
from types import SimpleNamespace as NS

import pytest

from app.ai import paquete
from app.hardware import linux
from app.hardware.inventory import NO_AUTORIZADO, NO_COMPATIBLE, OK, inventory_rows
from app.hardware.scanner import COMPONENT_NAMES, local_identifiers, read_cpu_temperature, run_scan
from app.health import evaluate, load_references

GB = 1024 ** 3


def _edid(nombre: str, fabricante: str = "DEL", anio: int = 2021) -> bytes:
    d = bytearray(128)
    d[:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    codigo = sum((ord(c) - 64) << s for c, s in zip(fabricante, (10, 5, 0), strict=True))
    d[8], d[9] = codigo >> 8, codigo & 0xFF
    d[17] = anio - 1990
    d[54:59] = b"\x00\x00\x00\xfc\x00"
    d[59:72] = (nombre.encode() + b"\n").ljust(13, b" ")
    return bytes(d)


DMIDECODE = """# dmidecode 3.5
Handle 0x0040, DMI type 17, 92 bytes
Memory Device
\tSize: 8 GB
\tForm Factor: SODIMM
\tLocator: DIMM A
\tType: DDR4
\tSpeed: 3200 MT/s
\tManufacturer: Samsung
\tPart Number: M471A1K43
\tConfigured Memory Speed: 2666 MT/s

Handle 0x0041, DMI type 17, 92 bytes
Memory Device
\tSize: No Module Installed
\tLocator: DIMM B
"""

SMART_NVME = {"smart_status": {"passed": True}, "temperature": {"current": 41},
              "nvme_smart_health_information_log": {"percentage_used": 7, "available_spare": 100,
                                                    "data_units_written": 20_000_000}}

ARCHIVOS = {
    "/sys/class/dmi/id/sys_vendor": "LENOVO", "/sys/class/dmi/id/product_name": "20XW00",
    "/sys/class/dmi/id/product_serial": "PF2ABCDE",
    "/sys/class/dmi/id/product_uuid": "4c4c4544-0042-4a10-8057-b8c04f4d3532",
    "/sys/class/dmi/id/board_vendor": "LENOVO", "/sys/class/dmi/id/board_name": "20XW00",
    "/sys/class/dmi/id/board_serial": "L1HF1234567", "/sys/class/dmi/id/board_version": "SDK0J40697",
    "/sys/class/dmi/id/bios_vendor": "LENOVO", "/sys/class/dmi/id/bios_version": "N32ET75W",
    "/sys/class/dmi/id/bios_date": "06/12/2023",
    "/proc/cpuinfo": "processor\t: 0\nvendor_id\t: GenuineIntel\nmodel name\t: 11th Gen Intel(R) Core(TM) "
                     "i5-1135G7 @ 2.40GHz\nphysical id\t: 0\n\nprocessor\t: 1\nvendor_id\t: GenuineIntel\n"
                     "physical id\t: 0\n",
    "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq": "4200000",
    # disco NVMe interno y memoria USB (extraíble: no cuenta)
    "/sys/block/nvme0n1/size": str(1_000_204_886_016 // 512), "/sys/block/nvme0n1/removable": "0",
    "/sys/block/nvme0n1/queue/rotational": "0", "/sys/block/nvme0n1/device/model": "SAMSUNG MZVL21T0",
    "/sys/block/sdb/size": "31260672", "/sys/block/sdb/removable": "1",
    "/sys/block/loop0/size": "1000",
    # gráficos
    "/sys/class/drm/card0/device/vendor": "0x8086", "/sys/class/drm/card0/device/uevent": "DRIVER=i915\nPCI_ID=8086:9A49",
    "/sys/class/drm/card0-eDP-1/status": "connected", "/sys/class/drm/card0-HDMI-A-1/status": "disconnected",
    # sistema
    "/etc/os-release": 'NAME="Ubuntu"\nVERSION_ID="24.04"\nPRETTY_NAME="Ubuntu 24.04.1 LTS"\n',
    # red
    "/sys/class/net/wlp0s20f3/address": "aa:bb:cc:dd:ee:ff", "/sys/class/net/wlp0s20f3/operstate": "up",
    "/sys/class/net/wlp0s20f3/type": "1",
    "/sys/class/net/docker0/address": "02:42:00:00:00:01", "/sys/class/net/lo/address": "00:00:00:00:00:00",
    # batería
    "/sys/class/power_supply/BAT0/energy_full_design": "50000000",
    "/sys/class/power_supply/BAT0/energy_full": "42500000",
    # audio
    "/proc/asound/cards": " 0 [PCH            ]: HDA-Intel - HDA Intel PCH\n                      HDA Intel PCH at 0x6",
    # sensores: CPU (coretemp), disco (nvme) y un ventilador (thinkpad)
    "/sys/class/hwmon/hwmon0/name": "coretemp",
    "/sys/class/hwmon/hwmon0/temp1_input": "71000", "/sys/class/hwmon/hwmon0/temp1_label": "Package id 0",
    "/sys/class/hwmon/hwmon0/temp2_input": "68000", "/sys/class/hwmon/hwmon0/temp2_label": "Core 0",
    "/sys/class/hwmon/hwmon0/temp3_input": "74000", "/sys/class/hwmon/hwmon0/temp3_label": "Core 1",
    "/sys/class/hwmon/hwmon1/name": "nvme", "/sys/class/hwmon/hwmon1/device/model": "SAMSUNG MZVL21T0",
    "/sys/class/hwmon/hwmon1/temp1_input": "39850", "/sys/class/hwmon/hwmon1/temp1_label": "Composite",
    "/sys/class/hwmon/hwmon2/name": "thinkpad", "/sys/class/hwmon/hwmon2/fan1_input": "2300",
}
BINARIOS = {"/sys/class/drm/card0-eDP-1/edid": _edid("DELL P2422H")}
CARPETAS = {"/sys/class/net/wlp0s20f3/device", "/sys/class/net/wlp0s20f3/wireless"}
ENLACES = {"/sys/block/nvme0n1": "/sys/devices/pci0000:00/0000:00:06.0/nvme/nvme0/nvme0n1",
           "/sys/block/sdb": "/sys/devices/pci0000:00/0000:00:14.0/usb2/2-1/block/sdb",
           "/sys/class/drm/card0/device": "/sys/devices/pci0000:00/0000:00:02.0"}
COMANDOS = {("dmidecode", "-t", "17"): DMIDECODE,
            ("smartctl", "-j", "-a", "/dev/nvme0n1"): json.dumps(SMART_NVME),
            ("lspci", "-mm", "-s", "0000:00:02.0"):
                '00:02.0 "VGA compatible controller" "Intel Corporation" "TigerLake-LP GT2 [Iris Xe Graphics]"'}


def _psutil():
    return NS(cpu_percent=lambda interval=0: 12.0, cpu_count=lambda logical=True: 8 if logical else 4,
              virtual_memory=lambda: NS(total=16 * GB - 300_000_000, available=9 * GB, percent=41.0),
              disk_partitions=lambda all=False: [
                  NS(device="/dev/nvme0n1p2", mountpoint="/", fstype="ext4", opts="rw"),
                  NS(device="/dev/nvme0n1p1", mountpoint="/boot/efi", fstype="vfat", opts="rw"),
                  NS(device="/dev/loop0", mountpoint="/snap/core/1", fstype="squashfs", opts="ro"),
                  NS(device="/dev/sdb1", mountpoint="/media/tecnico/USB", fstype="vfat", opts="rw")],
              disk_usage=lambda p: NS(total=980_000_000_000, free=400_000_000_000, used=580_000_000_000,
                                      percent=59.2),
              net_if_addrs=lambda: {"wlp0s20f3": [NS(family=socket.AF_INET, address="192.168.1.30")]},
              sensors_battery=lambda: NS(percent=80, power_plugged=False))


class LinuxSimulado:
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    sistema = "linux"

    def __init__(self, root=True, archivos=None, comandos=None, programas=("smartctl", "dmidecode", "lspci")):
        self.archivos = {**ARCHIVOS, **(archivos or {})}
        self.comandos = dict(COMANDOS) if comandos is None else comandos
        self.psutil, self.root, self.programas = _psutil(), root, programas

    def leer(self, ruta):
        v = self.archivos.get(ruta)
        return None if v is None else v.strip()

    def leer_bytes(self, ruta):
        return BINARIOS.get(ruta)

    def _rutas(self):
        rutas = set(self.archivos) | set(BINARIOS) | CARPETAS | set(ENLACES)
        for r in list(rutas):  # las carpetas que contienen archivos también existen
            partes = r.split("/")
            rutas.update("/".join(partes[:i]) for i in range(2, len(partes)))
        return rutas

    def listar(self, patron):
        n = patron.count("/")
        return sorted(r for r in self._rutas() if r.count("/") == n and fnmatchcase(r, patron))

    def existe(self, ruta):
        return ruta in self._rutas()

    def ruta_real(self, ruta):
        return ENLACES.get(ruta, ruta)

    def ejecutar(self, *args):
        return self.comandos.get(args) if (self.root or args[0] == "lspci") else None

    def tiene(self, programa):
        return programa in self.programas

    hostname = staticmethod(lambda: "tecnico-lenovo")
    machine = staticmethod(lambda: "x86_64")
    processor = staticmethod(lambda: "x86_64")
    release = staticmethod(lambda: "6.8.0-45-generic")

    def es_admin(self):
        return self.root


def test_escaneo_linux_completo():
    data = run_scan(env=LinuxSimulado())
    assert [c["name"] for c in data["components"]] == COMPONENT_NAMES
    inv, disp, resumen, metricas = data["inventory"], data["availability"], data["summary"], data["metrics"]
    assert all(v["status"] == OK for v in disp.values()), {k: v for k, v in disp.items() if v["status"] != OK}
    ident = inv["identity"]
    assert ident["manufacturer"] == "LENOVO" and ident["serial"] == "PF2ABCDE" and ident["architecture"] == "x64"
    assert ident["uuid"] == "4C4C4544-0042-4A10-8057-B8C04F4D3532"
    cpu = inv["cpu"]
    assert cpu["manufacturer"] == "Intel" and cpu["name"].startswith("11th Gen Intel") and cpu["max_mhz"] == 4200
    assert cpu["cores"] == 4 and cpu["threads"] == 8 and cpu["temp_c"] == 71.0 and cpu["temp_max_core_c"] == 74.0
    modulos = inv["memory"]["modules"]
    assert len(modulos) == 1 and modulos[0]["type"] == "DDR4" and modulos[0]["form_factor"] == "SO-DIMM"
    assert modulos[0]["nominal_mhz"] == 3200 and modulos[0]["configured_mhz"] == 2666
    discos = inv["storage"]["physical"]
    assert len(discos) == 1  # la memoria USB y loop0 no son discos del equipo
    d = discos[0]
    assert d["device"] == "/dev/nvme0n1" and d["media"] == "SSD" and d["bus"] == "NVMe" and not d["external"]
    assert d["health"] == "Saludable" and d["health_source"] == "SMART (smartctl)"
    assert d["life_pct"] == 93.0 and d["temp_c"] == 41.0 and d["written_gb"] == 10240.0
    assert [v["drive"] for v in inv["storage"]["logical"]] == ["/"]
    gpu = inv["graphics"]["adapters"][0]
    assert gpu["name"] == "Intel Iris Xe Graphics" and gpu["manufacturer"] == "Intel"
    assert gpu["driver_version"] == "i915"
    assert inv["motherboard"]["bios_date"] == "2023-06-12" and inv["motherboard"]["serial"] == "L1HF1234567"
    assert inv["os"] == {"name": "Ubuntu 24.04.1 LTS", "version": "24.04", "kernel": "6.8.0-45-generic",
                         "architecture": inv["os"]["architecture"]}
    red = inv["network"]["adapters"]
    assert len(red) == 1 and red[0]["type"] == "Inalámbrica (Wi-Fi)" and red[0]["ipv4"] == ["192.168.1.30"]
    assert red[0]["mac"] == "AA:BB:CC:DD:EE:FF" and red[0]["connected"]
    assert inv["battery"]["wear_pct"] == 15.0 and inv["battery"]["design_mwh"] == 50000
    assert inv["other"]["monitors"] == [{"name": "DELL P2422H", "manufacturer": "DEL", "year": 2021}]
    assert inv["other"]["audio"][0]["name"] == "HDA Intel PCH"
    assert inv["sensors"]["fans"][0]["rpm"] == 2300.0 and inv["sensors"]["cpu_temp_source"] == linux.FUENTE
    nombres = [t["name"] for t in inv["sensors"]["temperatures"]]
    assert "CPU Package" in nombres and "Core #1" in nombres and "Composite Temperature" in nombres
    assert resumen["os"] == "Ubuntu 24.04.1 LTS" and resumen["storage"] == "SSD 1 TB" and resumen["ram"] == "16 GB"
    assert metricas["cpu_temp"] == 71.0 and metricas["disk_life_min_pct"] == 93.0 and metricas["fan_max_rpm"] == 2300


def test_sin_root_los_datos_protegidos_quedan_sin_permisos():
    sin_permiso = {r: None for r in ("/sys/class/dmi/id/product_serial", "/sys/class/dmi/id/product_uuid",
                                     "/sys/class/dmi/id/board_serial")}
    data = run_scan(env=LinuxSimulado(root=False, archivos=sin_permiso))
    disp = data["availability"]
    faltan = {f["campo"]: f["motivo"] for c in disp.values() for f in c["faltantes"]}
    assert faltan["N.º de serie"] == NO_AUTORIZADO and faltan["Módulos individuales"] == NO_AUTORIZADO
    assert faltan["Estado SMART del disco (salud y vida útil)"] == NO_AUTORIZADO
    assert data["inventory"]["storage"]["physical"][0]["temp_c"] == 39.9  # hwmon no necesita root
    filas = inventory_rows(data)
    assert any(f["label"] == "N.º de serie" and f["status"] == NO_AUTORIZADO for f in filas)


def test_equipo_sin_bateria_ni_sensores():
    sin = {r: None for r in ARCHIVOS if r.startswith(("/sys/class/hwmon", "/sys/class/power_supply"))}
    env = LinuxSimulado(archivos=sin)
    env.psutil.sensors_battery = lambda: None
    data = run_scan(env=env)
    assert data["availability"]["battery"]["status"] == NO_COMPATIBLE
    assert data["availability"]["sensors"]["status"] != OK
    assert "lm-sensors" in data["availability"]["sensors"]["detail"]


def test_gpu_amd_y_nvidia_con_sensores():
    archivos = {"/sys/class/drm/card1/device/vendor": "0x1002", "/sys/class/drm/card1/device/uevent": "DRIVER=amdgpu",
                "/sys/class/drm/card1/device/mem_info_vram_total": str(8 * GB),
                "/sys/class/hwmon/hwmon3/name": "amdgpu", "/sys/class/hwmon/hwmon3/temp1_input": "61000",
                "/sys/class/hwmon/hwmon3/temp1_label": "edge", "/sys/class/hwmon/hwmon3/temp2_input": "75000",
                "/sys/class/hwmon/hwmon3/temp2_label": "junction",
                "/sys/class/hwmon/hwmon3/device/gpu_busy_percent": "33"}
    ENLACES["/sys/class/drm/card1/device"] = "/sys/devices/pci0000:00/0000:03:00.0"
    try:
        comandos = {**COMANDOS, ("lspci", "-mm", "-s", "0000:03:00.0"):
                    '03:00.0 "VGA compatible controller" "Advanced Micro Devices, Inc. [AMD/ATI]" "Navi 23"'}
        data = run_scan(env=LinuxSimulado(archivos=archivos, comandos=comandos))
    finally:
        del ENLACES["/sys/class/drm/card1/device"]
    amd = next(a for a in data["inventory"]["graphics"]["adapters"] if a["driver_version"] == "amdgpu")
    assert amd["manufacturer"] == "AMD" and amd["vram_gb"] == 8.0
    assert amd["temp_c"] == 61.0 and amd["hotspot_c"] == 75.0 and amd["load_pct"] == 33.0
    assert data["metrics"]["gpu_hotspot"] == 75.0

    env = LinuxSimulado(comandos={("nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu,memory.total,"
                                   "memory.used,fan.speed", "--format=csv,noheader,nounits"):
                                  "NVIDIA GeForce RTX 3060, 66, 97, 12288, 3000, 45\n"})
    lecturas = linux.leer_sensores(env)["lecturas"]
    nv = [l for l in lecturas if l["device"] == "NVIDIA GeForce RTX 3060"]
    assert {(l["type"], l["name"]) for l in nv} >= {("Temperature", "GPU Core"), ("SmallData", "GPU Memory Total")}


def test_temperatura_e_identificadores_para_la_prueba_y_el_caso():
    assert read_cpu_temperature(LinuxSimulado()) == (71.0, linux.FUENTE)
    ids = local_identifiers(LinuxSimulado())
    assert ("uuid", "4C4C4544-0042-4A10-8057-B8C04F4D3532") in ids and ("mac", "AA:BB:CC:DD:EE:FF") in ids


def test_requisitos_y_unidades_usb():
    completo = LinuxSimulado()
    assert linux.requisitos_sensores(completo) == []
    falta = linux.requisitos_sensores(LinuxSimulado(root=False, programas=()))
    assert any("smartmontools" in f for f in falta) and any("sudo" in f for f in falta)
    assert linux.unidades_extraibles(completo) == ["/media/tecnico/USB"]


def test_salud_de_una_captura_de_linux_cita_sus_fuentes():
    data = run_scan(env=LinuxSimulado())
    r = evaluate(data, load_references())
    disco = next(c for c in r["componentes"] if c["clave"].startswith("disco:"))
    assert "smartctl" in disco["fuente"] and "Windows" not in disco["fuente"]
    bateria = next(c for c in r["componentes"] if c["clave"] == "bateria")
    assert bateria["fuente"].startswith("Linux") and round(bateria["pct"]) == 85
    memoria = next(c for c in r["componentes"] if c["clave"] == "memoria")
    assert memoria["fuente"].startswith("dmidecode") and round(memoria["pct"]) == 83


# ---------------- Rutas y paquete de IA ----------------
def test_carpeta_de_datos_en_linux(monkeypatch, tmp_path):
    from app import paths
    monkeypatch.setattr(paths, "VAR_DATOS", "XDG_DATA_HOME")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths.data_dir() == tmp_path / "xdg" / "SistemaDiagnostico"
    monkeypatch.delenv("XDG_DATA_HOME")
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setattr(paths.Path, "home", staticmethod(lambda: tmp_path))
    assert paths.data_dir() == tmp_path / ".local" / "share" / "SistemaDiagnostico"


def test_motor_de_ia_segun_sistema_y_procesador(monkeypatch):
    import platform
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert paquete._motor_de_este_equipo()["url"].endswith("bin-ubuntu-x64.tar.gz")
    monkeypatch.setattr(platform, "machine", lambda: "aarch64")
    assert paquete._motor_de_este_equipo()["url"].endswith("bin-ubuntu-arm64.tar.gz")
    monkeypatch.setattr(platform, "machine", lambda: "riscv64")
    assert paquete._motor_de_este_equipo()["url"] == ""


def test_instalar_motor_sin_build_para_el_equipo(monkeypatch, tmp_path):
    from app.paths import VAR_DATOS
    monkeypatch.setenv(VAR_DATOS, str(tmp_path))
    monkeypatch.setattr(paquete, "MOTOR", {"version": "", "url": "", "sha256": "", "tamano": 0})
    assert not paquete.motor_instalado()
    with pytest.raises(paquete.PaqueteError, match="no está disponible"):
        paquete.instalar_motor()


def test_extraer_motor_de_linux(monkeypatch, tmp_path):
    def agregar(t, nombre, datos=b"", enlace=None):
        info = tarfile.TarInfo(nombre)
        if enlace:
            info.type, info.linkname = tarfile.SYMTYPE, enlace
        else:
            info.size, info.mode = len(datos), 0o644
        t.addfile(info, io.BytesIO(datos) if not enlace else None)

    archivo = tmp_path / "llama.tar.gz"
    with tarfile.open(archivo, "w:gz") as t:
        agregar(t, "llama-b1/llama-server", b"\x7fELF servidor")
        agregar(t, "llama-b1/libllama.so.0.6.0", b"\x7fELF lib")
        agregar(t, "llama-b1/libllama.so.0", enlace="libllama.so.0.6.0")
        agregar(t, "llama-b1/LICENSE", b"MIT")
        agregar(t, "llama-b1/llama-cli", b"no se necesita")
        agregar(t, "llama-b1/sub/otra.so", b"subcarpeta")
        agregar(t, "llama-b1/libmala.so", enlace="/etc/passwd")
    monkeypatch.setattr(paquete, "SERVIDOR_EXE", "llama-server")
    monkeypatch.setattr(paquete, "_ARCHIVOS_MOTOR", ("llama-server",))
    destino = tmp_path / "motor"
    destino.mkdir()
    paquete._extraer_tar(archivo, destino)
    nombres = {p.name for p in destino.iterdir()}
    assert {"llama-server", "libllama.so.0.6.0", "LICENSE"} <= nombres
    assert "llama-cli" not in nombres and "otra.so" not in nombres and "libmala.so" not in nombres
    assert (destino / "libllama.so.0").read_bytes() == b"\x7fELF lib"  # enlace (o copia en Windows)
