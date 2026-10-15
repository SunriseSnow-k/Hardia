"""Inventario de hardware: estados, filas legibles, identificadores y comparación.

Módulo puro (sin WMI ni Qt): lo usan el escáner, la interfaz y los reportes.
"""
import re

OK, NO_DISPONIBLE, NO_COMPATIBLE, NO_AUTORIZADO, FALLO = (
    "ok", "no_disponible", "no_compatible", "no_autorizado", "fallo")
ESTADO_TEXTO = {
    OK: "Detectado",
    NO_DISPONIBLE: "No disponible",
    NO_COMPATIBLE: "No aplica en este equipo",
    NO_AUTORIZADO: "Sin permisos",
    FALLO: "Falló la detección",
}
CATEGORIAS = [
    ("identity", "Identificación"), ("cpu", "Procesador"), ("memory", "Memoria RAM"),
    ("storage", "Almacenamiento"), ("graphics", "Gráficos"), ("motherboard", "Placa base y BIOS"),
    ("os", "Sistema operativo"), ("network", "Red"), ("battery", "Batería"),
    ("other", "Monitor y audio"), ("sensors", "Temperaturas y ventiladores"),
]
FUERTES = ("uuid", "serial", "board_serial")  # identificadores que bastan para reconocer un equipo


def _d(valor) -> dict:
    return valor if isinstance(valor, dict) else {}


def _l(valor) -> list:
    return valor if isinstance(valor, list) else []


def fmt_bytes(n) -> str:
    """Capacidad comercial (decimal): 512 GB, 1.5 TB."""
    gb = float(n) / 1e9
    if gb >= 950:
        return f"{round(gb / 1000, 1):g} TB"
    return f"{round(gb):d} GB"


def _fila(categoria, etiqueta, valor, estado=OK) -> dict:
    return {"category": categoria, "label": etiqueta, "value": str(valor), "status": estado}


def _campos(titulo, datos, spec) -> list:
    filas = []
    for clave, etiqueta, fmt in spec:
        v = datos.get(clave)
        if v in (None, "", [], {}):
            continue
        filas.append(_fila(titulo, etiqueta, fmt(v) if fmt else v))
    return filas


def _si_no(v):
    return "Sí" if v else "No"


def _f_identity(t, d):
    return _campos(t, d, [("hostname", "Nombre del equipo", None), ("manufacturer", "Fabricante", None),
                          ("model", "Modelo", None), ("serial", "N.º de serie", None),
                          ("uuid", "UUID del sistema", None), ("architecture", "Arquitectura", None)])


def _f_cpu(t, d):
    return _campos(t, d, [("manufacturer", "Fabricante", None), ("name", "Modelo", None),
                          ("architecture", "Arquitectura", None), ("cores", "Núcleos físicos", None),
                          ("threads", "Hilos lógicos", None),
                          ("max_mhz", "Frecuencia máxima declarada", lambda v: f"{v / 1000:.2f} GHz"),
                          ("usage_pct", "Uso al capturar", lambda v: f"{v:.0f} %"),
                          ("temp_c", "Temperatura al capturar", lambda v: f"{v:.0f} °C"),
                          ("temp_max_core_c", "Núcleo más caliente", lambda v: f"{v:.0f} °C"),
                          ("clock_mhz", "Frecuencia media al capturar", lambda v: f"{v / 1000:.2f} GHz"),
                          ("power_w", "Consumo del procesador", lambda v: f"{v:.0f} W")])


def _velocidad_ram(m: dict):
    """'3200 MHz' o, si la velocidad configurada difiere de la nominal, '3200 MHz (configurada 2666 MHz)'."""
    nominal, conf = m.get("nominal_mhz"), m.get("configured_mhz")
    if nominal and conf and nominal != conf:
        return f"{nominal} MHz (configurada {conf} MHz)"
    v = m.get("speed_mhz") or conf or nominal
    return f"{v} MHz" if v else None


