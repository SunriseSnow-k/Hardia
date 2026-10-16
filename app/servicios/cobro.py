"""Presupuesto y cobro de un caso.

Reglas:
- El presupuesto se arma con líneas de servicio o repuesto y un descuento opcional. Solo se puede
  modificar mientras no esté aprobado y el equipo no se haya entregado.
- Estados: Borrador → Enviado → Aprobado o Rechazado. Un presupuesto aprobado o rechazado se puede
  reabrir (vuelve a Borrador); reabrir uno aprobado es solo para administradores.
- Los pagos (adelantos incluidos) no pueden superar el saldo de un presupuesto con importe. Sin
  presupuesto se aceptan adelantos libres. Los pagos nunca se borran: un administrador los anula
  indicando el motivo.
- Aprobar, rechazar, reabrir, cobrar y anular quedan en el registro de auditoría.
"""
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.db.billing_repo import ESTADOS_PRESUPUESTO, METODOS_PAGO, TIPOS_LINEA, BillingRepository
from app.db.repo import Repository
from app.db.users_repo import UsersRepository

from .cuentas import SinPermiso, auditar, requerir_admin

MAX_IMPORTE = 100_000_000  # céntimos (1 000 000,00): evita errores de tipeo con ceros de más
MAX_CANTIDAD = 999
MAX_DESCRIPCION = 200
SIMBOLO_PREDETERMINADO = "S/"


# ---------------- importes ----------------
def a_centimos(texto) -> int:
    """'120' → 12000; '120,5' → 12050; '1.250,90' y '1,250.90' → 125090. Rechaza negativos,
    más de dos decimales y textos que no son importes."""
    t = re.sub(r"[^\d.,\-]", "", str(texto or ""))
    if not t:
        raise ValueError("Escriba un importe.")
    if "," in t and "." in t:  # el último separador es el decimal
        miles, decimal = (",", ".") if t.rfind(".") > t.rfind(",") else (".", ",")
        t = t.replace(miles, "").replace(decimal, ".")
    elif "," in t:
        partes = t.split(",")
        t = t.replace(",", ".") if len(partes) == 2 and len(partes[1]) <= 2 else t.replace(",", "")
    elif t.count(".") > 1 or ("." in t and len(t.split(".")[1]) == 3):
        t = t.replace(".", "")  # '1.250' o '1.250.000': separador de miles
    try:
        valor = Decimal(t)
    except InvalidOperation:
        raise ValueError("El importe no es válido.") from None
    if valor < 0:
        raise ValueError("El importe no puede ser negativo.")
    if valor != valor.quantize(Decimal("0.01")):
        raise ValueError("El importe admite como máximo dos decimales.")
    centimos = int(valor * 100)
    if centimos > MAX_IMPORTE:
        raise ValueError("El importe es demasiado grande; revise los ceros.")
    return centimos


def formato(centimos: int, simbolo: str = SIMBOLO_PREDETERMINADO) -> str:
    """12050 → 'S/ 120.50'; los negativos llevan el signo delante del símbolo."""
    signo = "-" if centimos < 0 else ""
    return f"{signo}{simbolo} {abs(centimos) / 100:,.2f}".strip()


def simbolo(repo: Repository) -> str:
    return repo.get_setting("currency_symbol", SIMBOLO_PREDETERMINADO).strip() or SIMBOLO_PREDETERMINADO


# ---------------- consulta ----------------
@dataclass
class Resumen:
    estado: str  # estado del presupuesto ("Sin presupuesto" si aún no tiene líneas)
    subtotal: int
    descuento: int
    total: int
    pagado: int
    lineas: list = field(default_factory=list)
    pagos: list = field(default_factory=list)  # incluye los anulados
    notas: str = ""
    decidido_por: str = ""
    decidido_el: str = ""

    @property
    def saldo(self) -> int:
        """Lo que falta cobrar (negativo si el cliente pagó de más)."""
        return self.total - self.pagado

    @property
    def editable(self) -> bool:
        return self.estado != "Aprobado"


def resumen(repo: Repository, code: str) -> Resumen:
    b = BillingRepository(repo)
    q = b.quote(code)
    lineas = b.items(code)
    subtotal = b.subtotal(code)
    descuento = min(q["discount"], subtotal) if q else 0
    estado = q["status"] if q else "Borrador"
    if estado == "Borrador" and not lineas:
        estado = "Sin presupuesto"
    return Resumen(estado, subtotal, descuento, subtotal - descuento, b.paid(code), lineas, b.payments(code),
                   q["notes"] if q else "", q["decided_by"] if q else "", q["decided_at"] if q else "")


def saldo_pendiente(repo: Repository, code: str) -> int:
    return max(resumen(repo, code).saldo, 0)


# ---------------- presupuesto ----------------
def _caso(repo: Repository, code: str):
    caso = repo.get_case(code)
    if caso is None:
        raise ValueError(f"No existe el caso {code}.")
    return caso


def _modificable(repo: Repository, code: str) -> None:
    if _caso(repo, code)["status"] == "Entregado":
        raise ValueError("El equipo ya fue entregado: el presupuesto no se puede modificar.")
    q = BillingRepository(repo).quote(code)
    if q and q["status"] == "Aprobado":
        raise ValueError("El presupuesto ya fue aprobado. Reábralo para modificarlo.")


