# Hardia

Hardia es un sistema de diagnóstico asistido para talleres de mantenimiento de computadoras. Funciona **sin conexión a
Internet**: registra la recepción de equipos, lee el hardware, evalúa la salud de cada componente, propone
posibles causas con un motor de reglas propio y, de forma opcional, con una IA local. Genera los documentos
del taller en PDF (reporte técnico, informe para el cliente, orden de servicio, presupuesto y estado de cuenta).

La validación final del diagnóstico siempre la realiza el técnico.

- Versión actual: **1.0.0** (ver [CHANGELOG.md](CHANGELOG.md))
- Sistemas: Windows 10 (1803 o posterior) y Windows 11 de 64 bits; Linux de 64 bits (Ubuntu 22.04 o posterior)
- Documentación:
  - [Manual de usuario](docs/MANUAL_DE_USUARIO.md)
  - [Memoria descriptiva](docs/MEMORIA_DESCRIPTIVA.md)
  - [Componentes de terceros](app/assets/LICENCIAS_TERCEROS.txt)

## Funciones principales

| Área | Qué hace |
|---|---|
| Recepción | Registra cliente, equipo, problema reportado, accesorios y estado físico; genera la orden de servicio |
| Escaneo | Lee CPU, memoria, discos, gráficos, placa, sistema, red, batería y sensores del equipo, o importa un escaneo `.diag` desde USB |
| Colector USB | `Colector.exe` (Windows) o `colector.sh` (Linux) escanean el PC del cliente sin instalar nada |
| Salud | Compara cada componente con referencias de fábrica y con inspecciones anteriores; prueba de rendimiento opcional con corte por temperatura |
| Diagnóstico | Motor de reglas (`app/diagnosis/rules.json`) que combina síntomas y mediciones y muestra la evidencia usada |
| IA local | Opcional: llama.cpp con un modelo Qwen descargado una sola vez y verificado con SHA-256 (u Ollama) |
| Presupuesto y cobro | Líneas de servicio y repuesto, descuentos, aprobación del cliente, pagos y anulaciones auditadas |
| Reportes | PDF técnico, informe para el cliente, orden de servicio, presupuesto y estado de cuenta |
| Seguridad | Roles administrador y técnico, bloqueo progresivo del acceso, registro de auditoría, contraseñas con PBKDF2 |
| Datos | SQLite local con migraciones versionadas y copias de seguridad automáticas y manuales |

## Estructura del código

```
main.py                 Punto de entrada de la aplicación de escritorio
app/
  ui/                   Interfaz (PySide6): ventana principal, páginas y diálogos
  servicios/            Reglas de negocio: recepción, cuentas, cobro
  db/                   Acceso a datos (repositorios), migraciones y seguridad
  hardware/             Lectura del hardware (WMI, LibreHardwareMonitor, Linux), archivo .diag y colector
  health/               Evaluación de salud, referencias de fábrica y prueba de rendimiento
  diagnosis/            Motor de reglas y base de reglas
  ai/                   IA local: paquete descargable, clientes llama.cpp y Ollama, indicaciones
  reports/              Generación de PDF (ReportLab)
  backup.py, paths.py   Copias de seguridad y carpetas de datos
  vendor/lhm/           LibreHardwareMonitorLib (terceros, MPL-2.0)
tests/                  Pruebas automáticas (pytest)
linux/                  Instalador y desinstalador para Linux
build.ps1 / build.sh    Empaquetado (pruebas → PyInstaller → instalador)
calidad.ps1 / calidad.sh  Controles de calidad (ruff, mypy, pytest con cobertura)
installer.iss           Instalador de Windows (Inno Setup)
diagnostico.spec        Configuración de PyInstaller (programa y colector)
```

## Desarrollo

Requisitos: Python 3.13.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python main.py
```

En Linux: `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/python main.py`.
Si la carpeta del proyecto está en una partición NTFS compartida con Windows, cree el entorno fuera de ella
(por ejemplo `~/venvs/diagnostico`) y actívelo: `calidad.sh` y `build.sh` usan el entorno virtual activo
(o el indicado en la variable `PY`).

### Controles de calidad

```powershell
.\calidad.ps1      # Windows
./calidad.sh       # Linux
```

Ejecutan `ruff check`, `mypy` y `pytest` con una cobertura mínima del 80 %. La integración continua
(`.github/workflows/calidad.yml`) los corre en Windows y en Ubuntu 22.04 en cada push.

### Empaquetado

```powershell
.\build.ps1        # Windows: genera dist\SistemaDiagnostico-Setup-<versión>.exe con Inno Setup
./build.sh         # Linux: genera dist/instalador/SistemaDiagnostico-<versión>-linux-x86_64.tar.gz
```

### Los dos colectores en cada instalador

Cada instalador incluye los colectores de Windows y Linux, para preparar desde cualquiera de los dos
sistemas una memoria USB que sirva en cualquier PC del cliente. PyInstaller no compila para otro sistema, así que
cada colector se genera en su sistema y se lleva al otro como `dist/colectores/Colector-<sistema>.tar.gz`
(ver `tools/colectores.py`):

- **Automático:** en GitHub, Actions → **Paquetes** → *Run workflow* (o publicar una etiqueta `v*`). Genera
  los dos colectores y luego los dos instaladores con ambos dentro, como artefactos de la ejecución.
- **A mano:** en cada sistema ejecute `.\build.ps1 -SoloColector` o `./build.sh --solo-colector`, copie los
  `.tar.gz` de `dist/colectores` a la misma carpeta del otro equipo y genere los instaladores. Si falta
  el colector del otro sistema, el build avisa y el instalador se genera sin él.

## Datos del programa

| Sistema | Carpeta |
|---|---|
| Windows | `%APPDATA%\SistemaDiagnostico` |
| Linux | `~/.local/share/SistemaDiagnostico` |

Contiene la base `diagnostico.db` y las carpetas `Reportes`, `Copias` e `IA`.

## Componentes de terceros

El programa usa componentes de terceros, cada uno con su propia licencia (PySide6, ReportLab, psutil,
LibreHardwareMonitorLib, PawnIO, llama.cpp, modelos Qwen, entre otros). La lista completa está en
[app/assets/LICENCIAS_TERCEROS.txt](app/assets/LICENCIAS_TERCEROS.txt).
