"""Informe para el cliente (PDF), en lenguaje simple."""

from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Spacer

from app.db.notes_repo import TIPOS_CLIENTE
from app.hardware.inventory import fmt_bytes, fuente_salud
from app.health import SIN_REF

from . import base
from .base import _aviso, _d, _e, _fecha, _kv, _l, _p, _styles
from .secciones import _cabecera, _seccion_cambios

URGENCIA = {"Alta": "Conviene atenderlo pronto", "Media": "Conviene revisarlo",
            "Baja": "No es urgente"}


IMPLICACIONES = {
    "R-001": "El equipo se calienta más de lo normal. Si no se atiende, puede apagarse solo, "
             "volverse lento y acortar la vida de sus componentes.",
    "R-002": "La ventilación no está enfriando bien el equipo; esto puede causar lentitud "
             "o apagados repentinos.",
    "R-003": "El procesador trabaja casi al máximo de forma constante; por eso el equipo responde lento.",
    "R-004": "La memoria del equipo se llena con lo que está abierto; al quedarse sin memoria, "
             "todo se vuelve lento.",
    "R-005": "El equipo tiene poca memoria para el uso que se le da; ampliarla suele mejorar la rapidez.",
    "R-006": "Queda poco espacio en el disco. Con el disco casi lleno el sistema se vuelve lento "
             "y las actualizaciones pueden fallar.",
    "R-007": "La unidad donde se guardan sus archivos muestra señales de desgaste. "
             "Le recomendamos respaldar su información cuanto antes.",
    "R-008": "El disco es de tipo mecánico, más lento que los discos de estado sólido (SSD).",
    "R-009": "Muchos programas se abren solos al encender, lo que hace lento el arranque y el uso diario.",
    "R-010": "Puede haber un problema con la alimentación eléctrica (cargador, fuente o conexión), "
             "lo que explicaría que no encienda o se apague.",
    "R-011": "Los reinicios pueden deberse a la memoria o a la alimentación; hay que confirmarlo con pruebas.",
    "R-012": "Una actualización o un controlador (el programa que maneja una pieza del equipo) "
             "puede estar causando las fallas.",
    "R-013": "Puede haber programas no deseados o dañinos que hacen lento el equipo "
             "o ponen en riesgo su información.",
    "R-014": "La parte que maneja la imagen (tarjeta o controlador de video) podría estar fallando.",
    "R-015": "La tarjeta de video se calienta demasiado; puede provocar cierres de juegos o programas, "
             "fallas de imagen y acortar su vida útil.",
    "R-016": "Un ventilador no está girando, así que el equipo no se enfría bien y puede apagarse "
             "o dañarse por calor.",
    "R-017": "El procesador se calienta incluso sin trabajo pesado; suele deberse a polvo o pasta "
             "térmica seca.",
    "R-018": "La unidad de estado sólido (SSD) se acerca al final de su vida útil. Le recomendamos "
             "respaldar su información y planificar su cambio.",
    "R-019": "El sistema detectó fallas en la unidad donde se guardan sus archivos. Respalde su "
             "información cuanto antes.",
    "R-020": "La unidad de almacenamiento trabaja muy caliente, lo que puede volverla lenta y "
             "reducir su vida útil.",
}


IMPLICACION_GENERICA = "Nuestro técnico le explicará qué significa y cómo resolverlo."


def client_summary(result: dict, max_items: int = 3) -> list[tuple[str, str]]:
    """Causas en lenguaje simple para el cliente: (causa, urgencia)."""
    return [(c["cause"], URGENCIA.get(c["priority"], ""))
            for c in result.get("causes", [])[:max_items]]


def implication(cause: dict) -> str:
    return IMPLICACIONES.get(str(cause.get("id")), IMPLICACION_GENERICA)


