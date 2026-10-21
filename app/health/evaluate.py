"""Salud del equipo frente a sus valores de fábrica (módulo puro, sin Qt).

Solo usa datos reales de la captura (inventory/metrics) y, si existe, de la prueba de
rendimiento. Lo que no tiene referencia o medición queda como "Sin referencia" con su motivo:
nunca se completa con valores supuestos. El índice general es orientativo: es el promedio
simple de los porcentajes que sí se pudieron calcular.
"""
from statistics import mean

from app.hardware.inventory import ESTADO_TEXTO, NO_COMPATIBLE, fmt_bytes, fuente_salud

from .references import find_cpu, find_cpu_score, find_disk_type

VERSION = 1
BUENO, REVISAR, ATENCION, SIN_REF = "Buen estado", "Revisar", "Atención", "Sin referencia"
ESTADOS = (BUENO, REVISAR, ATENCION, SIN_REF)
GRAVEDAD = {ATENCION: 0, REVISAR: 1, BUENO: 2, SIN_REF: 3}
UMBRAL_BUENO, UMBRAL_REVISAR = 80.0, 60.0      # % respecto a fábrica
MARGEN_BUENO, MARGEN_REVISAR = 20.0, 10.0      # °C hasta el límite del procesador
GPU_REVISAR, GPU_ATENCION = 83.0, 90.0         # °C del núcleo de la GPU (umbral orientativo del taller)
DISCO_T_REVISAR, DISCO_T_ATENCION = 55.0, 65.0  # °C de la unidad (umbral orientativo del taller)
FAN_PARADO_RPM, TEMP_FAN_PARADO = 200.0, 75.0  # ventiladores casi detenidos con la CPU caliente
SIN_MEDICION = "Sin medición: requiere la prueba de rendimiento"
FUENTE_LHM = "LibreHardwareMonitor"

QUE_SIGNIFICA = {
    "bateria": {
        BUENO: ("La capacidad máxima actual está cerca de la de diseño.",
                "La batería conserva buena parte de su capacidad original."),
        REVISAR: ("Desgaste apreciable: la autonomía es menor que la original.",
                  "La batería dura menos que cuando era nueva."),
        ATENCION: ("Desgaste alto: autonomía reducida; conviene evaluar el reemplazo.",
                   "La batería perdió buena parte de su capacidad; probablemente necesite cambiarse."),
    },
    "memoria": {
        BUENO: ("La memoria funciona a su velocidad nominal o cerca de ella.",
                "La memoria trabaja a la velocidad esperada."),
        REVISAR: ("La memoria trabaja por debajo de su velocidad nominal. Puede ser un límite del "
                  "procesador o de la placa, o un ajuste del BIOS.",
                  "La memoria funciona algo más lenta de lo que permite."),
        ATENCION: ("La memoria trabaja muy por debajo de su velocidad nominal. Revise el BIOS, la "
                   "combinación de módulos y lo que admite el procesador.",
                   "La memoria funciona bastante más lenta de lo que permite."),
    },
    "disco": {
        BUENO: ("El sistema no informa problemas en la unidad y, si se midió, la lectura es la esperada.",
                "La unidad de almacenamiento no muestra problemas."),
        REVISAR: ("La lectura medida es menor que la típica para este tipo de unidad.",
                  "La unidad de almacenamiento es más lenta de lo normal."),
        ATENCION: ("El sistema informa la unidad con advertencias o la lectura es muy baja. Respalde los "
                   "datos y revise la unidad.",
                   "La unidad donde se guardan sus archivos muestra señales de desgaste; conviene "
                   "respaldar su información."),
    },
    "refrigeracion": {
        BUENO: ("Hay margen suficiente hasta el límite térmico del procesador.",
                "El equipo no se está calentando de más."),
        REVISAR: ("El margen térmico es reducido: revise ventiladores, polvo y pasta térmica.",
                  "El equipo se calienta más de lo ideal."),
        ATENCION: ("El procesador trabaja cerca de su límite térmico: limpieza y pasta térmica "
                   "prioritarias.",
                   "El equipo se calienta demasiado; puede volverse lento o apagarse."),
    },
    "graficos": {
        BUENO: ("La temperatura de la GPU está dentro de lo habitual.",
                "La tarjeta de video no se está calentando de más."),
        REVISAR: ("La GPU trabaja caliente: revise ventiladores, polvo y flujo de aire.",
                  "La tarjeta de video se calienta más de lo ideal."),
        ATENCION: ("La GPU está muy caliente: limpieza, pasta y almohadillas térmicas prioritarias.",
                   "La tarjeta de video se calienta demasiado; puede fallar o cerrar juegos y programas."),
    },
    "procesador": {
        BUENO: ("El puntaje medido está cerca de la referencia del taller para este modelo.",
                "El procesador rinde como se espera."),
        REVISAR: ("El puntaje es menor que la referencia: revise temperatura, plan de energía y "
                  "programas en segundo plano.",
                  "El procesador rinde menos de lo esperado."),
        ATENCION: ("El puntaje es muy inferior a la referencia: posible limitación térmica o de energía.",
                   "El procesador rinde bastante menos de lo esperado."),
    },
}
QUE_HACER = {
    "bateria": "Comparar la autonomía real con la esperada; si el desgaste es alto, cotizar una batería nueva.",
    "memoria": "Revisar el perfil de memoria en el BIOS y que los módulos sean compatibles y del mismo tipo.",
    "disco": "Respaldar la información y repetir la medición; si el sistema informa advertencias, planificar el reemplazo.",
    "refrigeracion": "Limpiar ventiladores y disipador, renovar la pasta térmica y volver a medir bajo carga.",
    "procesador": "Repetir la prueba con el cargador conectado y sin programas abiertos; revisar la temperatura.",
    "graficos": "Limpiar el disipador y los ventiladores de la GPU y volver a medir bajo carga.",
}


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v) -> list:
    return v if isinstance(v, list) else []


