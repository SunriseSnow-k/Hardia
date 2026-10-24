"""Lectura de sensores con LibreHardwareMonitorLib (temperaturas, cargas, ventiladores, vida útil).

La biblioteca (.NET Framework 4.7.2) va incluida en app/vendor/lhm y se carga con pythonnet, así
que LibreHardwareMonitor no necesita estar abierto. Otra carpeta puede indicarse con la variable
de entorno DIAG_LHM_DIR. Sin permisos de administrador la biblioteca carga, pero Windows no le deja
leer la temperatura de la CPU ni el SMART de los discos: esos valores llegan vacíos o en 0.

Este módulo solo devuelve lecturas normalizadas; su interpretación está en sensores.py y colectores._sensores.
"""
import ctypes
import logging
import os
import sys
import threading
import time
from pathlib import Path

from app import plataforma

log = logging.getLogger(__name__)

DLL = "LibreHardwareMonitorLib.dll"
FUENTE = "LibreHardwareMonitor"

# HardwareType de LHM -> categoría propia
_CATEGORIA = {"Cpu": "cpu", "GpuNvidia": "gpu", "GpuAmd": "gpu", "GpuIntel": "gpu", "Storage": "storage",
              "Motherboard": "motherboard", "SuperIO": "motherboard", "EmbeddedController": "motherboard",
              "Cooler": "cooler", "Memory": "memory"}
# Prefijo del Identifier (/amdcpu/0/temperature/2) cuando se lee por WMI
_PREFIJO = (("cpu", "cpu"), ("gpu", "gpu"), ("nvidia", "gpu"), ("ati", "gpu"), ("radeon", "gpu"),
            ("hdd", "storage"), ("nvme", "storage"), ("ssd", "storage"), ("storage", "storage"),
            ("lpc", "motherboard"), ("mainboard", "motherboard"), ("motherboard", "motherboard"),
            ("ec", "motherboard"), ("cooler", "cooler"), ("ram", "memory"), ("memory", "memory"))

_lock = threading.Lock()
_cargada: bool | str | None = None  # True / mensaje de error


def carpeta() -> Path:
    otra = os.environ.get("DIAG_LHM_DIR")
    if otra:
        return Path(otra)
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))  # también empaquetado
    return base / "vendor" / "lhm" if (base / "vendor").exists() else base / "app" / "vendor" / "lhm"


def es_administrador() -> bool:
    """Administrador en Windows; root en Linux."""
    return plataforma.es_administrador()


def puede_reiniciar_como_administrador() -> bool:
    """Solo Windows: en Linux la interfaz no se abre como root (ver puede_pedir_permisos)."""
    return plataforma.ES_WINDOWS


def puede_pedir_permisos() -> bool:
    """Solo Linux: los datos protegidos se piden con pkexec sin reiniciar (ver permisos_linux.py)."""
    if not plataforma.ES_LINUX:
        return False
    from .permisos_linux import disponible
    return disponible()


def reiniciar_como_administrador() -> bool:
    """Abre otra instancia del programa con permisos de administrador (Windows pide confirmación).
    True si se lanzó; el llamador debe cerrar esta instancia."""
    import subprocess
    if sys.platform != "win32":
        return False
    # --relanzado: la nueva instancia espera a que esta se cierre (el programa es de instancia única)
    extra = [a for a in sys.argv[1:] if a != "--relanzado"] + ["--relanzado"]
    if getattr(sys, "frozen", False):
        programa, args = sys.executable, extra
    else:
        programa, args = sys.executable, [os.path.abspath(sys.argv[0]), *extra]
    try:
        r = ctypes.windll.shell32.ShellExecuteW(None, "runas", programa, subprocess.list2cmdline(args),
                                                os.getcwd(), 1)
    except Exception:
        return False
    return r > 32  # <= 32: error o el usuario canceló el aviso de Windows


def requisitos_sensores() -> list[str]:
    """Lo que falta en este equipo para leer todos los sensores (vacío si no falta nada)."""
    if not plataforma.ES_WINDOWS:
        from .linux import requisitos_sensores as en_linux
        return en_linux()
    falta = []
    if not es_administrador():
        falta.append("ejecutar el programa como administrador (temperatura de CPU y SMART de los discos)")
    if pawnio_instalado() is False:
        if instalador_pawnio() is not None:
            falta.append("instalar el controlador de sensores PawnIO (incluido: botón «Instalar controlador»)")
        else:
            falta.append("instalar el controlador PawnIO (https://pawnio.eu) para la temperatura de la CPU")
    if not (carpeta() / DLL).exists():
        falta.append(f"la biblioteca {DLL} en {carpeta()}")
    return falta


PAWNIO_SETUP = "PawnIO_setup.exe"


def instalador_pawnio() -> Path | None:
    """Instalador de PawnIO que acompaña al programa (el instalador lo deja en {app}\\Controladores;
    en desarrollo está en redist). None si no está o no es Windows."""
    if sys.platform != "win32":
        return None
    if getattr(sys, "frozen", False):
        ruta = Path(sys.executable).resolve().parent / "Controladores" / PAWNIO_SETUP
    else:
        ruta = Path(__file__).resolve().parents[2] / "redist" / PAWNIO_SETUP
    return ruta if ruta.is_file() else None