def measured_items(scan: dict | None) -> list[tuple[str, str]]:
    """Lo que medimos, en palabras simples. Solo incluye datos realmente leídos."""
    inv = _d(_d(scan).get("inventory"))
    if not inv:  # escaneo antiguo: se usa la lista de componentes tal como se leyó
        return [(c.get("name", "?"), c.get("detail", "")) for c in _l(_d(scan).get("components"))
                if isinstance(c, dict) and c.get("status") == "ok" and c.get("detail")]
    items = []
    ident = _d(inv.get("identity"))
    marca = " ".join(p for p in (ident.get("manufacturer"), ident.get("model")) if p)
    if marca:
        items.append(("Equipo", marca))
    cpu = _d(inv.get("cpu"))
    if cpu.get("name"):
        items.append(("Procesador", cpu["name"]))
    mem = _d(inv.get("memory"))
    if mem.get("total_gb"):
        uso = f' (en uso {mem["used_pct"]:.0f} % al momento de la revisión)' if mem.get("used_pct") is not None else ""
        items.append(("Memoria RAM", f'{round(mem["total_gb"])} GB{uso}'))
    sto = _d(inv.get("storage"))
    for u in _l(sto.get("physical")):
        if not isinstance(u, dict) or not u.get("size_bytes"):
            continue
        tipo = u.get("media") or "Unidad"
        estado = (f' — estado: {u["health"]} ({fuente_salud(u.get("health_source"))})'
                  if u.get("health") else "")
        items.append(("Disco", f'{tipo} de {fmt_bytes(u["size_bytes"])}{estado}'))
    for v in _l(sto.get("logical")):
        if isinstance(v, dict) and v.get("size_bytes") and v.get("free_bytes") is not None:
            items.append((f'Espacio libre en {v.get("drive", "el disco")}',
                          f'{fmt_bytes(v["free_bytes"])} de {fmt_bytes(v["size_bytes"])}'))
    sen = _d(inv.get("sensors"))
    temp = _d(_d(scan).get("metrics")).get("cpu_temp")
    if temp is not None:
        fuente = sen.get("cpu_temp_source")
        nota = "" if fuente == "LibreHardwareMonitor" else " (sensor general del equipo; valor aproximado)"
        items.append(("Temperatura", f"{float(temp):.0f} °C{nota}"))
    bat = _d(inv.get("battery"))
    if bat.get("wear_pct") is not None:
        items.append(("Batería", f'desgaste estimado {bat["wear_pct"]:.0f} %'))
    so = _d(inv.get("os"))
    if so.get("name"):
        items.append(("Sistema operativo", so["name"]))
    return items


def salud_para_cliente(data: dict) -> list[tuple[str, str]]:
    """Componentes con estado conocido, en palabras simples (sin datos técnicos internos)."""
    res = _d(_d(data.get("health")).get("resultado"))
    items = []
    ind = _d(res.get("indice"))
    if ind.get("valor") is not None:
        items.append(("Estado general (orientativo)", f'{ind["valor"]:.0f} % respecto a un equipo nuevo'))
    for c in _l(res.get("componentes")):
        if c.get("estado") == SIN_REF or not c.get("cliente"):
            continue
        extra = f' ({c["pct"]:.0f} % respecto a fábrica)' if c.get("pct") is not None else ""
        items.append((c["nombre"], f'{c["estado"]}{extra}. {c["cliente"]}'))
    return items


