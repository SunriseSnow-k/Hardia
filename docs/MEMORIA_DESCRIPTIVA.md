# Memoria descriptiva del programa de ordenador

## 1. Datos de la obra

| Campo | Dato |
|---|---|
| Título | Hardia |
| Versión | 1.1.0 |
| Tipo de obra | Programa de ordenador (software) |
| Fecha de inicio del desarrollo | 10 de octubre de 2026 |
| Fecha de conclusión de la versión 1.1.0 | 22 de octubre de 2026 |
| País de creación | Perú |
| Lenguaje de programación | Python 3.13 |
| Plataformas | Windows 10 (1803 o posterior) y Windows 11 de 64 bits; Linux de 64 bits |
| Tamaño del código propio | 91 archivos de código Python (unas 16 100 líneas), más 34 archivos de pruebas automáticas (unas 5 800 líneas) y 2 bases de conocimiento en JSON |
| Forma de distribución | Instalador de Windows (`SistemaDiagnostico-Setup-1.1.0.exe`) y paquete `.tar.gz` para Linux |

## 2. Objeto y finalidad

El programa asiste a los talleres de mantenimiento de computadoras en todo el ciclo de atención de un
equipo: la recepción del equipo del cliente, la lectura de su hardware, la evaluación de su estado, el
diagnóstico de la falla, el presupuesto, el cobro y la entrega.

Su característica principal es que **funciona sin conexión a Internet**. Todos los datos se guardan en
el equipo del taller y el diagnóstico lo produce un motor de reglas propio. Como apoyo opcional, una IA
local se ejecuta en el mismo equipo, sin enviar datos a servicios externos.

El programa propone posibles causas, prioridades y recomendaciones. La validación final siempre la
realiza el técnico.

## 3. Descripción funcional

### 3.1 Acceso y cuentas
- Al primer inicio se crea una cuenta de administrador y se registran los datos del taller.
- Hay dos roles: **administrador** y **técnico**. Solo el administrador crea técnicos, restablece contraseñas,
  cambia roles, desactiva cuentas, edita los datos del taller y restaura copias de seguridad.
- El acceso se bloquea de forma progresiva tras cinco intentos fallidos: 30 segundos al principio,
  duplicando el tiempo hasta un máximo de 15 minutos.
- Las contraseñas se guardan cifradas con PBKDF2-HMAC-SHA256 (200 000 iteraciones y sal aleatoria).
- Un registro de auditoría guarda los accesos, los cambios de cuentas, las copias y las operaciones de cobro.

### 3.2 Recepción y casos
- La recepción registra al cliente (nombre, teléfono y DNI, RUC o CE), el equipo (descripción y serie), el
  problema reportado, los accesorios, el estado físico, las observaciones y la fecha estimada de entrega.
- Cada recepción crea un **caso** con un código único y estos estados: Recibido → En diagnóstico → Listo → Entregado.
- Se puede imprimir una **orden de servicio** con las condiciones del taller y espacio para firmas.
- Cada caso guarda notas de tres tipos: observación técnica (interna), trabajo realizado y nota para el cliente.

### 3.3 Escaneo del hardware
- Lee la identidad del equipo, el procesador, la memoria, el almacenamiento, los gráficos, la placa base, el
  sistema operativo, la red, la batería y los sensores de temperatura y ventiladores.
- En Windows usa WMI y LibreHardwareMonitorLib. En Linux usa sysfs, /proc, hwmon, dmidecode, smartctl,
  lspci y nvidia-smi. Ambos colectores entregan los datos con el mismo formato.
- **Identificación del equipo**: compara identificadores fuertes (UUID y número de serie) y débiles
  (direcciones MAC) con los equipos ya registrados. El resultado es encontrado, ambiguo, probable o nuevo,
  y así se evita duplicar equipos o mezclar sus historiales.
- **Archivo `.diag`**: formato propio en JSON (identificador `SD-DIAG`, versión 2) que permite llevar un
  escaneo en una memoria USB e importarlo después en el taller.
- **Colector portátil**: un segundo ejecutable (`Colector.exe` en Windows; en Linux, `Colector-Linux.com`,
  que se abre con doble clic, o `colector.sh`) que se ejecuta desde la memoria USB en el PC del cliente sin
  instalar nada. Escanea el equipo, muestra un resumen de salud y guarda el `.diag`. Cada instalador trae
  los colectores de los dos sistemas, así que una misma memoria sirve para PCs con Windows o con Linux.

### 3.4 Salud del equipo
- Evalúa cada componente (batería, memoria, discos, refrigeración, procesador) y le asigna uno de estos
  estados: «Buen estado», «Revisar», «Atención» o «Sin referencia».
- Compara las mediciones con una base local de referencias de fábrica (`app/health/references.json`) que
  el taller puede ampliar.
