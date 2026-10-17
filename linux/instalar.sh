#!/bin/sh
# Instala Sistema Inteligente Offline en Linux para el usuario actual (no necesita sudo).
#   Programa:  ~/.local/opt/SistemaDiagnostico
#   Menú:      ~/.local/share/applications/sistemadiagnostico.desktop
#   Comando:   ~/.local/bin/sistemadiagnostico
# Los datos (base de datos, reportes, copias, paquete de IA) viven en ~/.local/share/SistemaDiagnostico
# y no se tocan al actualizar ni al desinstalar.
# Uso:  sh instalar.sh
set -e
ORIGEN=$(cd "$(dirname "$0")" && pwd)
DESTINO="$HOME/.local/opt/SistemaDiagnostico"
MENU="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
BIN="$HOME/.local/bin"

if [ ! -x "$ORIGEN/SistemaDiagnostico/SistemaDiagnostico" ]; then
    echo "No se encontró el programa junto a este instalador (carpeta SistemaDiagnostico)."
    exit 1
fi
if pgrep -x SistemaDiagnostico >/dev/null 2>&1; then
    echo "El programa está abierto. Ciérrelo y vuelva a ejecutar el instalador."
    exit 1
fi

echo "Instalando en $DESTINO…"
mkdir -p "$(dirname "$DESTINO")" "$MENU" "$BIN"
rm -rf "$DESTINO.nuevo"
cp -r "$ORIGEN/SistemaDiagnostico" "$DESTINO.nuevo"
rm -rf "$DESTINO"
mv "$DESTINO.nuevo" "$DESTINO"
chmod +x "$DESTINO/SistemaDiagnostico"
[ -f "$DESTINO/Colector/Colector" ] && chmod +x "$DESTINO/Colector/Colector"

ICONO="$DESTINO/_internal/app/assets/icono.png"
cat > "$MENU/sistemadiagnostico.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Sistema Inteligente Offline
Comment=Diagnóstico de computadoras para talleres de servicio técnico
Exec="$DESTINO/SistemaDiagnostico"
Icon=$ICONO
Terminal=false
Categories=Utility;System;
StartupWMClass=SistemaDiagnostico
EOF
ln -sf "$DESTINO/SistemaDiagnostico" "$BIN/sistemadiagnostico"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$MENU" >/dev/null 2>&1 || true

echo "Listo. Abra «Sistema Inteligente Offline» desde el menú de aplicaciones"
echo "o escriba sistemadiagnostico en una terminal."

# Dependencias del sistema: Qt necesita libxcb-cursor en escritorios X11; las demás son opcionales
falta=""
if command -v ldconfig >/dev/null 2>&1 && ! ldconfig -p 2>/dev/null | grep -q "libxcb-cursor.so.0"; then
    falta="$falta libxcb-cursor0"
fi
for p in smartctl:smartmontools dmidecode:dmidecode lspci:pciutils sensors:lm-sensors; do
    command -v "${p%%:*}" >/dev/null 2>&1 || falta="$falta ${p#*:}"
done
if [ -n "$falta" ]; then
    echo
    echo "Recomendado: instale estos paquetes para ver todos los datos del hardware:"
    echo "   sudo apt install$falta      (Debian/Ubuntu/Mint)"
    echo "   sudo dnf install$falta      (Fedora; libxcb-cursor0 se llama xcb-util-cursor)"
fi