def build_client(data: dict, path, tech_id: str = "") -> None:
    st = _styles()
    caso, res = data["caso"], data["result"]
    story = _cabecera(data, st, "Informe de revisión de su equipo")

    story.append(Spacer(1, 4 * mm))
    story.append(_p(f'Estimado/a {caso["cliente"] or "cliente"}:', st["body"]))
    story.append(Spacer(1, 2 * mm))
    story.append(_p("Gracias por confiarnos su equipo. Este es el resumen de nuestra revisión.", st["body"]))
    story.append(Spacer(1, 3 * mm))
    filas = [("Equipo", caso["equipo"]), ("N.º de serie", caso["serial"])]
    if data["doc_id"]:
        filas.insert(0, ("Documento", data["doc_id"]))
    story.append(_kv(filas, st))

    story.append(_p("Lo que nos comentó", st["h2"]))
    story.append(_p(caso["problem"], st["body"]))

    story.append(_p("Lo que medimos", st["h2"]))
    medidos = measured_items(data["scan"])
    if medidos:
        cuando = _fecha((data["capture"] or {}).get("captured_at") or _d(data["scan"]).get("scanned_at"), 10)
        story.append(_p(f"Datos leídos de su equipo el {cuando}:",
                        ParagraphStyle("intro", parent=st["body"], keepWithNext=1)))
        story.append(Spacer(1, 1.5 * mm))
        story.append(_kv(medidos, st))
        if data["unavailable"]:
            faltan = sorted({f["category"] for f in data["unavailable"]})
            story.append(Spacer(1, 1.5 * mm))
            story.append(_p("Algunos datos no se pudieron leer automáticamente ("
                            + ", ".join(faltan) + "). El técnico los revisará si hace falta.", st["small"]))
    else:
        story.append(_p("En esta revisión no se tomaron mediciones automáticas de su equipo.", st["body"]))
    salud = salud_para_cliente(data)
    if salud:
        story.append(_p("Estado de los componentes", st["h3"]))
        story.append(_kv(salud, st))
        story.append(_p("Comparamos cada componente con su valor de fábrica usando solo datos medidos; "
                        "es una orientación.", st["small"]))

    story.append(_p("Lo que encontramos", st["h2"]))
    causas = res.get("causes", [])[:3]
    if causas:
        story.append(_p("Estas son las causas más probables de la falla:", st["body"]))
        for c in causas:
            story.append(Spacer(1, 1.5 * mm))
            story.append(_p(f'• <b>{_e(c["cause"])}</b> — {_e(URGENCIA.get(c["priority"], ""))}',
                            st["body"], raw=True))
            story.append(_p(f"Qué significa: {implication(c)}", st["cell"]))
        story.append(Spacer(1, 1.5 * mm))
        story.append(_p("Se trata de posibles causas: nuestro técnico las confirmará con pruebas.", st["small"]))
    else:
        story.append(_p("Todavía no identificamos una causa con los datos disponibles. "
                        "Necesitamos revisar el equipo con más detalle en el taller.", st["body"]))

    story += _seccion_cambios(data, st, cliente=True)

    for kind, titulo in (("trabajo", "Trabajo realizado"), ("cliente", "Notas del técnico para usted")):
        notas = [n for n in data["notes"] if n["kind"] == kind and kind in TIPOS_CLIENTE]
        if notas:
            story.append(_p(titulo, st["h2"]))
            for n in notas:
                story.append(_p(f'• {_e(n["text"])} <font color="#66727f" size="8.5">'
                                f'({_e(_fecha(n["created_at"], 10))})</font>', st["body"], raw=True))

    recs = res.get("recommendations", [])[:5]
    if recs:
        story.append(_p("Lo que recomendamos", st["h2"]))
        for i, r in enumerate(recs, 1):
            story.append(_p(f"{i}. {r}", st["body"]))

    contacto = data["business"] + (f' · Teléfono: {data["phone"]}' if data["phone"] else "")
    story.append(Spacer(1, 6 * mm))
    story.append(KeepTogether([
        _aviso("Este informe es una orientación y no incluye precios ni plazos. "
               "Nos comunicaremos con usted para acordarlos antes de realizar cualquier trabajo.", st),
        Spacer(1, 6 * mm),
        _p("Atentamente,", st["body"]),
        _p(contacto, st["body"]),
        _p(f"Técnico: {tech_id or '—'}", st["small"]),
    ]))
    base._construir(story, path, f'Informe para el cliente {caso["code"]}', tech_id, caso["code"])