def instalar_pawnio() -> bool:
    """Instala PawnIO en silencio con permisos de administrador (Windows pide confirmación) y espera
    a que termine. True si quedó instalado."""
    import subprocess
    setup = instalador_pawnio()
    if setup is None:
        return False
    ruta = str(setup).replace("'", "''")
    orden = (f"$p = Start-Process -FilePath '{ruta}' -ArgumentList '-install','-silent' -Verb RunAs "
             "-Wait -PassThru; exit $p.ExitCode")
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", orden],  # noqa: S603, S607 (orden fija)
                       capture_output=True, timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        log.warning("No se pudo ejecutar el instalador de PawnIO", exc_info=True)
        return False
    return pawnio_instalado() is True


def pawnio_instalado() -> bool | None:
    """LibreHardwareMonitor 0.9.5+ lee la temperatura de la CPU con el controlador PawnIO
    (https://pawnio.eu). None si no se pudo consultar el registro (o no es Windows)."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    clave = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO"
    for vista in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, clave, 0, winreg.KEY_READ | vista) as k:
                if winreg.QueryValueEx(k, "DisplayVersion")[0]:
                    return True
        except OSError:
            continue
    return False


def _cargar():
    """Carga la DLL una sola vez por proceso. Lanza RuntimeError con el motivo si no se puede."""
    global _cargada
    with _lock:
        if _cargada is True:
            return
        if isinstance(_cargada, str):
            raise RuntimeError(_cargada)
        dll = carpeta() / DLL
        try:
            if not dll.exists():
                raise RuntimeError(f"No disponible: no se encontró {DLL} en {dll.parent}")
            try:
                import clr  # pythonnet
            except Exception as e:
                raise RuntimeError(f"No disponible: falta pythonnet ({type(e).__name__})") from e
            if str(dll.parent) not in sys.path:
                sys.path.append(str(dll.parent))
            _resolver_dependencias(dll.parent)
            clr.AddReference(str(dll))
        except RuntimeError as e:
            _cargada = str(e)
            raise
        except Exception as e:
            _cargada = f"Fallo al cargar {DLL}: {e}"
            raise RuntimeError(_cargada) from e
        _cargada = True


def _resolver_dependencias(directorio: Path):
    """Sin un .exe.config no hay bindingRedirect: resuelve las dependencias por nombre desde la
    carpeta de la biblioteca aunque la versión pedida no coincida."""
    import System

    def resolver(_sender, args):
        nombre = str(args.Name).split(",")[0]
        ruta = directorio / f"{nombre}.dll"
        return System.Reflection.Assembly.LoadFrom(str(ruta)) if ruta.exists() else None

    System.AppDomain.CurrentDomain.AssemblyResolve += System.ResolveEventHandler(resolver)


def categoria(tipo_hw: str = "", identificador: str = "", nombre: str = "") -> str:
    t = _CATEGORIA.get(str(tipo_hw))
    if t:
        return t
    ident = str(identificador or "").lower().lstrip("/")
    for pre, cat in _PREFIJO:
        if ident.startswith(pre) or ident.split("/")[0].endswith(pre):
            return cat
    n = str(nombre or "").lower()
    return "cpu" if "cpu" in n else "gpu" if "gpu" in n else "other"


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


class MMAE_Lector:
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    """Computer de LHM abierto. Abrirlo cuesta 1-3 s: para lecturas repetidas se reutiliza.
    Uso: with MMAE_Lector() as l: lecturas = l.leer()"""

    def __init__(self):
        self._pc = None

    def __enter__(self):
        _cargar()
        from LibreHardwareMonitor.Hardware import Computer
        pc = Computer()
        for opcion in ("IsCpuEnabled", "IsGpuEnabled", "IsStorageEnabled", "IsMotherboardEnabled",
                       "IsControllerEnabled", "IsMemoryEnabled"):
            setattr(pc, opcion, True)
        pc.Open()
        self._pc = pc
        self._actualizar()
        time.sleep(0.4)  # las cargas y frecuencias necesitan dos muestras
        return self

    def _actualizar(self):
        def rec(hw):
            hw.Update()
            for sub in hw.SubHardware:
                rec(sub)
        assert self._pc is not None, "MMAE_Lector usado fuera de su bloque with"
        for hw in self._pc.Hardware:
            try:
                rec(hw)
            except Exception:  # un componente ilegible no impide leer los demás
                log.debug("LHM: no se pudo leer %s", hw, exc_info=True)
                continue

    def leer(self, actualizar: bool = True) -> list[dict]:
        """[{hw, device, type, name, value}] con valores numéricos válidos."""
        if actualizar:
            self._actualizar()
        salida = []

        def rec(hw, cat):
            for s in hw.Sensors:
                valor = _num(s.Value)
                if valor is not None:
                    salida.append({"hw": cat, "device": str(hw.Name), "type": str(s.SensorType),
                                   "name": str(s.Name), "value": valor})
            for sub in hw.SubHardware:
                rec(sub, cat)
        assert self._pc is not None, "MMAE_Lector usado fuera de su bloque with"
        for hw in self._pc.Hardware:
            try:
                rec(hw, categoria(str(hw.HardwareType)))
            except Exception:  # un componente ilegible no impide leer los demás
                log.debug("LHM: no se pudo leer %s", hw, exc_info=True)
                continue
        return salida

    def __exit__(self, *exc):
        try:
            if self._pc is not None:
                self._pc.Close()
        finally:
            self._pc = None
        return False


def leer_sensores() -> list[dict]:
    """Una lectura completa. Lanza RuntimeError con el motivo si la biblioteca no está disponible."""
    with MMAE_Lector() as l:
        return l.leer(actualizar=False)
