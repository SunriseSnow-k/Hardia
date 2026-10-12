import socket
from types import SimpleNamespace as NS

import pytest

from app.hardware import diag_file
from app.hardware.inventory import (FALLO, NO_AUTORIZADO, NO_COMPATIBLE, NO_DISPONIBLE, OK,
                                    compare_captures, identifiers_from_scan, inventory_rows)
from app.hardware.scanner import (COMPONENT_NAMES, clasificar_error, run_scan, serie_valida,
                                  uuid_valido)

GB = 1024 ** 3


def _psutil(bateria=True, falla_ram=False):
    def ram():
        if falla_ram:
            raise OSError("fallo simulado")
        return NS(total=16 * GB - 300_000_000, available=7 * GB, percent=82.0)

    return NS(
        cpu_percent=lambda interval=0: 76.0, cpu_count=lambda logical=True: 8 if logical else 4,
        virtual_memory=ram,
        disk_partitions=lambda all=False: [], disk_usage=lambda p: NS(total=1, free=1, used=0, percent=0),
        net_if_addrs=lambda: {"Wi-Fi": [NS(family=socket.AF_INET, address="192.168.1.20")]},
        sensors_battery=lambda: NS(percent=64, power_plugged=True) if bateria else None)


def _wmi_basico(laptop=True):
    return NS(
        Win32_ComputerSystem=lambda: [NS(Manufacturer="HP", Model="Laptop 15-dw", SystemType="x64-based PC")],
        Win32_ComputerSystemProduct=lambda: [NS(UUID="4C4C4544-0042-4A10-8057-B8C04F4D3532",
                                                IdentifyingNumber="5CD1234ABC")],
        Win32_BIOS=lambda: [NS(SerialNumber="5CD1234ABC", SMBIOSBIOSVersion="F.21", Manufacturer="Insyde",
                               ReleaseDate="20230612000000.000000+000")],
        Win32_BaseBoard=lambda: [NS(Manufacturer="HP", Product="8A12", SerialNumber="PBOARD0001", Version="KBC 5A")],
        Win32_Processor=lambda: [NS(Name="Intel(R) Core(TM) i5-1135G7", Manufacturer="GenuineIntel",
                                    NumberOfCores=4, NumberOfLogicalProcessors=8, MaxClockSpeed=2419,
                                    Architecture=9)],
        Win32_PhysicalMemory=lambda: [
            NS(Capacity=8 * GB, DeviceLocator="DIMM A", SMBIOSMemoryType=26, ConfiguredClockSpeed=3200,
               FormFactor=12, Manufacturer="Samsung", PartNumber="M471A1K43"),
            NS(Capacity=8 * GB, DeviceLocator="DIMM B", SMBIOSMemoryType=26, Speed=3200, FormFactor=12,
               Manufacturer="Samsung", PartNumber="M471A1K43")],
        Win32_DiskDrive=lambda: [
            NS(Index=0, Model="KINGSTON SA400S37", Manufacturer="(Standard disk drives)", Size=512_110_190_592,
               MediaType="Fixed hard disk media", InterfaceType="SCSI"),
            NS(Index=1, Model="TOSHIBA MQ01", Size=1_000_204_886_016, MediaType="Fixed hard disk media"),
            NS(Index=2, Model="Kingston USB", Size=16_000_000_000, MediaType="Removable Media")],
        Win32_LogicalDisk=lambda: [
            NS(DeviceID="C:", FileSystem="NTFS", Size=475_000_000_000, FreeSpace=64_000_000_000, DriveType=3,
               VolumeName="Windows"),
            NS(DeviceID="E:", FileSystem="FAT32", Size=16_000_000_000, FreeSpace=1, DriveType=2)],
        Win32_VideoController=lambda: [
            NS(Name="Intel(R) Iris(R) Xe Graphics", AdapterCompatibility="Intel", AdapterRAM=1_073_741_824,
               DriverVersion="31.0.101"),
            NS(Name="NVIDIA GeForce MX350", AdapterCompatibility="NVIDIA", AdapterRAM=4_294_967_295)],
        Win32_OperatingSystem=lambda: [NS(Caption="Microsoft Windows 11 Pro", Version="10.0.22631",
                                          BuildNumber="22631", OSArchitecture="64-bit")],
        Win32_NetworkAdapter=lambda: [
            NS(PhysicalAdapter=True, Name="Intel(R) Wi-Fi 6 AX201", NetConnectionID="Wi-Fi",
               MACAddress="aa-bb-cc-dd-ee-ff", NetConnectionStatus=2, Manufacturer="Intel"),
            NS(PhysicalAdapter=False, Name="Hyper-V Virtual Ethernet", NetConnectionID="vEthernet")],
        Win32_SoundDevice=lambda: [NS(Name="Realtek Audio", Manufacturer="Realtek")])


