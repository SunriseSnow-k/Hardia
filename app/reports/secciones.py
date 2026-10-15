"""Secciones compartidas por los reportes técnico y para el cliente."""
from datetime import datetime

from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Spacer

from app.db.hardware_repo import ORIGENES
from app.db.notes_repo import TIPOS
from app.hardware.inventory import ESTADO_TEXTO
from app.health import SIN_REF
from app.health.benchmark import texto_condiciones

from .base import ANCHO, ESTADO_HEX, _d, _e, _fecha, _kv, _l, _p, _tabla, _tabla_categoria


def _cabecera(data: dict, st: dict, titulo: str, extra=()) -> list:
    caso = data["caso"]
    return [
        _p(data["business"], st["biz"]), _p(titulo, st["h1"]), Spacer(1, 4 * mm),
        _kv([("Caso", caso["code"]),
             ("Fecha de ingreso", _fecha(caso["created_at"])),
             ("Reporte generado", datetime.now().strftime("%d/%m/%Y %H:%M")), *extra], st),
    ]


def _origen_captura(cap: dict) -> str:
    texto = ORIGENES.get(cap["source"], cap["source"])
    if cap.get("source_file"):
        texto += f' ({cap["source_file"]})'
    return texto


def _seccion_inventario(data: dict, st: dict) -> list:
    story = [_p("Inventario de hardware", st["h2"])]
    cap = data["capture"]
    if not data["scan"]:
        return story + [_p("Este caso no tiene captura de hardware. Escanee el equipo o importe "
                           "su archivo .diag para incluir el inventario.", st["small"])]
    if cap:
        story.append(_p(f'Captura del {_e(_fecha(cap["captured_at"]))} · Origen: {_e(_origen_captura(cap))}'
                        + (f' · El caso tiene {cap["count"]} capturas; se usa la más reciente.'
                           if cap["count"] > 1 else ""), st["small"], raw=True))
    else:
        story.append(_p(f'Escaneo del caso del {_e(_fecha(data["scan"].get("scanned_at")))}.',
                        st["small"], raw=True))
    story.append(Spacer(1, 2 * mm))
    if not data["categories"]:
        story.append(_p("La captura no contiene datos leídos.", st["body"]))
    for titulo, filas in data["categories"]:
        story.append(_tabla_categoria(titulo, filas, st))
        story.append(Spacer(1, 3 * mm))

    story.append(_p("Información no disponible", st["h3"]))
    if data["unavailable"]:
        filas = []
        for f in data["unavailable"]:
            dato = "Toda la categoría" if f["label"] == "Estado de la detección" else f["label"]
            motivo = f["value"] or ESTADO_TEXTO.get(f["status"], f["status"])
            filas.append([_p(f["category"], st["cell"]), _p(dato, st["cell"]), _p(motivo, st["cell"])])
        story.append(_tabla(["Categoría", "Dato", "Motivo"], filas, [42, 58, ANCHO - 100], st))
    else:
        story.append(_p("Todos los datos previstos se pudieron leer.", st["small"]))
    return story


def _seccion_cambios(data: dict, st: dict, cliente: bool = False) -> list:
    titulo = "Cambios desde su visita anterior" if cliente else "Cambios desde la inspección anterior"
    prev = data["previous"]
    if not prev:
        if cliente:
            return []
        return [_p(titulo, st["h2"]),
                _p("No hay inspecciones anteriores de este equipo con las que comparar.", st["small"])]
    story = [_p(titulo, st["h2"])]
    base = (f'Comparado con la revisión del {_fecha(prev["captured_at"], 10)}.' if cliente else
            f'Comparado con la captura del {_fecha(prev["captured_at"])} (caso {prev["case_code"]}).')
    story.append(_p(base, st["small"]))
    story.append(Spacer(1, 1.5 * mm))
    if data["changes"]:
        filas = [[_p(c["area"], st["cell"]), _p(c["antes"], st["cell"]), _p(c["despues"], st["cell"])]
                 for c in data["changes"]]
        story.append(_tabla(["Área", "Antes", "Ahora"], filas, [45, 62, ANCHO - 107], st))
    else:
        story.append(_p("No se encontraron cambios en los datos que se pueden comparar.", st["body"]))
    return [KeepTogether(story)]


def _estado_txt(estado: str) -> str:
    return f'<font color="{ESTADO_HEX.get(estado, "#1b2430")}"><b>{_e(estado)}</b></font>'


