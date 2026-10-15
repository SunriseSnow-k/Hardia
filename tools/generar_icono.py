"""Genera app/assets/icono.ico (16 a 256 px) e icono.png (256 px) dibujándolos con Qt.

Uso: .venv\\Scripts\\python tools\\generar_icono.py
Solo hace falta volver a ejecutarlo si se cambia el diseño del ícono."""
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen  # noqa: E402

DESTINO = Path(__file__).resolve().parents[1] / "app" / "assets"
TAMANOS = (16, 24, 32, 48, 64, 128, 256)
FONDO_1, FONDO_2 = QColor("#24506a"), QColor("#1d2733")
ACENTO = QColor("#5ec1df")


def dibujar(n: int) -> QImage:
    img = QImage(n, n, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)

    # Fondo: cuadrado redondeado con degradado
    grad = QLinearGradient(0, 0, 0, n)
    grad.setColorAt(0, FONDO_1)
    grad.setColorAt(1, FONDO_2)
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    m = n * 0.04
    p.drawRoundedRect(QRectF(m, m, n - 2 * m, n - 2 * m), n * 0.22, n * 0.22)

    pequeno = n <= 24
    trazo = max(1.6, n * (0.075 if pequeno else 0.055))

    # Monitor
    pantalla = QRectF(n * 0.18, n * 0.22, n * 0.64, n * (0.50 if pequeno else 0.44))
    p.setPen(QPen(Qt.white, trazo, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(pantalla, n * 0.05, n * 0.05)
    if not pequeno:
        base_y = pantalla.bottom() + n * 0.07
        p.drawLine(QPointF(n * 0.5, pantalla.bottom()), QPointF(n * 0.5, base_y))
        p.drawLine(QPointF(n * 0.36, base_y + trazo * 0.2), QPointF(n * 0.64, base_y + trazo * 0.2))

    # Pulso dentro de la pantalla
    cy = pantalla.center().y()
    a = pantalla.height() * 0.30
    x0, x1 = pantalla.left() + n * 0.06, pantalla.right() - n * 0.06
    w = x1 - x0
    puntos = [(0, 0), (0.28, 0), (0.38, -a), (0.52, a), (0.64, -a * 0.45), (0.72, 0), (1, 0)]
    camino = QPainterPath(QPointF(x0, cy))
    for fx, dy in puntos[1:]:
        camino.lineTo(QPointF(x0 + w * fx, cy + dy))
    p.setPen(QPen(ACENTO, trazo * (0.95 if pequeno else 0.85), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPath(camino)
    p.end()
    return img


def png(img: QImage) -> bytes:
    datos = QByteArray()
    buf = QBuffer(datos)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(datos)


def escribir_ico(path: Path, imagenes: list[tuple[int, bytes]]):
    cabecera = struct.pack("<HHH", 0, 1, len(imagenes))
    offset = 6 + 16 * len(imagenes)
    entradas, cuerpo = b"", b""
    for n, datos in imagenes:
        lado = 0 if n >= 256 else n
        entradas += struct.pack("<BBBBHHII", lado, lado, 0, 0, 1, 32, len(datos), offset + len(cuerpo))
        cuerpo += datos
    path.write_bytes(cabecera + entradas + cuerpo)


def main() -> int:
    _app = QGuiApplication(sys.argv)
    DESTINO.mkdir(parents=True, exist_ok=True)
    imagenes = [(n, png(dibujar(n))) for n in TAMANOS]
    escribir_ico(DESTINO / "icono.ico", imagenes)
    (DESTINO / "icono.png").write_bytes(imagenes[-1][1])
    print(f"Ícono generado en {DESTINO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
