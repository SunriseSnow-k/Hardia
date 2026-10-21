#!/bin/sh
# Desinstala Sistema Inteligente Offline del usuario actual. Los datos NO se borran:
# quedan en ~/.local/share/SistemaDiagnostico (bórrelos a mano si ya no los necesita).
# Uso:  sh desinstalar.sh
DATOS="${XDG_DATA_HOME:-$HOME/.local/share}"
DESTINO="$HOME/.local/opt/SistemaDiagnostico"
MENU="$DATOS/applications"
# ¿Está abierto? Se mira el ejecutable real de cada proceso: el nombre se corta a 15 caracteres y
# la línea de comandos puede ser la del enlace ~/.local/bin/sistemadiagnostico
abierto() {
    [ -d "$DESTINO" ] || return 1
    exe="$(cd "$DESTINO" && pwd -P)/SistemaDiagnostico"
    for p in /proc/[0-9]*/exe; do
        case "$(readlink "$p" 2>/dev/null)" in "$exe"|"$exe (deleted)") return 0 ;; esac
    done
    return 1
}
if abierto; then
    echo "El programa está abierto. Ciérrelo y vuelva a intentarlo."
    exit 1
fi
rm -rf "$DESTINO" "$DESTINO.nuevo"
rm -f "$MENU/sistemadiagnostico.desktop" "$HOME/.local/bin/sistemadiagnostico" \
      "$DATOS/icons/hicolor/256x256/apps/sistemadiagnostico.png"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$MENU" >/dev/null 2>&1
echo "Programa desinstalado. Sus datos siguen en $DATOS/SistemaDiagnostico"