def _env(laptop=True, wmi_extra=None, psutil=None, base=None):
    c = base or _wmi_basico()
    espacios = {
        r"root\Microsoft\Windows\Storage": NS(MSFT_PhysicalDisk=lambda: [
            NS(DeviceId="0", MediaType=4, BusType=11, HealthStatus=0),
            NS(DeviceId="1", MediaType=3, BusType=11, HealthStatus=1)]),
        r"root\wmi": NS(
            BatteryStaticData=lambda: [NS(DesignedCapacity=50000)],
            BatteryFullChargedCapacity=lambda: [NS(FullChargedCapacity=42500)],
            WmiMonitorID=lambda: [NS(UserFriendlyName=[76, 71, 32, 50, 52, 0], ManufacturerName=[71, 83, 77, 0],
                                     YearOfManufacture=2021)],
            MSAcpi_ThermalZoneTemperature=lambda: [NS(CurrentTemperature=3430, InstanceName="TZ00")]),
        r"root\LibreHardwareMonitor": NS(Sensor=lambda: [
            NS(SensorType="Temperature", Name="CPU Package", Value=71.0),
            NS(SensorType="Temperature", Name="GPU Core", Value=55.0),
            NS(SensorType="Temperature", Name="Disco", Value=0.0),
            NS(SensorType="Fan", Name="Fan #1", Value=2300.0)]),
    }
    espacios.update(wmi_extra or {})

    def ns(nombre):
        if nombre not in espacios:
            raise RuntimeError("Invalid namespace")
        o = espacios[nombre]
        if isinstance(o, Exception):
            raise o
        return o

    return NS(c=c, ns=ns, psutil=psutil or _psutil(), hostname=lambda: "LAPTOP-ABC", machine=lambda: "AMD64",
              processor=lambda: "Intel64 Family 6")


def test_escaneo_completo():
    pasos = []
    data = run_scan(lambda i, n, d, s: pasos.append((i, n, s)), env=_env())
    assert [c["name"] for c in data["components"]] == COMPONENT_NAMES and len(pasos) == len(COMPONENT_NAMES)
    assert all(c["status"] in ("ok", "warn", "error") for c in data["components"])
    inv, disp, resumen, metricas = data["inventory"], data["availability"], data["summary"], data["metrics"]
    assert all(v["status"] == OK for v in disp.values())
    assert inv["identity"]["manufacturer"] == "HP" and inv["identity"]["serial"] == "5CD1234ABC"
    assert inv["identity"]["uuid"] == "4C4C4544-0042-4A10-8057-B8C04F4D3532"
    assert inv["identity"]["architecture"] == "x64"
    assert inv["cpu"]["manufacturer"] == "Intel" and inv["cpu"]["cores"] == 4 and inv["cpu"]["threads"] == 8
    assert inv["cpu"]["max_mhz"] == 2419
    assert inv["memory"]["total_gb"] == 15.7 and len(inv["memory"]["modules"]) == 2
    assert inv["memory"]["modules"][0]["type"] == "DDR4" and inv["memory"]["modules"][0]["form_factor"] == "SO-DIMM"
    assert inv["memory"]["modules"][1]["speed_mhz"] == 3200
    fis = inv["storage"]["physical"]
    assert [f["media"] for f in fis] == ["SSD", "HDD"] and len(fis) == 2  # el USB no se incluye
    assert fis[0]["health"] == "Saludable" and fis[1]["health"] == "Advertencia"
    assert fis[0]["bus"] == "SATA" and fis[0]["manufacturer"] == ""
    assert [v["drive"] for v in inv["storage"]["logical"]] == ["C:"]
    gpus = inv["graphics"]["adapters"]
    assert gpus[0]["vram_gb"] == 1.0 and gpus[1]["vram_gb"] is None  # 4 GB: valor no fiable
    assert inv["motherboard"]["bios_date"] == "2023-06-12" and inv["motherboard"]["serial"] == "PBOARD0001"
    assert inv["os"]["name"] == "Windows 11 Pro" and inv["os"]["architecture"] == "64-bit"
    red = inv["network"]["adapters"]
    assert len(red) == 1 and red[0]["type"] == "Inalámbrica (Wi-Fi)" and red[0]["ipv4"] == ["192.168.1.20"]
    assert inv["battery"]["wear_pct"] == 15.0
    assert inv["other"]["monitors"][0]["name"] == "LG 24" and inv["other"]["audio"][0]["name"] == "Realtek Audio"
    assert inv["sensors"]["fans"][0]["rpm"] == 2300.0
    assert [t["name"] for t in inv["sensors"]["temperatures"]] == ["CPU Package", "GPU Core"]  # 0 °C descartado
    # compatibilidad con el motor de diagnóstico
    assert resumen["ram"] == "16 GB" and resumen["storage"] == "SSD 512 GB" and resumen["os"] == "Windows 11 Pro"
    assert resumen["description"] == "HP Laptop 15-dw" and resumen["serial"] == "5CD1234ABC"
    assert metricas["cpu_temp"] == 71.0 and metricas["cpu_usage"] == 76.0 and metricas["ram_usage"] == 82.0
    assert metricas["disk_used_pct"] == pytest.approx(86.5, abs=0.1)
    almacenamiento = [c for c in data["components"] if c["name"] == "Almacenamiento"][0]
    assert almacenamiento["status"] == "warn" and "Advertencia" in almacenamiento["detail"]