def agregar_linea(repo: Repository, code: str, tipo: str, descripcion: str, cantidad: int,
                  precio: int) -> int:
    """Agrega una línea al presupuesto. `precio` es el precio unitario en céntimos."""
    _modificable(repo, code)
    if tipo not in TIPOS_LINEA:
        raise ValueError("Tipo de línea no válido.")
    descripcion = (descripcion or "").strip()
    if not descripcion:
        raise ValueError("Escriba la descripción del servicio o repuesto.")
    if len(descripcion) > MAX_DESCRIPCION:
        raise ValueError(f"La descripción supera los {MAX_DESCRIPCION} caracteres.")
    if not 1 <= int(cantidad) <= MAX_CANTIDAD:
        raise ValueError(f"La cantidad debe estar entre 1 y {MAX_CANTIDAD}.")
    if not 0 <= int(precio) <= MAX_IMPORTE:
        raise ValueError("El precio no es válido.")
    return BillingRepository(repo).add_item(code, tipo, descripcion, int(cantidad), int(precio))


def quitar_linea(repo: Repository, item_id: int) -> None:
    b = BillingRepository(repo)
    linea = b.item(item_id)
    if linea is None:
        raise ValueError("La línea ya no existe.")
    _modificable(repo, linea["case_code"])
    b.delete_item(item_id)


def fijar_descuento(repo: Repository, code: str, descuento: int, notas: str | None = None) -> None:
    _modificable(repo, code)
    if descuento < 0 or descuento > BillingRepository(repo).subtotal(code):
        raise ValueError("El descuento no puede superar el subtotal.")
    campos: dict = {"discount": int(descuento)}
    if notas is not None:
        notas = notas.strip()
        if len(notas) > 500:
            raise ValueError("Las notas del presupuesto superan los 500 caracteres.")
        campos["notes"] = notas
    BillingRepository(repo).update_quote(code, **campos)


def cambiar_estado(repo: Repository, actor: str, code: str, estado: str) -> None:
    """Enviar, aprobar, rechazar o reabrir (estado 'Borrador') el presupuesto."""
    if estado not in ESTADOS_PRESUPUESTO:
        raise ValueError("Estado de presupuesto no válido.")
    if _caso(repo, code)["status"] == "Entregado":
        raise ValueError("El equipo ya fue entregado: el presupuesto no se puede modificar.")
    actual = resumen(repo, code)
    if actual.estado == estado:
        return
    if estado != "Borrador" and not actual.lineas:
        raise ValueError("Agregue al menos una línea al presupuesto.")
    if estado == "Borrador" and actual.estado == "Aprobado":
        requerir_admin(repo, actor)
    if UsersRepository(repo).role(actor) is None:
        raise SinPermiso("La sesión no corresponde a un técnico activo.")
    decidido = estado in ("Aprobado", "Rechazado")
    total = formato(actual.total, simbolo(repo))
    with repo.transaccion():
        BillingRepository(repo).update_quote(
            code, status=estado, decided_by=actor.strip().upper() if decidido else "",
            decided_at=repo.c.execute("SELECT datetime('now','localtime')").fetchone()[0] if decidido else "")
        if decidido:
            auditar(repo, "presupuesto_aprobado" if estado == "Aprobado" else "presupuesto_rechazado",
                    actor, f"{code} · {total}")
        elif estado == "Borrador":
            auditar(repo, "presupuesto_reabierto", actor, f"{code} (estaba {actual.estado})")


# ---------------- pagos ----------------
def registrar_pago(repo: Repository, actor: str, code: str, monto: int, metodo: str, nota: str = "") -> int:
    caso = _caso(repo, code)
    if UsersRepository(repo).role(actor) is None:
        raise SinPermiso("La sesión no corresponde a un técnico activo.")
    if metodo not in METODOS_PAGO:
        raise ValueError("Forma de pago no válida.")
    if monto <= 0:
        raise ValueError("El importe del pago debe ser mayor que cero.")
    nota = (nota or "").strip()
    if len(nota) > MAX_DESCRIPCION:
        raise ValueError(f"La nota supera los {MAX_DESCRIPCION} caracteres.")
    r = resumen(repo, code)
    if r.estado == "Rechazado":
        raise ValueError("El presupuesto fue rechazado; reábralo antes de registrar un pago.")
    if caso["status"] == "Entregado" and r.saldo <= 0:
        raise ValueError("El caso ya fue entregado y no tiene saldo pendiente.")
    if r.total > 0 and monto > r.saldo:
        raise ValueError(f"El pago supera el saldo pendiente ({formato(max(r.saldo, 0), simbolo(repo))}).")
    with repo.transaccion():
        pid = BillingRepository(repo).add_payment(code, monto, metodo, nota, actor.strip().upper())
        auditar(repo, "pago_registrado", actor, f"{code} · {formato(monto, simbolo(repo))} · {metodo}")
    return pid


def anular_pago(repo: Repository, actor: str, payment_id: int, motivo: str) -> None:
    requerir_admin(repo, actor)
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Indique el motivo de la anulación.")
    b = BillingRepository(repo)
    pago = b.payment(payment_id)
    if pago is None:
        raise ValueError("El pago no existe.")
    if pago["voided_at"]:
        raise ValueError("El pago ya estaba anulado.")
    with repo.transaccion():
        b.void_payment(payment_id, actor.strip().upper(), motivo[:MAX_DESCRIPCION])
        auditar(repo, "pago_anulado", actor,
                f'{pago["case_code"]} · {formato(pago["amount"], simbolo(repo))} · {motivo[:100]}')
