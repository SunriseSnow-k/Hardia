#!/bin/sh
# Desinstala Sistema Inteligente Offline del usuario actual. Los datos NO se borran:
# quedan en ~/.local/share/SistemaDiagnostico (bórrelos a mano si ya no los necesita).
# Uso:  sh desinstalar.sh
DESTINO="$HOME/.local/opt/SistemaDiagnostico"
MENU="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
if pgrep -x SistemaDiagnostico >/dev/null 2>&1; then
    echo "El programa está abierto. Ciérrelo y vuelva a intentarlo."
    exit 1
fi
rm -rf "$DESTINO"
rm -f "$MENU/sistemadiagnostico.desktop" "$HOME/.local/bin/sistemadiagnostico"
echo "Programa desinstalado. Sus datos siguen en ${XDG_DATA_HOME:-$HOME/.local/share}/SistemaDiagnostico"