def _miles(n) -> str:
    return f"{int(round(n)):,}".replace(",", " ")


def estado_por_pct(pct: float | None) -> str:
    if pct is None:
        return SIN_REF
    if pct >= UMBRAL_BUENO:
        return BUENO
    if pct >= UMBRAL_REVISAR:
        return REVISAR
    return ATENCION


def estado_por_margen(margen: float | None) -> str:
    if margen is None:
        return SIN_REF
    if margen >= MARGEN_BUENO:
        return BUENO
    if margen >= MARGEN_REVISAR:
        return REVISAR
    return ATENCION


def peor(*estados: str) -> str:
    validos = [e for e in estados if e and e != SIN_REF]
    return min(validos, key=lambda e: GRAVEDAD.get(e, 0)) if validos else SIN_REF


def _comp(clave, nombre, modelo="", estado=SIN_REF, medido=("No disponible", ""),
          fabrica=("Sin referencia", ""), pct=None, alt="", fuente="", calculo="",
          medido_num=None, fabrica_num=None, unidad="", windows=(), resumen="", tipo=None) -> dict:
    tipo = tipo or clave.split(":")[0]
    tecnico, cliente = QUE_SIGNIFICA.get(tipo, {}).get(estado, ("", ""))
    return {
        "clave": clave, "tipo": tipo, "nombre": nombre, "modelo": modelo or "", "estado": estado,
        "medido": {"valor": medido[0], "nota": medido[1]},
        "fabrica": {"valor": fabrica[0], "nota": fabrica[1]},
        "pct": None if pct is None else round(float(pct), 1),
        "alt": alt, "fuente": fuente, "calculo": calculo,
        "medido_num": medido_num, "fabrica_num": fabrica_num, "unidad": unidad,
        "windows": [list(x) for x in windows], "resumen": resumen,
        "tecnico": tecnico or ("Sin datos suficientes para comparar con fábrica." if estado == SIN_REF else ""),
        "cliente": cliente,
        "que_hacer": QUE_HACER.get(tipo, ""),
    }


# ---------------- componentes ----------------
def _es_linux(inv) -> bool:
    """Captura hecha en Linux (sus datos vienen de /sys, dmidecode y smartctl, no de WMI)."""
    return bool(_d(inv.get("os")).get("kernel"))


def _sistema(inv) -> str:
    return "Linux" if _es_linux(inv) else "Windows"


