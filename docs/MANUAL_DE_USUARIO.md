# Manual de usuario — Sistema Inteligente Offline 1.0

## Contenido
1. [Introducción](#1-introducción)
2. [Requisitos](#2-requisitos)
3. [Instalación](#3-instalación)
4. [Primer inicio](#4-primer-inicio)
5. [La ventana principal](#5-la-ventana-principal)
6. [Atender un equipo paso a paso](#6-atender-un-equipo-paso-a-paso)
7. [Secciones del programa](#7-secciones-del-programa)
8. [Colector portátil en USB](#8-colector-portátil-en-usb)
9. [IA local (opcional)](#9-ia-local-opcional)
10. [Cuentas y seguridad](#10-cuentas-y-seguridad)
11. [Copias de seguridad](#11-copias-de-seguridad)
12. [Solución de problemas](#12-solución-de-problemas)
13. [Preguntas frecuentes](#13-preguntas-frecuentes)

---

## 1. Introducción

Sistema Inteligente Offline ayuda a los talleres de mantenimiento de computadoras a registrar los equipos
que reciben, leer su hardware, evaluar su estado, diagnosticar la falla, presupuestar, cobrar y entregar.
Funciona **sin Internet** y todos los datos quedan en la computadora del taller.

> El programa propone posibles causas y recomendaciones. **El técnico siempre valida el diagnóstico**
> con sus propias pruebas.

## 2. Requisitos

| | Windows | Linux |
|---|---|---|
| Sistema | Windows 10 (versión 1803 o posterior) o Windows 11, de 64 bits | 64 bits: Ubuntu 22.04 o posterior, Debian 12, Fedora, Linux Mint |
| Espacio | Unos 170 MB, más de 1 a 2,5 GB si instala la IA local | Igual |
| Internet | No es necesario (solo para descargar la IA local, una vez) | Igual |

## 3. Instalación

### Windows
1. Ejecute `SistemaDiagnostico-Setup-1.0.0.exe`.
2. Siga los pasos del asistente. Si quiere, marque la opción de crear un acceso directo en el escritorio.
3. Si Windows pide permiso para instalar el controlador de sensores **PawnIO**, acéptelo. Este
   controlador permite leer la temperatura del procesador. Si lo cancela, puede instalarlo más tarde desde
   **Escanear equipo → Instalar controlador**.

### Linux
1. Descomprima el paquete `.tar.gz`.
2. En una terminal, dentro de la carpeta descomprimida, ejecute `sh instalar.sh`. El programa se instala
   para su usuario y no necesita `sudo`.
3. Al final, el instalador ofrece instalar los paquetes recomendados (`smartmontools`, `dmidecode`,
   `pciutils`, `lm-sensors` y `libxcb-cursor0`); para eso sí pide la contraseña de `sudo`. Puede omitirlos
   y el programa funciona igual, con menos datos del hardware.
4. Abra «Sistema Inteligente Offline» desde el menú de aplicaciones o escriba `sistemadiagnostico`.

El paquete funciona en distribuciones con una versión de glibc igual o más nueva que la del equipo donde se
generó; el instalador lo comprueba y avisa si el equipo es demasiado antiguo.

Para desinstalar en Linux, ejecute `sh desinstalar.sh`. Sus datos se conservan.

## 4. Primer inicio

1. **Crear la cuenta inicial.** Escriba un ID de técnico (por ejemplo, `TEC-001`) y una contraseña de al
   menos 6 caracteres. Esta primera cuenta es la de **administrador**.
2. **Configuración inicial.** Escriba el nombre y los datos del taller. Estos datos aparecen en los
   reportes. Puede pulsar **Omitir** y completarlos después en **Configuración**.
3. A partir de entonces, cada técnico entra con su ID y su contraseña.

## 5. La ventana principal

A la izquierda está la barra con las 11 secciones:

| Sección | Para qué sirve |
|---|---|
| Inicio | Cola de trabajo: casos Recibidos, En diagnóstico y Listos |
| Recepción de equipo | Registrar el ingreso de un equipo |
| Escanear equipo | Leer el hardware de este PC o importar un escaneo desde USB |
| Salud del equipo | Estado de cada componente frente a fábrica y entre inspecciones |
| Equipos | Todos los equipos registrados y su último caso |
| Historial | Todos los casos, con búsqueda y filtros |
| Reportes | Generar y buscar los PDF |
| Base de conocimiento | Consultar las reglas de diagnóstico |
| IA local | Descargar y configurar la IA opcional |
| Configuración | Datos del taller, técnicos, contraseñas, copias, carpetas y auditoría |
| Acerca del sistema | Versión, limitaciones conocidas e información para soporte |

La **búsqueda global**, en la parte superior, busca por cliente, documento, equipo, serie
o teléfono.

## 6. Atender un equipo paso a paso

### Paso 1 — Recepción
1. Vaya a **Recepción de equipo** o pulse **+ Nueva recepción** en Inicio.
2. Complete **Cliente y equipo**: nombre y apellido, teléfono, DNI, RUC o CE, descripción del equipo
   (por ejemplo, «Laptop HP 15») y número de serie.
3. Escriba el **Problema reportado** en una línea. Es obligatorio.
4. En **Ingreso del equipo**, marque los accesorios que trae, el estado físico (por ejemplo, «rayones en la
   tapa») y las observaciones del cliente, y elija la fecha estimada de entrega.
5. Opcional: pulse **Escanear o importar datos** para adjuntar ahora el hardware del equipo.
6. Pulse **Guardar recepción**. Si está marcada la opción **Abrir la orden de servicio para imprimir al
   guardar**, se abre el PDF para imprimirlo y que el cliente lo firme.

Si el equipo ya estuvo en el taller, el programa lo avisa y ofrece **Ver caso anterior**.

### Paso 2 — Escaneo del hardware
- **Este equipo:** pulse **Iniciar escaneo**. Para leer todos los datos:
  - **Windows:** pulse **Reiniciar como administrador** cuando el programa lo sugiera.
  - **Linux:** pulse **Escanear con permisos**. El escritorio pide la contraseña de administrador una sola
    vez; con ella se leen el número de serie, el UUID, los módulos de RAM y el SMART de los discos. El
    programa no se reinicia ni queda abierto como administrador. Si cancela, se escanea sin esos datos.
- **Importar desde USB (.diag):** conecte la memoria USB, pulse **Actualizar**, elija el archivo y pulse
  **Importar seleccionado**. También puede usar **Buscar archivo…**.

Al terminar, la pantalla muestra las categorías leídas y **lo que no se pudo leer**. Las acciones
disponibles son:
- **Usar datos en la recepción**
- **Ver salud del equipo**
- **Ver inventario detallado**
- **Guardar archivo .diag en USB**

El programa reconoce el equipo por su UUID, número de serie o dirección MAC. Si la coincidencia no es
segura, le pide que la confirme.

### Paso 3 — Salud del equipo
1. En **Salud del equipo**, busque el caso.
2. Cada componente aparece con uno de estos estados:

   | Estado | Significado |
   |---|---|
   | Buen estado | Dentro de lo esperado frente a fábrica |
   | Revisar | Desgaste o valores para vigilar |
   | Atención | Requiere intervención |
   | Sin referencia | No hay datos de fábrica para comparar |

3. Pulse **Ver detalle** para ver **Qué significa** (explicado para el técnico y para el cliente),
   **Qué hacer** y cómo se calculó.
4. Pulse **Incluir en el diagnóstico** para llevar el hallazgo al diagnóstico, o **Agregar nota al caso**.
5. Opcional: pulse **Ejecutar prueba de rendimiento**. La prueba mide el procesador (unos 60 s) y cada disco
   (unos 30 s, solo lectura). En Linux, al iniciar la prueba se pide la contraseña de administrador para
   leer los discos. **Cierre los demás programas antes de iniciarla.** Se detiene sola si la
   temperatura llega a 95 °C. Si el equipo no informa la temperatura, el programa le pide confirmar que
   entiende que no habrá corte de seguridad.

### Paso 4 — Diagnóstico
1. Abra el caso (doble clic en Inicio o en Historial) y pulse **Ver o ejecutar diagnóstico**.
2. El sistema muestra las **posibles causas** con su prioridad y su confianza, la **evidencia usada por la
   regla** y las **recomendaciones sugeridas**.
3. Opcional: pulse **Analizar con IA local** para obtener una segunda opinión. Revise siempre su texto.
4. Pulse **Guardar diagnóstico**.

### Paso 5 — Presupuesto y cobro
1. En el caso, pulse **Abrir presupuesto y cobro**.
2. Agregue cada **servicio o repuesto** con su cantidad y su precio. Si corresponde, indique un descuento y
   las notas para el cliente (garantía, plazo, condiciones).
3. Imprima el **Presupuesto (PDF)**, pulse **Marcar como enviado** y, según responda el cliente, **Aprobado
   por el cliente** o **Rechazado por el cliente**.
4. En **Pagos**, registre los adelantos o el pago total (**Todo el saldo**). Puede anotar el número de
   operación. El programa no acepta pagos mayores que el saldo.
5. **Estado de cuenta (PDF)** muestra el presupuesto, los pagos y el saldo.

Solo un administrador puede reabrir un presupuesto aprobado o anular un pago, y la anulación exige
indicar un motivo.

### Paso 6 — Trabajo, notas y entrega
1. En el caso, agregue **notas** de tres tipos:
   - **Observación técnica:** interna, no sale en el informe para el cliente.
   - **Trabajo realizado:** sí aparece en el informe para el cliente.
   - **Nota para el cliente:** sí aparece en el informe para el cliente.
2. Cambie el **Estado** a medida que avanza (Recibido → En diagnóstico → Listo → Entregado) y pulse
   **Guardar estado**.
3. Genere el **Informe para el cliente (PDF)** y entréguelo con el equipo.
4. Al marcar el caso como **Entregado**, el programa avisa si queda un saldo pendiente.

## 7. Secciones del programa

### Equipos
Lista de todos los equipos con su último caso y su estado de salud. Desde aquí puede abrir **Ver último
caso**, la **Salud** del equipo o una **Nueva recepción** para el mismo equipo.

### Historial
Todos los casos, con búsqueda y filtros. Pulse **Limpiar filtros** para volver a ver la lista completa.

### Reportes
- **Generar reporte:** busque el caso y pulse **Generar reporte técnico** o **Generar informe para el cliente**.
- **Reportes generados:** búsqueda por cliente, código, serie, equipo o fecha. Puede usar **Abrir PDF
  seleccionado**, **Ver caso** o **Abrir carpeta de reportes**.

| Documento | Contenido |
|---|---|
| Reporte técnico | Datos completos del equipo, hardware, salud, diagnóstico y notas internas |
| Informe para el cliente | Problema, hallazgos y trabajo realizado, en lenguaje sencillo |
| Orden de servicio | Ingreso del equipo, accesorios, estado físico, condiciones y firmas |
| Presupuesto | Líneas, descuento, total y firma del cliente |
| Estado de cuenta | Presupuesto, pagos realizados y saldo |

### Base de conocimiento
Consulta de las reglas de diagnóstico. Puede buscar por causa, síntoma, palabra clave o recomendación.

### Configuración
- **Datos del taller** y condiciones de la orden de servicio (una por línea). Solo el administrador.
- **Técnicos:** crear técnicos, restablecer contraseñas, cambiar roles y desactivar cuentas. Solo el administrador.
- **Cambiar mi contraseña.**
- **Copias de seguridad** (ver el capítulo 11).
- **Carpetas:** abre las carpetas de datos, reportes y copias.
- **Referencias de fábrica:** **Crear copia editable del taller** permite ampliar la base de referencias.
- **Registro de auditoría:** accesos, cambios de cuentas, copias y operaciones de cobro. Solo el administrador.

### Acerca del sistema
Versión, datos del sistema, limitaciones conocidas y el botón **Copiar información (para soporte)**.
También permite volver a abrir el asistente de configuración inicial.

## 8. Colector portátil en USB

Sirve para escanear el PC de un cliente sin llevarlo al taller y sin instalar nada en él.

1. En **Escanear equipo**, pulse **Preparar USB colector…** y elija la memoria. Los escaneos anteriores
   de la memoria se conservan.
2. En el PC del cliente:
   - **Windows:** abra `Colector\Colector.exe` y acepte el permiso de administrador.
   - **Linux:** ejecute `sh colector.sh`, que le pedirá `sudo`.
3. El colector muestra un resumen de salud y ofrece la prueba de rendimiento opcional. El resultado se
   guarda en `Colector\Resultados` como archivo `.diag`.
4. En el taller, conecte la memoria e impórtela desde **Escanear equipo → Importar desde USB (.diag)**.

## 9. IA local (opcional)

El diagnóstico por reglas funciona sin IA. La IA local agrega estas funciones: análisis del caso, resumen
del historial del equipo, mensaje para el cliente y consultas de soporte.

1. Vaya a **IA local → Paquete de IA** y elija un modelo:
   - **Recomendado (Qwen3 4B):** mejores respuestas; necesita un equipo más potente.
   - **Ligero (Qwen2.5 1.5B):** para equipos modestos.
2. La descarga (de 1 a 2,5 GB) se hace **una sola vez** y se verifica automáticamente. Puede **pausarla**
   y continuarla después.
3. Marque **Activar IA local**, pulse **Guardar** y luego **Probar** para medir cuánto tarda en este equipo.
4. Para borrar la IA, use **Eliminar el paquete completo (motor y modelos)**.

La IA trabaja dentro del equipo y no envía datos a Internet. Sus respuestas pueden contener errores,
así que **siempre deben revisarse**. Los usuarios avanzados pueden usar Ollama en su lugar.

## 10. Cuentas y seguridad

- **Roles:**
  - **Administrador:** gestiona técnicos, datos del taller, copias y anulaciones.
  - **Técnico:** atiende casos.
- Siempre queda al menos un administrador activo.
- Tras 5 intentos fallidos de acceso, la cuenta se bloquea 30 segundos. El tiempo se duplica con cada
  nuevo fallo, hasta un máximo de 15 minutos.
- **Contraseña olvidada:** un administrador puede asignarle una nueva. Como el programa no usa Internet,
  no hay recuperación por correo.

## 11. Copias de seguridad

- **Automáticas:** al cerrar el programa se crea una copia como máximo cada 20 horas, y se conservan las
  10 más recientes. Se puede desactivar en Configuración.
- **Manuales:** en Configuración → Copias de seguridad. Se recomienda guardar una copia en una memoria
  USB o en otro disco.
- **Restaurar:** solo un administrador. Antes de restaurar, el programa guarda una copia de seguridad de
  los datos actuales.
- Ubicación de los datos:
  - Windows: `%APPDATA%\SistemaDiagnostico`
  - Linux: `~/.local/share/SistemaDiagnostico`

## 12. Solución de problemas

| Problema | Solución |
|---|---|
| No aparece la temperatura de la CPU | Instale el controlador desde **Escanear equipo → Instalar controlador** y use **Reiniciar como administrador** |
| No se lee la salud de los discos | En Windows, ejecute como administrador. En Linux, instale `smartmontools` y use **Escanear con permisos** |
| En Linux faltan la serie o los módulos de RAM | Instale `dmidecode` y use **Escanear con permisos** |
| En Linux no aparece «Escanear con permisos» | Instale `polkit` (el programa `pkexec`) |
| En Linux no aparece la temperatura de la CPU | Instale `lm-sensors` y ejecute una vez `sudo sensors-detect --auto` |
| El colector dice que el Linux es demasiado antiguo | Genere el programa con `build.sh` en una distribución más antigua (por ejemplo, Ubuntu 22.04) |
| La memoria gráfica aparece menor a la real | Es una limitación de WMI con tarjetas de 4 GB o más |
| Un componente aparece «Sin referencia» | Ese modelo no está en la base de referencias de fábrica. El taller puede ampliarla |
| La IA tarda mucho | Use el modelo ligero o cierre otros programas |
| «Archivo incompleto o dañado» al importar un `.diag` | Vuelva a generarlo con el colector y no retire la memoria USB mientras se guarda |
| Olvidé la contraseña del único administrador | Restaure una copia de seguridad en la que conozca la contraseña |

Si necesita soporte, use **Acerca del sistema → Copiar información (para soporte)** y envíe ese texto.

## 13. Preguntas frecuentes

**¿Necesito Internet?** No. Solo se usa para descargar, una vez, la IA local opcional.

**¿El programa repara el equipo?** No. Lee la información, propone causas y documenta el trabajo. Las
reparaciones las hace el técnico.

**¿Dónde quedan los datos de mis clientes?** Solo en la computadora del taller, en la carpeta de datos
indicada en el capítulo 11.

**¿Puedo usar el programa en varias computadoras?** Cada instalación tiene su propia base de datos. Para
mover los datos de una a otra, cree una copia de seguridad y restáurela en la otra computadora.