def _f_memory(t, d):
    filas = _campos(t, d, [("total_gb", "Capacidad total", lambda v: f"{v:g} GB"),
                           ("available_gb", "Disponible al capturar", lambda v: f"{v:g} GB"),
                           ("used_pct", "Uso al capturar", lambda v: f"{v:.0f} %")])
    for i, m in enumerate(_l(d.get("modules")), 1):
        partes = [f'{m.get("capacity_gb"):g} GB' if m.get("capacity_gb") else None, m.get("type"),
                  _velocidad_ram(m), m.get("form_factor"),
                  m.get("manufacturer"), m.get("part_number"),
                  f'ranura {m.get("slot")}' if m.get("slot") else None]
        filas.append(_fila(t, f"Módulo {i}", " · ".join(p for p in partes if p)))
    return filas


def fuente_salud(fuente) -> str:
    """Texto breve de la fuente de la salud del disco (no hay lectura SMART propia)."""
    f = str(fuente or "").strip()
    if not f:
        return "según el sistema"
    if "windows storage" in f.lower():
        return "según Windows Storage"
    return f"según {f}"


def _f_storage(t, d):
    filas = []
    for i, u in enumerate(_l(d.get("physical")), 1):
        salud = (f'Salud: {u["health"]} ({fuente_salud(u.get("health_source"))})'
                 if u.get("health") else "Salud: sin fuente fiable")
        partes = [u.get("model"), u.get("media"), fmt_bytes(u["size_bytes"]) if u.get("size_bytes") else None,
                  f'{u["rpm"]} rpm' if u.get("rpm") else None,
                  u.get("bus"), "externa" if u.get("external") else None, u.get("manufacturer"), salud,
                  f'{u["temp_c"]:.0f} °C' if u.get("temp_c") is not None else None,
                  f'vida útil restante {u["life_pct"]:.0f} %' if u.get("life_pct") is not None else None,
                  f'{u["written_gb"]:,.0f} GB escritos'.replace(",", " ") if u.get("written_gb") else None]
        filas.append(_fila(t, f"Unidad física {i}", " · ".join(p for p in partes if p)))
    for v in _l(d.get("logical")):
        if v.get("size_bytes"):
            texto = (f'{v.get("filesystem") or "s/d"} · {fmt_bytes(v["size_bytes"])} · '
                     f'usado {fmt_bytes(v["used_bytes"])} ({v["used_pct"]:.0f} %) · '
                     f'libre {fmt_bytes(v["free_bytes"])}')
            filas.append(_fila(t, f'Volumen {v.get("drive", "?")}', texto))
    return filas


def _f_graphics(t, d):
    filas = []
    for i, g in enumerate(_l(d.get("adapters")), 1):
        vram = f'memoria gráfica {g["vram_gb"]:g} GB' if g.get("vram_gb") else "memoria gráfica no informada"
        partes = [g.get("name"), g.get("manufacturer"), vram,
                  f'controlador {g["driver_version"]}' if g.get("driver_version") else None,
                  f'{g["temp_c"]:.0f} °C' if g.get("temp_c") is not None else None,
                  f'punto más caliente {g["hotspot_c"]:.0f} °C' if g.get("hotspot_c") is not None else None,
                  f'uso {g["load_pct"]:.0f} %' if g.get("load_pct") is not None else None,
                  f'ventilador {g["fan_rpm"]:.0f} RPM' if g.get("fan_rpm") is not None else None]
        filas.append(_fila(t, f"Adaptador {i}", " · ".join(p for p in partes if p)))
    return filas


def _f_motherboard(t, d):
    return _campos(t, d, [("manufacturer", "Fabricante", None), ("model", "Modelo", None),
                          ("serial", "N.º de serie", None), ("version", "Versión de la placa", None),
                          ("bios_vendor", "Fabricante del BIOS", None),
                          ("bios_version", "Versión del BIOS", None), ("bios_date", "Fecha del BIOS", None)])