def _bateria(inv, disp) -> dict | None:
    a = _d(disp.get("battery"))
    if a.get("status") == NO_COMPATIBLE or ("battery" not in inv and not a):
        return None  # equipo sin batería: no aplica
    b = _d(inv.get("battery"))
    windows = []
    if b.get("percent") is not None:
        windows.append(("Carga actual", f'{b["percent"]:.0f} %'))
    if b.get("plugged") is not None:
        windows.append(("Conectada a corriente", "Sí" if b["plugged"] else "No"))
    windows.append(("Ciclos de carga", "No disponible: esta versión no los lee"))
    fuente = ("Linux (/sys/class/power_supply: capacidad de diseño y máxima actual)" if _es_linux(inv)
              else "Windows (BatteryStaticData y BatteryFullChargedCapacity)")
    if not b:
        motivo = ESTADO_TEXTO.get(str(a.get("status")), "No disponible")
        return _comp("bateria", "Batería", alt=f"Sin referencia: {motivo.lower()}", fuente=fuente,
                     windows=windows)
    diseno, actual = b.get("design_mwh"), b.get("full_mwh")
    if not (diseno and actual):
        motivo = next((ESTADO_TEXTO.get(str(f.get("motivo")), "No disponible") for f in _l(a.get("faltantes"))
                       if isinstance(f, dict) and "batería" in str(f.get("campo", "")).lower()),
                      "No disponible")
        return _comp("bateria", "Batería", alt=f"Sin referencia: {_sistema(inv)} no informó la capacidad ({motivo.lower()})",
                     fuente=fuente, windows=windows)
    pct = 100 * actual / diseno
    estado = estado_por_pct(pct)
    return _comp(
        "bateria", "Batería", estado=estado,
        medido=(f"{_miles(actual)} mWh", "capacidad máxima actual"),
        fabrica=(f"{_miles(diseno)} mWh", "capacidad de diseño"),
        pct=pct, fuente=fuente, medido_num=actual, fabrica_num=diseno, unidad="mWh",
        calculo=f"{_miles(actual)} mWh ÷ {_miles(diseno)} mWh = {pct:.0f} %",
        windows=windows + ([("Desgaste estimado", f'{b["wear_pct"]:.1f} %')] if b.get("wear_pct") is not None else []),
        resumen=f"La batería conserva el {pct:.0f} % de su capacidad de fábrica.")


def _memoria(inv) -> dict | None:
    mem = _d(inv.get("memory"))
    if not mem:
        return None
    modulos = [m for m in _l(mem.get("modules")) if isinstance(m, dict)]
    tipos = sorted({m["type"] for m in modulos if m.get("type")})
    modelo = " ".join(p for p in (f'{mem["total_gb"]:g} GB' if mem.get("total_gb") else "", " / ".join(tipos)) if p)
    windows = [(f'Módulo {i}', " · ".join(str(p) for p in (
        f'{m["capacity_gb"]:g} GB' if m.get("capacity_gb") else None, m.get("type"),
        f'nominal {m["nominal_mhz"]} MHz' if m.get("nominal_mhz") else None,
        f'configurada {m["configured_mhz"]} MHz' if m.get("configured_mhz") else None,
        m.get("slot")) if p)) for i, m in enumerate(modulos, 1)]
    fuente = ("dmidecode (Speed y Configured Memory Speed)" if _es_linux(inv)
              else "Windows (Win32_PhysicalMemory: Speed y ConfiguredClockSpeed)")
    pares = [(m["configured_mhz"], m["nominal_mhz"]) for m in modulos
             if m.get("configured_mhz") and m.get("nominal_mhz")]
    if not pares:
        motivo = ("la captura no incluye la velocidad nominal y la configurada de los módulos"
                  if modulos else f"{_sistema(inv)} no informó los módulos de memoria")
        leidas = sorted({int(m.get("configured_mhz") or m.get("speed_mhz") or 0) for m in modulos
                         if m.get("configured_mhz") or m.get("speed_mhz")})
        medido = ((" / ".join(f"{v} MHz" for v in leidas), "velocidad leída") if leidas
                  else ("No disponible", ""))
        return _comp("memoria", "Memoria RAM", modelo, medido=medido, alt=f"Sin referencia: {motivo}",
                     fuente=fuente, windows=windows)
    conf, nominal = min(pares, key=lambda p: p[0] / p[1])
    pct = 100 * conf / nominal
    return _comp(
        "memoria", "Memoria RAM", modelo, estado_por_pct(pct),
        medido=(f"{conf} MHz", "velocidad configurada"), fabrica=(f"{nominal} MHz", "velocidad nominal del módulo"),
        pct=pct, fuente=fuente, medido_num=conf, fabrica_num=nominal, unidad="MHz",
        calculo=f"{conf} MHz ÷ {nominal} MHz = {pct:.0f} %", windows=windows,
        resumen=f"La memoria funciona al {pct:.0f} % de su velocidad nominal ({conf} de {nominal} MHz).")


