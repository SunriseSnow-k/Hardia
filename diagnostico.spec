# -*- mode: python ; coding: utf-8 -*-
# Empaquetado con PyInstaller (carpeta, no un solo .exe: arranca más rápido y los antivirus
# lo marcan menos). Uso: .\build.ps1 en Windows, ./build.sh en Linux
# (o: python -m PyInstaller --noconfirm diagnostico.spec). PyInstaller no compila de un sistema a
# otro: el programa para Linux se genera en Linux y el de Windows en Windows.
# Genera dos programas: dist/SistemaDiagnostico (el del taller) y dist/Colector (el colector
# portátil que se lleva en el USB al PC del cliente; el script de build lo copia dentro del primero).
import re
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"
if WINDOWS:
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct,
                                                     StringTable, VarFileInfo, VarStruct, VSVersionInfo)

RAIZ = Path(SPECPATH)
_version_py = (RAIZ / "app" / "version.py").read_text(encoding="utf-8")
APP_NAME = re.search(r'APP_NAME\s*=\s*"([^"]+)"', _version_py).group(1)
VERSION = re.search(r'VERSION\s*=\s*"([^"]+)"', _version_py).group(1)
NUMEROS = tuple(int(n) for n in (VERSION.split(".") + ["0", "0", "0"])[:4])
# LibreHardwareMonitor (.NET) y pywin32 solo se usan en Windows
LHM = [("app/vendor/lhm", "app/vendor/lhm")] if WINDOWS else []
ICONO = str(RAIZ / "app" / "assets" / ("icono.ico" if WINDOWS else "icono.png"))


def _version_info(interno: str, descripcion: str):
    """Datos de versión del .exe (solo Windows; en Linux no existen)."""
    if not WINDOWS:
        return None
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=NUMEROS, prodvers=NUMEROS),
        kids=[
            StringFileInfo([StringTable("0C0A04B0", [
                StringStruct("CompanyName", APP_NAME),
                StringStruct("FileDescription", descripcion),
                StringStruct("FileVersion", VERSION),
                StringStruct("InternalName", interno),
                StringStruct("OriginalFilename", f"{interno}.exe"),
                StringStruct("ProductName", APP_NAME),
                StringStruct("ProductVersion", VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0C0A, 1200])]),
        ],
    )


a = Analysis(
    ["main.py"],
    pathex=[str(RAIZ)],
    datas=[
        ("app/diagnosis/rules.json", "app/diagnosis"),
        ("app/health/references.json", "app/health"),
        *LHM,
        ("app/assets", "app/assets"),
    ],
    hiddenimports=["win32timezone", "win32job"] if WINDOWS else [],
    excludes=["tkinter", "pytest", "PyInstaller", "setuptools",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
              "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SistemaDiagnostico",
    icon=ICONO,
    version=_version_info("SistemaDiagnostico", APP_NAME),
    console=False,
    upx=False,
    uac_admin=False,  # se pide administrador solo al escanear sensores (botón en Escanear)
)
coll = COLLECT(exe, a.binaries, a.datas, name="SistemaDiagnostico", upx=False)

# ---------------- Colector portátil (USB) ----------------
# Solo escaneo por consola: sin Qt, PDF ni base de datos, para que pese poco en la memoria USB.
c = Analysis(
    [str(RAIZ / "app" / "hardware" / "cli.py")],
    pathex=[str(RAIZ)],
    datas=[*LHM, ("app/health/references.json", "app/health")],
    hiddenimports=["win32timezone"] if WINDOWS else [],
    excludes=["tkinter", "pytest", "PyInstaller", "setuptools", "PySide6", "shiboken6", "reportlab",
              "PIL", "numpy", "sqlite3", "app.ui", "app.db", "app.reports", "app.ai"],
    noarchive=False,
)
colector = EXE(
    PYZ(c.pure),
    c.scripts,
    [],
    exclude_binaries=True,
    name="Colector",
    icon=ICONO,
    version=_version_info("Colector", f"{APP_NAME} - Colector portátil"),
    console=True,
    upx=False,
    uac_admin=True,  # Windows: temperaturas, ventiladores y SMART solo se leen como administrador
)
COLLECT(colector, c.binaries, c.datas, name="Colector", upx=False)