def test_equipo_de_escritorio_sin_bateria():
    data = run_scan(env=_env(psutil=_psutil(bateria=False)))
    assert data["availability"]["battery"]["status"] == NO_COMPATIBLE
    assert "battery" not in data["inventory"]
    comp = [c for c in data["components"] if c["name"] == "Batería"][0]
    assert comp["status"] == "ok" and comp["detail"].startswith("No aplica")


def test_sin_permisos_se_distingue_de_no_disponible():
    denegado = RuntimeError("Access denied 0x80041003")
    extra = {r"root\wmi": denegado, r"root\LibreHardwareMonitor": RuntimeError("Invalid namespace")}
    data = run_scan(env=_env(wmi_extra=extra))
    disp = data["availability"]
    assert disp["sensors"]["status"] == NO_AUTORIZADO
    assert disp["battery"]["status"] == OK  # existe batería; falta el desgaste
    assert disp["battery"]["faltantes"] == [{"campo": "Desgaste de la batería", "motivo": NO_AUTORIZADO}]
    assert "wear_pct" not in data["inventory"]["battery"]
    assert "cpu_temp" not in data["metrics"]
    assert "monitors" in data["inventory"]["other"] and data["inventory"]["other"]["monitors"] == []
    assert any(f["campo"] == "Monitor" and f["motivo"] == NO_AUTORIZADO for f in disp["other"]["faltantes"])


def test_respaldo_acpi_sin_librehardwaremonitor():
    extra = {r"root\LibreHardwareMonitor": RuntimeError("Invalid namespace")}
    data = run_scan(env=_env(wmi_extra=extra))
    t = data["inventory"]["sensors"]["temperatures"][0]
    assert t["value"] == pytest.approx(69.9, abs=0.1) and "ACPI" in t["source"]
    assert data["inventory"]["sensors"]["cpu_temp_source"] == "ACPI"


def test_sin_wmi_no_se_rompe():
    base = NS()  # sin ninguna clase WMI
    env = _env(base=base)
    env.c = None
    env.ns = lambda n: (_ for _ in ()).throw(RuntimeError("WMI no disponible"))
    data = run_scan(env=env)
    assert [c["name"] for c in data["components"]] == COMPONENT_NAMES
    assert data["summary"]["description"] == "LAPTOP-ABC"
    assert data["inventory"]["identity"]["hostname"] == "LAPTOP-ABC"
    assert data["inventory"]["memory"]["total_gb"] == 15.7
    assert data["availability"]["graphics"]["status"] == NO_DISPONIBLE
    assert data["availability"]["sensors"]["status"] == NO_DISPONIBLE
    assert {f["campo"] for f in data["availability"]["identity"]["faltantes"]} >= {"Fabricante", "Modelo"}


def test_un_colector_que_falla_no_detiene_el_resto():
    data = run_scan(env=_env(psutil=_psutil(falla_ram=True)))
    assert data["availability"]["memory"]["status"] == FALLO
    assert [c for c in data["components"] if c["name"] == "RAM"][0]["status"] == "error"
    assert data["availability"]["os"]["status"] == OK and "memory" not in data["inventory"]


def test_clasificar_error():
    assert clasificar_error(PermissionError("x")) == NO_AUTORIZADO
    assert clasificar_error(Exception("OLE error 0x80041003")) == NO_AUTORIZADO
    assert clasificar_error(Exception("Invalid class")) == NO_DISPONIBLE
    assert clasificar_error(Exception("(-2147217394, 'x')")) == NO_DISPONIBLE
    assert clasificar_error(ValueError("otra cosa")) == FALLO