def _estado_salud_disco(salud) -> str:
    if not salud:
        return SIN_REF
    return BUENO if salud == "Saludable" else ATENCION  # "Advertencia" o peor


def _discos(inv, references, benchmark) -> list[dict]:
    sto = _d(inv.get("storage"))
    medidas = {str(x.get("index")): x for x in _l(_d(benchmark).get("discos")) if isinstance(x, dict)}
    salida = []
    fisicos = [u for u in _l(sto.get("physical")) if isinstance(u, dict) and not u.get("external")]
    linux = _es_linux(inv)
    origen_salud = "SMART (smartctl)" if linux else "Windows Storage"
    lector = "hwmon / smartctl" if linux else "LibreHardwareMonitor"
    permisos = "escanear con permisos de administrador" if linux else "ejecutar como administrador"
    for n, u in enumerate(fisicos, 1):
        salud = u.get("health")
        e_salud = _estado_salud_disco(salud)
        modelo = " · ".join(p for p in (u.get("model"), u.get("media"),
                                         fmt_bytes(u["size_bytes"]) if u.get("size_bytes") else None) if p)
        windows = [("Salud", f'{salud} ({fuente_salud(u.get("health_source"))})' if salud else
                    f"No disponible: {origen_salud} no la informó"),
                   ("Tipo", u.get("media") or "No disponible"), ("Conexión", u.get("bus") or "No disponible")]
        if u.get("rpm"):
            windows.append(("Velocidad de giro", f'{u["rpm"]} rpm'))
        t_disco, vida = u.get("temp_c"), u.get("life_pct")
        windows.append(("Temperatura del disco", f"{t_disco:.0f} °C ({lector})" if t_disco is not None
                        else f"No disponible: requiere {permisos}"))
        windows.append(("Vida útil restante", f"{vida:.0f} % (SMART, {lector})" if vida is not None
                        else f"No disponible: la unidad no la informa o falta {permisos}"))
        if u.get("written_gb"):
            windows.append(("Datos escritos", f'{u["written_gb"]:,.0f} GB'.replace(",", " ")))
        e_temp = (ATENCION if t_disco is not None and t_disco >= DISCO_T_ATENCION else
                  REVISAR if t_disco is not None and t_disco >= DISCO_T_REVISAR else None)
        if e_temp:
            e_salud = peor(e_salud, e_temp) if e_salud != SIN_REF else e_temp
        ref = find_disk_type(references, u)
        med = medidas.get(str(u.get("index")))
        mb_s = med.get("lectura_mb_s") if med else None
        fabrica = ((f'{ref["lectura_mb_s"]:.0f} MB/s', f'típico de {ref["tipo"]}') if ref
                   else ("Sin referencia", "no hay valor de fábrica para este tipo de unidad"))
        fuente = ("SMART (smartctl)" if linux else "Windows Storage (MSFT_PhysicalDisk)") + (
            f" · SMART: {lector}" if vida is not None and not linux else "") + (
            f' · lectura medida por este programa · referencia: {ref["fuente"]}' if mb_s and ref else
            " · lectura medida por este programa" if mb_s else "")
        nombre = "Almacenamiento" if len(fisicos) == 1 else f"Almacenamiento {n}"
        texto_salud = f"{origen_salud} informa la unidad {u.get('model') or ''} en estado «{salud}»." if salud else ""
        if vida is not None:
            texto_salud = (texto_salud + " " if texto_salud else "") + f"Le queda el {vida:.0f} % de su vida útil."
        if mb_s and ref:
            pct = 100 * mb_s / ref["lectura_mb_s"]
            estado = peor(e_salud, estado_por_pct(pct), *([estado_por_pct(vida)] if vida is not None else []))
            resumen = (texto_salud + " " if e_salud == ATENCION else "") + \
                f"La lectura medida es el {pct:.0f} % de la típica ({mb_s:.0f} de {ref['lectura_mb_s']:.0f} MB/s)."
            salida.append(_comp(
                f"disco:{u.get('index')}", nombre, modelo, estado,
                medido=(f"{mb_s:.0f} MB/s", "lectura secuencial medida"), fabrica=fabrica, pct=pct,
                fuente=fuente, medido_num=mb_s, fabrica_num=ref["lectura_mb_s"], unidad="MB/s",
                calculo=f"{mb_s:.0f} MB/s ÷ {ref['lectura_mb_s']:.0f} MB/s = {pct:.0f} %",
                windows=windows, resumen=resumen.strip(), tipo="disco"))
            continue
        if vida is not None and not mb_s:
            # La vida útil SMART se compara con la de una unidad nueva (100 %)
            estado = peor(e_salud, estado_por_pct(vida)) if e_salud != SIN_REF else estado_por_pct(vida)
            salida.append(_comp(
                f"disco:{u.get('index')}", nombre, modelo, estado,
                medido=(f"{vida:.0f} %", "vida útil restante (SMART)"), fabrica=("100 %", "unidad nueva"),
                pct=vida, alt=SIN_MEDICION, fuente=fuente, medido_num=vida, fabrica_num=100.0, unidad="%",
                calculo=f"{vida:.0f} % ÷ 100 % = {vida:.0f} %", windows=windows, resumen=texto_salud,
                tipo="disco"))
            continue
        if mb_s:
            alt = "Sin referencia para este tipo de unidad"
            medido = (f"{mb_s:.0f} MB/s", "lectura secuencial medida")
        else:
            motivo = med.get("motivo") if med else None
            alt = f"Sin medición: {motivo}" if motivo else SIN_MEDICION
            medido = (salud or "No disponible", f"salud según {origen_salud}")
        salida.append(_comp(f"disco:{u.get('index')}", nombre, modelo, e_salud, medido=medido, fabrica=fabrica,
                            alt=alt, fuente=fuente, windows=windows, resumen=texto_salud, tipo="disco"))
    return salida