def _seccion_salud(data: dict, st: dict) -> list:
    """Salud frente a fábrica (reporte técnico): índice, componentes, prueba e inclusiones."""
    story = [_p("Salud frente a fábrica", st["h2"])]
    salud = _d(data.get("health"))
    res = salud.get("resultado")
    if not res or not res.get("componentes"):
        motivo = salud.get("error") or (res or {}).get("aviso") or "No hay datos de salud para este caso."
        return story + [_p(motivo, st["small"])]
    ind = res["indice"]
    if ind["valor"] is not None:
        story.append(_p(f'Índice orientativo: <b>{ind["valor"]:.0f} %</b> respecto a fábrica '
                        f'({_estado_txt(ind["estado"])}) · promedio simple de: {_e(", ".join(ind["incluidos"]))}.',
                        st["body"], raw=True))
    else:
        story.append(_p("No se calculó el índice: ningún componente tiene a la vez medición y referencia "
                        "de fábrica.", st["body"]))
    story.append(Spacer(1, 2 * mm))
    filas = []
    for c in res["componentes"]:
        respecto = f'{c["pct"]:.0f} %' if c.get("pct") is not None else (c.get("alt") or SIN_REF)
        filas.append([
            _p(f'<b>{_e(c["nombre"])}</b><br/><font size="8" color="#5f6b77">{_e(c.get("modelo", ""))}</font>',
               st["cell"], raw=True),
            _p(_estado_txt(c["estado"]), st["cell"], raw=True),
            _p(f'{_e(c["medido"]["valor"])}<br/><font size="8" color="#5f6b77">{_e(c["medido"]["nota"])}</font>',
               st["cell"], raw=True),
            _p(f'{_e(c["fabrica"]["valor"])}<br/><font size="8" color="#5f6b77">{_e(c["fabrica"]["nota"])}</font>',
               st["cell"], raw=True),
            _p(respecto, st["cell"]),
            _p(c.get("fuente") or "—", st["small"]),
        ])
    story.append(_tabla(["Componente", "Estado", "Medido", "De fábrica", "Respecto a fábrica", "Fuente"],
                        filas, [30, 20, 30, 30, 26, ANCHO - 136], st))
    if res.get("hallazgo"):
        story.append(Spacer(1, 2 * mm))
        story.append(_p(f'Lo más importante: {res["hallazgo"]["texto"]}', st["body"]))

    bench = salud.get("benchmark")
    story.append(_p("Prueba de rendimiento", st["h3"]))
    if bench:
        story.append(_p(f'Realizada el {_fecha(bench.get("fecha"))}. Condiciones en que se midió:', st["small"]))
        story.append(_kv(texto_condiciones(bench.get("condiciones")), st))
        cpu = _d(bench.get("cpu"))
        if cpu.get("detenido_por_temp"):
            story.append(_p(f'La prueba de CPU se detuvo por seguridad al llegar a {cpu.get("temp_max", 0):.0f} °C.',
                            st["body"]))
        for d in _l(bench.get("discos")):
            if isinstance(d, dict) and not d.get("lectura_mb_s"):
                story.append(_p(f'Disco {d.get("model") or d.get("index")}: lectura no disponible '
                                f'({d.get("motivo") or "sin datos"}).', st["small"]))
    else:
        story.append(_p("No se ejecutó la prueba de rendimiento: el procesador y la velocidad de los discos "
                        "quedan sin medición.", st["small"]))
    if salud.get("incluidos"):
        story.append(_p("Incluido en el diagnóstico por el técnico", st["h3"]))
        for i in salud["incluidos"]:
            story.append(_p(f'• {i["texto"]}', st["body"]))
    story.append(_p("El índice es orientativo: compara cada componente con su valor de fábrica usando solo datos "
                    "leídos o medidos; la validación final es del técnico.", st["small"]))
    return story


def _seccion_notas(notas: list[dict], st: dict) -> list:
    filas = [[_p(_fecha(n["created_at"]), st["cell"]), _p(TIPOS.get(n["kind"], n["kind"]), st["cell"]),
              _p(n["author"] or "—", st["cell"]), _p(n["text"], st["cell"])] for n in notas]
    return [_tabla(["Fecha", "Tipo", "Técnico", "Nota"], filas, [28, 32, 22, ANCHO - 82], st)]