def _f_os(t, d):
    return _campos(t, d, [("name", "Sistema", None), ("version", "Versión", None),
                          ("build", "Compilación", None), ("architecture", "Arquitectura", None)])


def _f_network(t, d):
    filas = []
    for i, a in enumerate(_l(d.get("adapters")), 1):
        tipo = a.get("type") or "No determinado"
        if a.get("type_inferred"):
            tipo += " (inferido)"
        ips = ", ".join(a.get("ipv4") or []) or "sin IP"
        partes = [a.get("name"), tipo, "conectado" if a.get("connected") else "desconectado",
                  f"IP: {ips}", f'MAC {a["mac"]}' if a.get("mac") else None]
        filas.append(_fila(t, f"Adaptador {i}", " · ".join(p for p in partes if p)))
    return filas


def _f_battery(t, d):
    return _campos(t, d, [("percent", "Carga actual", lambda v: f"{v:.0f} %"),
                          ("plugged", "Conectada a corriente", _si_no),
                          ("design_mwh", "Capacidad de diseño", lambda v: f"{v:,} mWh".replace(",", " ")),
                          ("full_mwh", "Capacidad máxima actual", lambda v: f"{v:,} mWh".replace(",", " ")),
                          ("wear_pct", "Desgaste estimado", lambda v: f"{v:.1f} %")])


def _f_other(t, d):
    filas = []
    for i, m in enumerate(_l(d.get("monitors")), 1):
        partes = [m.get("name"), m.get("manufacturer"),
                  f'fabricado en {m["year"]}' if m.get("year") else None]
        filas.append(_fila(t, f"Monitor {i}", " · ".join(p for p in partes if p) or "sin nombre"))
    for i, a in enumerate(_l(d.get("audio")), 1):
        filas.append(_fila(t, f"Audio {i}", " · ".join(p for p in (a.get("name"), a.get("manufacturer")) if p)))
    return filas


_PIEZA = {"cpu": "CPU", "gpu": "GPU", "storage": "Disco", "motherboard": "Placa", "cooler": "Refrigeración",
          "memory": "RAM"}


def _sensor(s: dict) -> str:
    """'GPU · GPU Core' o solo el nombre si no se sabe de qué pieza es."""
    pieza = _PIEZA.get(str(s.get("hw")))
    nombre = s.get("name", "?")
    return f"{pieza} · {nombre}" if pieza and not nombre.lower().startswith(pieza.lower()) else nombre


def _f_sensors(t, d):
    filas = []
    for s in _l(d.get("temperatures")):
        filas.append(_fila(t, f'Temperatura: {_sensor(s)}',
                           f'{s["value"]:.0f} °C (fuente: {s.get("source", "s/d")})'))
    for s in _l(d.get("fans")):
        filas.append(_fila(t, f'Ventilador: {_sensor(s)}', f'{s["rpm"]:.0f} RPM'))
    return filas


_FORMATOS = {"identity": _f_identity, "cpu": _f_cpu, "memory": _f_memory, "storage": _f_storage,
             "graphics": _f_graphics, "motherboard": _f_motherboard, "os": _f_os,
             "network": _f_network, "battery": _f_battery, "other": _f_other, "sensors": _f_sensors}


def _filas_heredadas(scan) -> list:
    """Escaneos antiguos (versión 1): solo existe la lista de componentes."""
    estado = {"ok": OK, "warn": NO_DISPONIBLE, "error": FALLO}
    return [_fila(c.get("name", "?"), "Detalle", c.get("detail", ""),
                  estado.get(str(c.get("status")), NO_DISPONIBLE))
            for c in _l(_d(scan).get("components")) if isinstance(c, dict)]