def _cpu_nombre(inv, scan) -> str:
    return _d(inv.get("cpu")).get("name") or _d(_d(scan).get("summary")).get("cpu") or ""


def _refrigeracion(inv, scan, references, benchmark) -> dict:
    cpu = _cpu_nombre(inv, scan)
    bcpu = _d(_d(benchmark).get("cpu"))
    if bcpu.get("temp_max") is not None:
        temp, fuente_t, cuando = bcpu["temp_max"], bcpu.get("temp_fuente"), "máxima durante la prueba de carga"
    else:
        temp = _d(_d(scan).get("metrics")).get("cpu_temp")
        fuente_t, cuando = _d(inv.get("sensors")).get("cpu_temp_source"), "al momento de la captura"
    aprox = bool(fuente_t) and fuente_t != FUENTE_LHM
    sen = _d(inv.get("sensors"))
    windows = [("Fuente de la temperatura", (fuente_t or "No disponible") + (" (aproximada)" if aprox else ""))]
    for f in _l(sen.get("fans")):
        if isinstance(f, dict) and f.get("rpm") is not None:
            windows.append((f'Ventilador: {f.get("name", "?")}', f'{f["rpm"]:.0f} rpm'))
    if bcpu.get("detenido_por_temp"):
        windows.append(("Prueba de carga", "Detenida por seguridad al llegar al corte de temperatura"))
    ref = find_cpu(references, cpu) if cpu else None
    fabrica = ((f'{ref["tjmax_c"]:.0f} °C', "límite térmico del procesador (Tjmax)") if ref
               else ("Sin referencia", "procesador no incluido en la base"))
    fuente = "Sensores: " + (fuente_t or "no disponibles") + (f' · Tjmax: {ref["fuente"]}' if ref else "")
    if temp is None:
        return _comp("refrigeracion", "Refrigeración", cpu, fabrica=fabrica,
                     alt="Sin lectura de temperatura (requiere LibreHardwareMonitor o permisos)",
                     fuente=fuente, windows=windows)
    medido = (f"{float(temp):.0f} °C", cuando + (" · aproximada" if aprox else ""))
    if not ref:
        return _comp("refrigeracion", "Refrigeración", cpu, medido=medido, fabrica=fabrica,
                     alt="Sin límite de fábrica para este procesador en la base", fuente=fuente, windows=windows)
    margen = ref["tjmax_c"] - float(temp)
    estado = ATENCION if bcpu.get("detenido_por_temp") else estado_por_margen(margen)
    if _ventiladores_parados(sen) and float(temp) > TEMP_FAN_PARADO:
        estado = peor(estado, REVISAR)
        windows.append(("Ventiladores", f"Ninguno supera {FAN_PARADO_RPM:.0f} rpm con la CPU a {float(temp):.0f} °C"))
    return _comp(
        "refrigeracion", "Refrigeración", cpu, estado, medido=medido, fabrica=fabrica,
        alt=f"Margen de {margen:.0f} °C", fuente=fuente, medido_num=float(temp), fabrica_num=ref["tjmax_c"],
        unidad="°C", calculo=f"{ref['tjmax_c']:.0f} °C − {float(temp):.0f} °C = {margen:.0f} °C de margen",
        windows=windows,
        resumen=f"Margen térmico de {margen:.0f} °C hasta el límite del procesador ({ref['tjmax_c']:.0f} °C)"
                + (", con temperatura aproximada." if aprox else "."))