- Muestra la evolución del equipo entre inspecciones y una explicación para el técnico y otra para el cliente.
- **Prueba de rendimiento** opcional: carga el procesador unos 60 segundos y lee cada disco unos 30 segundos,
  solo en modo lectura. La prueba se detiene sola si la temperatura llega a 95 °C.

### 3.5 Diagnóstico por reglas
- Una base de conocimiento propia (`app/diagnosis/rules.json`) contiene 20 reglas. Cada regla tiene una
  categoría, una prioridad, una causa probable, síntomas con palabras clave, condiciones sobre mediciones
  del hardware y recomendaciones.
- El motor normaliza el texto del problema (minúsculas y sin acentos) y busca las palabras clave al inicio
  de cada palabra. Así, por ejemplo, «ram» no coincide con «programas».
- Calcula una confianza para cada regla: los síntomas encontrados más las condiciones cumplidas (con un
  peso de 1,5), divididos entre lo que la regla podía evaluar. Muestra hasta cinco causas ordenadas por
  prioridad y confianza, junto con la evidencia que usó cada regla.
- El técnico puede añadir al diagnóstico los hallazgos de la evaluación de salud.

### 3.6 IA local (opcional)
- Se descarga una sola vez desde la sección IA local: el motor llama.cpp y un modelo de lenguaje
  (Qwen3 4B o Qwen2.5 1.5B). Cada archivo se verifica con su huella SHA-256.
- Sirve para analizar un caso, resumir el historial de un equipo, redactar un mensaje para el cliente y
  responder consultas de soporte. Todo se ejecuta en el equipo del taller.
- Como alternativa avanzada se puede usar Ollama.

### 3.7 Presupuesto y cobro
- Presupuestos con líneas de servicio y de repuesto, cantidades, descuento y notas para el cliente.
- Estados del presupuesto: Borrador, Enviado, Aprobado y Rechazado. Solo un administrador puede reabrir un
  presupuesto aprobado.
- Pagos y adelantos que no pueden superar el saldo. Solo un administrador puede anular un pago, y debe
  indicar el motivo. Los importes se guardan en céntimos para evitar errores de redondeo.

### 3.8 Reportes
El programa genera cinco documentos PDF: reporte técnico, informe para el cliente, orden de servicio,
presupuesto y estado de cuenta. Todos quedan registrados y se pueden buscar por cliente, caso, serie o fecha.

### 3.9 Datos y copias de seguridad
- La base de datos SQLite está en la carpeta de datos del usuario.
- El esquema cambia mediante migraciones numeradas, y antes de migrar una base con datos se hace una copia.
- Las operaciones con varias escrituras se ejecutan en una sola transacción: se guardan completas o no se
  guarda nada.
- Al cerrar el programa se crea una copia de seguridad automática, como máximo una cada 20 horas, y se conservan las 10 más recientes. La opción se puede desactivar.
  También se pueden crear copias manuales, validarlas y restaurarlas.

## 4. Arquitectura

El programa está organizado en capas. La interfaz no accede directamente a la base de datos.

```
┌────────────────────────────────────────────────────────────┐
│ Interfaz (app/ui) — PySide6: páginas, diálogos y paleta    │
├────────────────────────────────────────────────────────────┤
│ Servicios (app/servicios) — recepción, cuentas, cobro      │
├──────────────┬──────────────┬──────────────┬───────────────┤
│ Diagnóstico  │ Salud        │ IA local     │ Reportes PDF  │
│ app/diagnosis│ app/health   │ app/ai       │ app/reports   │
├──────────────┴──────────────┴──────────────┴───────────────┤
│ Hardware (app/hardware) — Windows (WMI, LHM) y Linux       │
├────────────────────────────────────────────────────────────┤
│ Datos (app/db) — repositorios, migraciones, seguridad      │
│ SQLite local · copias de seguridad (app/backup.py)         │
└────────────────────────────────────────────────────────────┘
```

| Módulo | Responsabilidad |
|---|---|
| `main.py` | Punto de entrada: registro de eventos, base de datos, inicio de sesión y ventana principal |
| `app/ui` | Ventana principal con 11 secciones, diálogos de caso, diagnóstico, salud, cobro y rendimiento |
| `app/servicios` | Reglas de negocio de la recepción, las cuentas y el cobro |
| `app/db` | Un repositorio por entidad, migraciones versionadas, transacciones y cifrado de contraseñas |
| `app/hardware` | Colectores por componente, sensores, inventario, archivo `.diag`, colector USB |
| `app/health` | Evaluación de salud, referencias de fábrica y prueba de rendimiento |
| `app/diagnosis` | Motor de reglas y base de reglas |
| `app/ai` | Descarga y verificación del paquete de IA, clientes de llama.cpp y Ollama, indicaciones |
| `app/reports` | Construcción de los cinco documentos PDF |
| `app/plataforma.py`, `app/paths.py` | Diferencias entre Windows y Linux, y carpetas de datos |

