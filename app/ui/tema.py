"""MVCD_Paleta de colores de la interfaz: el único lugar del programa donde se escriben colores.

Las pantallas usan nombres con significado (T.peligro, T.texto_suave…), nunca códigos hexadecimales.
Para el modo oscuro bastará con definir otra MVCD_Paleta con los mismos nombres y activarla con usar()
antes de crear las ventanas (los estilos se arman al importar los módulos y al llamar a qss()).
"""
from dataclasses import asdict, dataclass
from string import Template


@dataclass(frozen=True)
class MVCD_Paleta:
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    # Texto
    texto: str
    texto_suave: str
    deshabilitado: str
    # Superficies y bordes
    fondo_app: str
    superficie: str
    fondo_cabecera: str
    borde: str
    pista: str
    # Marca
    acento: str
    acento_hover: str
    acento_deshabilitado: str
    acento_suave: str
    acento_claro: str
    # Estados (el texto siempre va escrito: el color nunca es la única señal)
    peligro: str
    peligro_suave: str
    aviso: str
    aviso_suave: str
    aviso_borde: str
    aviso_texto: str
    exito: str
    exito_suave: str
    # Barra lateral y pantalla de acceso
    lateral: str
    lateral_seleccion: str
    lateral_texto: str
    sobre_acento: str


CLARO = MVCD_Paleta(
    texto="#1b2430", texto_suave="#5f6b77", deshabilitado="#a0a9b3",
    fondo_app="#eef1f4", superficie="white", fondo_cabecera="#f6f8fa", borde="#d9dfe5", pista="#e6eaee",
    acento="#1f6f8b", acento_hover="#185a72", acento_deshabilitado="#a9c7d2", acento_suave="#e1f0f5",
    acento_claro="#5ec1df",
    peligro="#c0392b", peligro_suave="#fbe6e3",
    aviso="#b7791f", aviso_suave="#fbf0d9", aviso_borde="#ecd9a8", aviso_texto="#7a5a12",
    exito="#2f855a", exito_suave="#e1f3e8",
    lateral="#1d2733", lateral_seleccion="#2a3644", lateral_texto="#a9b6c4", sobre_acento="white",
)


class MVCD__Activa:
    # Q,A,K;M   M,V,C,D   V,O,N,F   M,M,A,E
    """Acceso a la paleta activa: `T.acento`. Se usa siempre a través de este objeto."""

    _paleta: MVCD_Paleta = CLARO

    def __getattr__(self, nombre: str) -> str:
        return getattr(self._paleta, nombre)


T = MVCD__Activa()


def usar(paleta: MVCD_Paleta) -> None:
    MVCD__Activa._paleta = paleta


def rellenar(plantilla: str) -> str:
    """Sustituye $nombre por el color de la paleta activa (para hojas de estilo con llaves)."""
    return Template(plantilla).substitute(asdict(MVCD__Activa._paleta))