def _ventiladores_parados(sen) -> bool:
    rpm = [f["rpm"] for f in _l(sen.get("fans"))
           if isinstance(f, dict) and f.get("rpm") is not None and f.get("hw") != "gpu"]
    return bool(rpm) and max(rpm) < FAN_PARADO_RPM


def _procesador(inv, scan, references, benchmark) -> dict:
    cpu = _cpu_nombre(inv, scan)
    c = _d(inv.get("cpu"))
    windows = []
    if c.get("cores"):
        windows.append(("Núcleos / hilos", f'{c["cores"]} / {c.get("threads") or "?"}'))
    if c.get("max_mhz"):
        windows.append(("Frecuencia máxima declarada", f'{c["max_mhz"] / 1000:.2f} GHz'))
    ref = find_cpu_score(references, cpu) if cpu else None
    fabrica = ((f'{_miles(ref["ops_s"])} op/s', "referencia medida por el taller") if ref
               else ("Sin referencia", "no hay puntaje de fábrica en esta unidad"))
    bcpu = _d(_d(benchmark).get("cpu"))
    ops = bcpu.get("ops_s")
    fuente = "Prueba de CPU de este programa" if ops else "—"
    if not ops:
        return _comp("procesador", "Procesador", cpu, medido=("No medido", ""), fabrica=fabrica,
                     alt=SIN_MEDICION, fuente=fuente, windows=windows)
    sost = bcpu.get("sostenido_pct")
    nota = f"rendimiento sostenido {sost:.0f} % del inicial" if sost is not None else "operaciones por segundo"
    windows.append(("Duración de la prueba", f'{bcpu.get("duracion_s", 0):.0f} s'))
    if not ref:
        return _comp("procesador", "Procesador", cpu, medido=(f"{_miles(ops)} op/s", nota), fabrica=fabrica,
                     alt="Sin referencia: no hay puntaje de fábrica para este modelo", fuente=fuente,
                     medido_num=ops, unidad="op/s", windows=windows)
    pct = 100 * ops / ref["ops_s"]
    return _comp("procesador", "Procesador", cpu, estado_por_pct(pct), medido=(f"{_miles(ops)} op/s", nota),
                 fabrica=fabrica, pct=pct, fuente=f'{fuente} · referencia: {ref.get("fuente", "taller")}',
                 medido_num=ops, fabrica_num=ref["ops_s"], unidad="op/s",
                 calculo=f"{_miles(ops)} ÷ {_miles(ref['ops_s'])} op/s = {pct:.0f} %", windows=windows,
                 resumen=f"El procesador rinde el {pct:.0f} % de la referencia del taller.")


