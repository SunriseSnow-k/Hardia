# Historial de cambios

Todos los cambios importantes del programa se registran en este archivo.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y las versiones siguen
[Versionado Semántico](https://semver.org/lang/es/).

## Sin publicar

### Agregado
- README, memoria descriptiva, manual de usuario y este historial de cambios.
- Linux: botón **Escanear con permisos** en Escanear equipo. Pide la contraseña de administrador con
  pkexec una sola vez y lee el número de serie, el UUID, los módulos de RAM y el SMART de los discos sin
  abrir la interfaz como root. La prueba de rendimiento la pide al iniciar para medir los discos.
- Linux: el equipo local se reconoce sin root con un identificador derivado de `/etc/machine-id`, para
  permitir la prueba de rendimiento (solo para confirmar que la captura es de esta computadora).
- Linux: velocidad de giro de los discos y fabricante real (Seagate, Western Digital…) en lugar del bus
  («ATA»); la GPU aparece con su nombre comercial (p. ej., «Intel UHD Graphics 620»).
- Instalador de Linux: ofrece instalar los paquetes recomendados (apt, dnf, zypper o pacman), comprueba la
  glibc y que el programa arranque antes de reemplazar la versión anterior, e instala el ícono en el tema.
- Colector de Linux: avisa con claridad si el PC del cliente tiene una glibc más antigua que la necesaria.

- Una misma memoria USB puede llevar el colector de Windows y el de Linux: cada programa reemplaza solo el
  suyo (el de Linux va en `Colector/linux`) y los escaneos de `Colector/Resultados` se conservan.

### Corregido
- Linux: las memorias USB conectadas pero sin montar no se reconocían para preparar el colector ni para
  importar escaneos. Ahora se montan solas con udisksctl (sin contraseña).
- Preparar el colector de Linux borraba el colector de Windows que ya tenía la memoria.
- Linux: la copia de la base de referencias del taller se buscaba en `%APPDATA%` y no en
  `~/.local/share/SistemaDiagnostico`.
- Linux: el instalador y el desinstalador no detectaban el programa abierto (el nombre del proceso se corta
  a 15 caracteres) y podían borrarlo en uso.
- Linux: `build.sh` y `calidad.sh` usan el entorno virtual activo; el programa de Linux se genera en
  `dist/linux` sin pisar el de Windows, sin símbolos de depuración (paquete de 111 a 83 MB, colector de
  53 a 21 MB) y se prueba antes de empaquetarlo.

## 1.0.0 - 2026-10-17

Primera versión completa. Se desarrolló por fases entre el 2026-10-10 y el 2026-10-17.

### Agregado

**Base del sistema (fases 1 a 3, 2026-10-10)**
- Inicio de sesión, ventana principal y barra lateral de secciones.
- Base de datos SQLite local con usuarios reales y contraseñas cifradas con PBKDF2-SHA256.
- Pantallas de Inicio (cola de trabajo), Recepción de equipo, Historial y búsqueda global.

**Hardware y diagnóstico (fases 4 a 9, 2026-10-10 y 2026-10-11)**
- Escaneo de hardware del equipo y archivo `.diag` para llevar el escaneo en una memoria USB.
- Motor de diagnóstico por reglas con evidencia de síntomas y mediciones.
- IA local con cancelación segura (hilo lector y cola).
- Reportes en PDF: reporte técnico e informe para el cliente; pantalla Reportes.
- Copias de seguridad automáticas con rotación.
- Validación del motor, pruebas de robustez e interfaz y plan de pruebas.

**Hardware ampliado y salud (fases 10 y 11, 2026-10-12 a 2026-10-14)**
- Inventario de hardware ampliado, capturas guardadas por equipo e identificación fiable del equipo.
- Búsqueda por cliente, documento, serie y código.
- Pantalla Salud del equipo: comparación con referencias de fábrica y evolución entre inspecciones.

**Sensores, IA opcional e instalador (fases 12 y 13, 2026-10-15)**
- Sensores de CPU, almacenamiento, refrigeración y gráficos con LibreHardwareMonitorLib.
- Paquete de IA opcional: motor llama.cpp y modelo GGUF descargados una vez y verificados con SHA-256.
- Empaquetado con PyInstaller e instalador de Windows con Inno Setup.

**Orden de servicio (fase 14, 2026-10-15)**
- Ingreso del equipo: accesorios, estado físico, observaciones, entrega estimada y quién recibió.
- PDF «Orden de servicio» con condiciones editables y espacio para firmas.

**Calidad (pasos 1 a 5, 2026-10-15)**
- Transacciones atómicas anidables y migraciones de esquema versionadas, con copia previa a cada migración.
- Roles de administrador y técnico, cuentas desactivables, bloqueo progresivo tras intentos fallidos
  (5 fallos → 30 s, duplicando hasta 15 min) y registro de auditoría.
- Controles automáticos: ruff, mypy, cobertura mínima del 80 % e integración continua.
- Separación por capas (sin SQL en la interfaz) y división de los módulos grandes.
- Colores centralizados en una paleta con nombres semánticos.

**Presupuesto y cobro (fase 17, 2026-10-16)**
- Presupuestos con líneas de servicio y repuesto, descuento y estados Borrador, Enviado, Aprobado y Rechazado.
- Pagos y adelantos sin superar el saldo; anulación con motivo (solo administrador); auditoría.
- PDF de presupuesto con firma del cliente y estado de cuenta; símbolo de moneda configurable (S/ por defecto).
- Aviso de saldo pendiente al marcar un caso como Entregado.

**Colector portátil en USB (fase 18, 2026-10-16)**
- `Colector.exe`: escanea el PC del cliente sin instalar nada y guarda el `.diag` en `Colector\Resultados`.
- Resumen de salud y prueba de rendimiento opcional en el colector.
- Botón «Preparar USB colector» en Escanear.

**Soporte para Linux (fase 19, 2026-10-17)**
- Colectores de hardware para Linux (sysfs, /proc, hwmon, dmidecode, smartctl, lspci, nvidia-smi).
- Datos en `~/.local/share/SistemaDiagnostico`; motor de IA para Linux x64 y ARM64.
- Colector USB `colector.sh`, instalador `linux/instalar.sh` e integración continua en Ubuntu 22.04.

**Instalador con todo incluido (fase 20, 2026-10-17)**
- El instalador trae el controlador de sensores PawnIO 2.2.0 y lo instala en silencio si falta.
- Botón «Instalar controlador» en Escanear.
- Requisito mínimo Windows 10 versión 1803 para no instalar .NET por separado.

### Corregido
- Regla R-006 y liberación de recursos COM al leer WMI (fase 5).
- Rotación de copias: sello de tiempo estrictamente creciente y sin borrar la copia nueva (fase 8).
- Descargas limitadas a HTTPS, causa original conservada al relanzar excepciones y fallos de sensores
  registrados en el log (calidad paso 3).

### Problemas conocidos
- El soporte para Linux se probó en un entorno simulado; falta verificarlo en equipos reales.
- La interfaz (`app/ui`) todavía no pasa por la verificación de tipos de mypy.