### 4.1 Modelo de datos
La base tiene 19 tablas: `users`, `clients`, `equipment`, `equipment_identifiers`, `cases`, `case_scans`,
`case_notes`, `diagnoses`, `hardware_captures`, `health_results`, `health_diag_items`, `health_benchmarks`,
`reports`, `service_orders`, `quotes`, `quote_items`, `payments`, `settings` y `audit_log`.

## 5. Elementos originales de la obra

Estos elementos son de creación propia:
1. El diseño funcional del flujo del taller: recepción, escaneo, salud, diagnóstico, presupuesto, cobro y entrega.
2. El motor de diagnóstico por reglas, su cálculo de confianza y la base de 20 reglas.
3. El método de evaluación de salud por componente, sus umbrales y los textos para el técnico y el cliente.
4. La prueba de rendimiento con corte de seguridad por temperatura y su unidad de puntaje propia.
5. El método de identificación de equipos con identificadores fuertes y débiles.
6. El formato de archivo `.diag` y el colector portátil en USB.
7. El esquema de la base de datos y sus migraciones.
8. El diseño de la interfaz gráfica y de los documentos PDF.
9. Las indicaciones (prompts) de la IA local y su integración con el resto del sistema.

## 6. Componentes de terceros (no forman parte de la obra registrada)

El programa usa estos componentes, cada uno con su propia licencia. **No se reclama ningún derecho sobre ellos.**

| Componente | Licencia | Uso |
|---|---|---|
| Python | PSF | Lenguaje e intérprete |
| Qt for Python (PySide6) | LGPL-3.0 | Interfaz gráfica |
| ReportLab | BSD | Generación de PDF |
| psutil | BSD-3-Clause | Información del sistema |
| WMI, pywin32 | MIT, PSF | Consultas a Windows |
| pythonnet | MIT | Puente con .NET |
| LibreHardwareMonitorLib y dependencias | MPL-2.0 | Sensores en Windows (`app/vendor/lhm`) |
| PawnIO 2.2.0 | GPL-2.0 | Controlador de sensores, instalado como programa independiente y sin modificar |
| Runtime de Microsoft Visual C++ | Licencia de Microsoft | Ejecución |
| llama.cpp, LLVM OpenMP | MIT, Apache-2.0 | Motor de IA opcional (se descarga aparte) |
| Modelos Qwen3 4B y Qwen2.5 1.5B | Apache-2.0 | Modelos de IA opcionales (se descargan aparte) |
| PyInstaller, Inno Setup | GPL con excepción, licencia de Inno Setup | Herramientas de empaquetado; no se distribuyen como parte de la obra |

## 7. Requisitos de funcionamiento

| Requisito | Windows | Linux |
|---|---|---|
| Sistema | Windows 10 versión 1803 o posterior, Windows 11 (64 bits) | Distribución de 64 bits con glibc de Ubuntu 22.04 o posterior |
| Permisos | Usuario normal; administrador solo para leer algunos sensores y discos | Usuario normal; `sudo` para el número de serie, los módulos de RAM y el SMART |
| Espacio | Unos 170 MB para el programa; de 1 a 2,5 GB adicionales si se instala la IA local | Igual |
| Internet | No se necesita. Solo se usa para descargar, una vez, el paquete de IA opcional | Igual |

## 8. Aseguramiento de la calidad

- 417 pruebas automáticas con pytest. Cubren la base de datos, las migraciones, las transacciones, las
  cuentas, el motor de reglas, la salud, el cobro, el colector, Linux y la interfaz.
- Cobertura de código mínima del 80 %, exigida por la herramienta.
- Análisis estático con ruff (estilo, errores probables y reglas de seguridad) y verificación de tipos con mypy.
- Integración continua en Windows y en Ubuntu 22.04 en cada cambio.
- El empaquetado (`build.ps1` en Windows, `build.sh` en Linux) solo genera el instalador si antes pasan
  todos los controles.

## 9. Ejemplar de la obra

El ejemplar que acompaña esta memoria contiene el código fuente propio:
- `main.py`
- Todos los archivos `.py` de la carpeta `app`, excepto `app/vendor`
- Las herramientas de la carpeta `tools` (generación del ícono y empaquetado de los colectores)
- Las bases de conocimiento `app/diagnosis/rules.json` y `app/health/references.json`

Quedan excluidas las bibliotecas de terceros: las carpetas `app/vendor`, `redist` y `.venv`, y los
archivos generados en `build` y `dist`.