def _graficos(inv) -> dict | None:
    adaptadores = [a for a in _l(_d(inv.get("graphics")).get("adapters")) if isinstance(a, dict) and a.get("name")]
    if not adaptadores:
        return None
    modelo = " · ".join(a["name"] for a in adaptadores)
    windows = []
    for a in adaptadores:
        pre = f'{a["name"]}: ' if len(adaptadores) > 1 else ""
        for campo, etiqueta, fmt in (("temp_c", "Temperatura", "{:.0f} °C"),
                                     ("hotspot_c", "Punto más caliente", "{:.0f} °C"),
                                     ("load_pct", "Uso al capturar", "{:.0f} %"), ("fan_rpm", "Ventilador", "{:.0f} rpm")):
            if a.get(campo) is not None:
                windows.append((pre + etiqueta, fmt.format(a[campo])))
        if a.get("mem_used_mb") is not None and a.get("mem_total_mb"):
            windows.append((pre + "Memoria gráfica en uso", f'{a["mem_used_mb"]:.0f} de {a["mem_total_mb"]:.0f} MB'))
    con_temp = [a for a in adaptadores if a.get("temp_c") is not None]
    if not con_temp:
        return _comp("graficos", "Gráficos", modelo, medido=("No medido", ""), windows=windows,
                     alt="Sin lectura de temperatura de la GPU",
                     fuente="LibreHardwareMonitor" if windows else "—")
    caliente = max(con_temp, key=lambda a: a["temp_c"])
    temp = float(caliente["temp_c"])
    estado = ATENCION if temp >= GPU_ATENCION else REVISAR if temp >= GPU_REVISAR else BUENO
    return _comp("graficos", "Gráficos", modelo, estado, medido=(f"{temp:.0f} °C", "temperatura al capturar"),
                 fabrica=(f"< {GPU_REVISAR:.0f} °C", "umbral orientativo del taller"),
                 alt=f"{caliente['name']} a {temp:.0f} °C", fuente="Sensores: LibreHardwareMonitor",
                 medido_num=temp, unidad="°C", windows=windows,
                 resumen=f"La GPU {caliente['name']} está a {temp:.0f} °C." if estado != BUENO else "")


# ---------------- evaluación ----------------
def evaluate(scan: dict | None, references: dict, benchmark: dict | None = None) -> dict:
    scan = _d(scan)
    inv = scan.get("inventory")
    base = {"version": VERSION, "captura": str(scan.get("scanned_at") or ""),
            "con_prueba": bool(benchmark), "benchmark_fecha": _d(benchmark).get("fecha")}
    if not isinstance(inv, dict):
        return {**base, "componentes": [], "indice": {"valor": None, "estado": SIN_REF, "incluidos": []},
                "conteo": {e: 0 for e in ESTADOS}, "hallazgo": None,
                "aviso": ("La captura es de una versión anterior y no incluye el inventario detallado: "
                          "escanee el equipo de nuevo para evaluar su salud." if scan else
                          "El caso no tiene captura de hardware.")}
    disp = _d(scan.get("availability"))
    comps = [c for c in (
        _procesador(inv, scan, references, benchmark),
        _memoria(inv),
        *_discos(inv, references, benchmark),
        _bateria(inv, disp),
        _refrigeracion(inv, scan, references, benchmark),
        _graficos(inv),
    ) if c]
    con_pct = [c for c in comps if c["pct"] is not None]
    valor = round(mean(c["pct"] for c in con_pct), 1) if con_pct else None
    conteo = {e: sum(1 for c in comps if c["estado"] == e) for e in ESTADOS}
    malos = sorted((c for c in comps if c["estado"] in (ATENCION, REVISAR)),
                   key=lambda c: (GRAVEDAD[c["estado"]], c["pct"] if c["pct"] is not None else 999))
    hallazgo = ({"clave": malos[0]["clave"], "estado": malos[0]["estado"],
                 "texto": malos[0]["resumen"] or f'{malos[0]["nombre"]}: {malos[0]["estado"].lower()}.'}
                if malos else None)
    return {**base, "componentes": comps,
            "indice": {"valor": valor, "estado": estado_por_pct(valor),
                       "incluidos": [c["nombre"] for c in con_pct]},
            "conteo": conteo, "hallazgo": hallazgo, "aviso": ""}


def componente(resultado: dict, clave: str) -> dict | None:
    return next((c for c in _l(_d(resultado).get("componentes")) if c.get("clave") == clave), None)