def inventory_rows(scan: dict) -> list[dict]:
    """Filas planas {category, label, value, status} de todo el inventario, incluidas
    las categorías que no se pudieron detectar y los datos faltantes con su motivo."""
    inv = _d(scan).get("inventory")
    if not isinstance(inv, dict):
        return _filas_heredadas(scan)
    disp = _d(scan.get("availability"))
    filas = []
    for clave, titulo in CATEGORIAS:
        a = _d(disp.get(clave))
        estado = a.get("status", OK if inv.get(clave) else NO_DISPONIBLE)
        datos = _d(inv.get(clave))
        if estado != OK:
            filas.append(_fila(titulo, "Estado de la detección",
                               a.get("detail") or ESTADO_TEXTO.get(estado, estado), estado))
            continue
        filas += _FORMATOS[clave](titulo, datos)
        for f in _l(a.get("faltantes")):
            motivo = f.get("motivo", NO_DISPONIBLE)
            filas.append(_fila(titulo, f.get("campo", "?"), ESTADO_TEXTO.get(motivo, motivo), motivo))
    return filas


# ---------------- Identificación del equipo ----------------
def _norm_mac(valor) -> str:
    m = str(valor or "").strip().upper().replace("-", ":")
    return m if re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", m) else ""


def identifiers_from_scan(scan: dict) -> list[tuple[str, str]]:
    """Identificadores (tipo, valor) para reconocer el equipo sin depender de su nombre."""
    inv = _d(_d(scan).get("inventory"))
    ident, placa = _d(inv.get("identity")), _d(inv.get("motherboard"))
    resumen = _d(_d(scan).get("summary"))
    candidatos = [("uuid", ident.get("uuid")),
                  ("serial", ident.get("serial") or resumen.get("serial")),
                  ("board_serial", placa.get("serial"))]
    candidatos += [("mac", a.get("mac")) for a in _l(_d(inv.get("network")).get("adapters"))
                   if isinstance(a, dict)]
    salida = []
    for tipo, valor in candidatos:
        v = _norm_mac(valor) if tipo == "mac" else str(valor or "").strip().upper()
        if v and (tipo, v) not in salida:
            salida.append((tipo, v))
    return salida


# ---------------- Comparación entre capturas ----------------
def _resumen(scan: dict) -> dict:
    inv = _d(_d(scan).get("inventory"))
    mem, sto = _d(inv.get("memory")), _d(inv.get("storage"))
    return {
        "Equipo": " ".join(p for p in (_d(inv.get("identity")).get("manufacturer"),
                                       _d(inv.get("identity")).get("model")) if p) or None,
        "Procesador": _d(inv.get("cpu")).get("name"),
        "Memoria RAM": f'{round(mem["total_gb"])} GB' if mem.get("total_gb") else None,
        "Módulos de RAM": len(_l(mem.get("modules"))) or None,
        "Unidades de almacenamiento": sorted(
            f'{u.get("model") or "Disco"} {fmt_bytes(u["size_bytes"])}'
            for u in _l(sto.get("physical")) if u.get("size_bytes")) or None,
        "Gráficos": sorted(g["name"] for g in _l(_d(inv.get("graphics")).get("adapters"))
                           if g.get("name")) or None,
        "Sistema operativo": " ".join(p for p in (_d(inv.get("os")).get("name"),
                                                  _d(inv.get("os")).get("build")) if p) or None,
        "Desgaste de batería": _d(inv.get("battery")).get("wear_pct"),
    }


def _fmt_cambio(area: str, v) -> str:
    if isinstance(v, list):
        return ", ".join(v)
    return f"{v:g} %" if area == "Desgaste de batería" else str(v)


def compare_captures(antes: dict, despues: dict) -> list[dict]:
    """Cambios entre dos capturas. Un dato que falta en alguna de las dos no cuenta como cambio."""
    a, b = _resumen(antes), _resumen(despues)
    cambios = []
    for area in a:
        x, y = a[area], b[area]
        if x is None or y is None or x == y:
            continue
        if area == "Desgaste de batería" and abs(x - y) < 5:
            continue
        cambios.append({"area": area, "antes": _fmt_cambio(area, x), "despues": _fmt_cambio(area, y)})
    return cambios