def test_valores_basura_se_descartan():
    for malo in ("To Be Filled By O.E.M.", "00000000", "0", "", None, "  ", "AA"):
        assert serie_valida(malo) == ""
    assert serie_valida("5CD1234ABC") == "5CD1234ABC"
    assert uuid_valido("FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF") == ""
    assert uuid_valido("00000000-0000-0000-0000-000000000000") == ""
    assert uuid_valido("no-es-uuid") == ""
    assert uuid_valido("4c4c4544-0042-4a10-8057-b8c04f4d3532") == "4C4C4544-0042-4A10-8057-B8C04F4D3532"


def test_filas_del_inventario():
    data = run_scan(env=_env(psutil=_psutil(bateria=False)))
    filas = inventory_rows(data)
    por = {(f["category"], f["label"]): f for f in filas}
    assert por[("Procesador", "Modelo")]["value"].startswith("Intel(R) Core(TM)")
    assert "DDR4" in por[("Memoria RAM", "Módulo 1")]["value"]
    assert "Salud: Saludable" in por[("Almacenamiento", "Unidad física 1")]["value"]
    assert "sin fuente fiable" not in por[("Almacenamiento", "Unidad física 1")]["value"]
    assert por[("Batería", "Estado de la detección")]["status"] == NO_COMPATIBLE
    assert por[("Gráficos", "Memoria gráfica (WMI no la informa o supera los 4 GB)")]["status"] == NO_DISPONIBLE
    assert por[("Red", "Adaptador 1")]["value"].count("(inferido)") == 1
    assert all(set(f) == {"category", "label", "value", "status"} for f in filas)


def test_filas_de_un_escaneo_antiguo():
    viejo = {"format": "SD-DIAG", "version": 1, "summary": {}, "metrics": {},
             "components": [{"name": "CPU", "detail": "i5", "status": "ok"},
                            {"name": "Temperaturas", "detail": "No disponible", "status": "warn"}]}
    filas = inventory_rows(viejo)
    assert [(f["category"], f["status"]) for f in filas] == [("CPU", OK), ("Temperaturas", NO_DISPONIBLE)]
    assert inventory_rows({}) == []


def test_identificadores_del_equipo():
    ids = identifiers_from_scan(run_scan(env=_env()))
    assert ("uuid", "4C4C4544-0042-4A10-8057-B8C04F4D3532") in ids
    assert ("serial", "5CD1234ABC") in ids and ("board_serial", "PBOARD0001") in ids
    assert ("mac", "AA:BB:CC:DD:EE:FF") in ids and len(ids) == 4
    assert identifiers_from_scan({"summary": {"serial": "abc123"}}) == [("serial", "ABC123")]
    assert identifiers_from_scan({}) == []


def test_comparacion_de_capturas():
    antes = run_scan(env=_env())
    despues = run_scan(env=_env())
    assert compare_captures(antes, despues) == []
    despues["inventory"]["memory"]["total_gb"] = 31.7
    despues["inventory"]["storage"]["physical"].append(
        {"model": "NVME 1TB", "size_bytes": 1_000_204_886_016})
    despues["inventory"]["battery"]["wear_pct"] = 40.0
    cambios = {c["area"]: c for c in compare_captures(antes, despues)}
    assert cambios["Memoria RAM"] == {"area": "Memoria RAM", "antes": "16 GB", "despues": "32 GB"}
    assert "NVME 1TB" in cambios["Unidades de almacenamiento"]["despues"]
    assert cambios["Desgaste de batería"]["despues"] == "40 %"
    # un dato que falta en una de las capturas no es un cambio
    del despues["inventory"]["graphics"]
    assert "Gráficos" not in {c["area"] for c in compare_captures(antes, despues)}


def test_archivo_diag_version_2_ida_y_vuelta(tmp_path):
    data = run_scan(env=_env())
    ruta = diag_file.save_scan(data, tmp_path / "a.diag")
    leido = diag_file.load_scan(ruta)
    assert leido["version"] == 2 and leido["inventory"]["cpu"]["cores"] == 4
    assert [f["label"] for f in inventory_rows(leido)] == [f["label"] for f in inventory_rows(data)]
    ruta.write_text('{"format":"SD-DIAG","summary":{},"components":[],"inventory":"x"}', encoding="utf-8")
    with pytest.raises(ValueError):
        diag_file.load_scan(ruta)