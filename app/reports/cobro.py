"""Presupuesto (PDF para que el cliente lo apruebe) y estado de cuenta con los pagos recibidos."""

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Spacer, Table

from app.db.billing_repo import TIPOS_LINEA
from app.db.clients_repo import ClientsRepository
from app.servicios import cobro

from . import base
from .base import _aviso, _estilo_tabla, _fecha, _kv, _p, _styles
from .orden import _firmas


def load_billing_data(repo, code: str) -> dict:
    caso = repo.get_case(code)
    if caso is None:
        raise ValueError(f"No existe el caso {code}.")
    return {
        "caso": caso, "doc_id": ClientsRepository(repo).doc_for_case(code),
        "resumen": cobro.resumen(repo, code), "simbolo": cobro.simbolo(repo),
        "business": repo.get_setting("business_name", "Mi taller"),
        "phone": repo.get_setting("business_phone", ""),
    }


def _encabezado(data: dict, titulo: str, st) -> list:
    caso = data["caso"]
    contacto = data["business"] + (f' · Teléfono: {data["phone"]}' if data["phone"] else "")
    return [
        _p(contacto, st["biz"]), _p(titulo, st["h1"]), Spacer(1, 4 * mm),
        _kv([("N.º de orden", caso["code"]), ("Cliente", caso["cliente"]), ("Documento", data["doc_id"]),
             ("Equipo", f'{caso["equipo"]} · Serie {caso["serial"]}')], st),
    ]


def _tabla_lineas(data: dict, st) -> Table:
    r, s = data["resumen"], data["simbolo"]
    num = ParagraphStyle("num", parent=st["cell"], alignment=2)
    num_b = ParagraphStyle("num_b", parent=num, fontName="Helvetica-Bold")
    filas = [[_p(h, st["head"]) for h in ("Descripción", "Tipo", "Cant.", "P. unitario", "Importe")]]
    for li in r.lineas:
        filas.append([_p(li["description"], st["cell"]), _p(TIPOS_LINEA.get(li["kind"], li["kind"]), st["cell"]),
                      _p(str(li["quantity"]), num), _p(cobro.formato(li["unit_price"], s), num),
                      _p(cobro.formato(li["quantity"] * li["unit_price"], s), num)])
    totales = [("Subtotal", r.subtotal)]
    if r.descuento:
        totales.append(("Descuento", -r.descuento))
    totales.append(("Total", r.total))
    inicio = len(filas)
    for etiqueta, valor in totales:
        filas.append(["", "", "", _p(etiqueta, num_b), _p(cobro.formato(valor, s), num_b)])
    t = Table(filas, colWidths=[78 * mm, 24 * mm, 14 * mm, 27 * mm, 27 * mm], repeatRows=1)
    t.setStyle(_estilo_tabla([("GRID", (0, inicio), (2, -1), 0.4, colors.white),
                              ("LINEABOVE", (3, inicio), (-1, inicio), 0.8, base.TEXTO)]))
    return t


def build_quote(data: dict, path, tech_id: str = "") -> None:
    st = _styles()
    r = data["resumen"]
    story = _encabezado(data, "Presupuesto", st)
    story.append(_p("Detalle", st["h2"]))
    if r.lineas:
        story.append(_tabla_lineas(data, st))
    else:
        story.append(_p("El presupuesto aún no tiene líneas.", st["body"]))
    if r.notas:
        story.append(_p("Notas", st["h2"]))
        story.append(_p(r.notas, st["body"]))
    if r.pagado:
        story.append(Spacer(1, 3 * mm))
        story.append(_p(f'Pagos a cuenta: {cobro.formato(r.pagado, data["simbolo"])} · '
                        f'Saldo: {cobro.formato(r.saldo, data["simbolo"])}', st["body"]))
    story.append(Spacer(1, 4 * mm))
    if r.estado == "Aprobado":
        story.append(_aviso(f"Presupuesto aprobado el {_fecha(r.decidido_el)}"
                            f'{" (registrado por " + r.decidido_por + ")" if r.decidido_por else ""}.', st))
    story.append(Spacer(1, 8 * mm))
    story.append(KeepTogether([
        _p("Con su firma, el cliente aprueba el presupuesto y autoriza la realización de los trabajos "
           "detallados.", st["small"]),
        Spacer(1, 4 * mm),
        _firmas("Firma del cliente", f"Técnico{': ' + tech_id if tech_id else ''}", st),
    ]))
    base._construir(story, path, f'Presupuesto {data["caso"]["code"]}', tech_id, data["caso"]["code"])


def build_statement(data: dict, path, tech_id: str = "") -> None:
    st = _styles()
    r, s = data["resumen"], data["simbolo"]
    story = _encabezado(data, "Estado de cuenta", st)
    story.append(_p("Trabajos", st["h2"]))
    if r.lineas:
        story.append(_tabla_lineas(data, st))
    else:
        story.append(_p("Sin presupuesto registrado.", st["body"]))
    story.append(_p("Pagos recibidos", st["h2"]))
    vigentes = [p for p in r.pagos if not p["voided_at"]]
    if vigentes:
        filas = [[_p(h, st["head"]) for h in ("Fecha", "Forma de pago", "Recibido por", "Importe")]]
        filas += [[_p(_fecha(p["created_at"]), st["cell"]), _p(p["method"], st["cell"]),
                   _p(p["tech_id"], st["cell"]), _p(cobro.formato(p["amount"], s), st["cell"])] for p in vigentes]
        t = Table(filas, colWidths=[40 * mm, 50 * mm, 40 * mm, 40 * mm], repeatRows=1)
        t.setStyle(_estilo_tabla())
        story.append(t)
    else:
        story.append(_p("Aún no se registraron pagos.", st["body"]))
    story.append(Spacer(1, 4 * mm))
    story.append(_kv([("Total", cobro.formato(r.total, s)), ("Pagado", cobro.formato(r.pagado, s)),
                      ("Saldo pendiente", cobro.formato(max(r.saldo, 0), s))], st))
    if r.saldo < 0:
        story.append(_p(f"Saldo a favor del cliente: {cobro.formato(-r.saldo, s)}", st["body"]))
    story.append(Spacer(1, 4 * mm))
    story.append(_p("Este documento es un comprobante interno del taller y no reemplaza al comprobante de "
                    "pago tributario.", st["small"]))
    base._construir(story, path, f'Estado de cuenta {data["caso"]["code"]}', tech_id, data["caso"]["code"])
