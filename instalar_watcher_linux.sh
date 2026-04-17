#!/bin/bash
# ============================================================
#  DXF WATCHER — Instalador de servicio systemd (Linux)
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$(which python3)"
SERVICE_NAME="dxf-watcher"
USER="$(whoami)"

echo "=============================================="
echo " DXF WATCHER — Instalador Linux (systemd)"
echo "=============================================="
echo " Directorio : $SCRIPT_DIR"
echo " Python     : $PYTHON"
echo " Usuario    : $USER"
echo ""

# Instalar watchdog si no está
if ! $PYTHON -c "import watchdog" 2>/dev/null; then
    echo "Instalando watchdog..."
    $PYTHON -m pip install watchdog --user
fi

# Crear archivo de servicio systemd
SERVICE_FILE="$HOME/.config/systemd/user/${SERVICE_NAME}.service"
mkdir -p "$HOME/.config/systemd/user"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=DXF Watcher - Generador automático de PDFs
After=network.target

[Service]
Type=simple
ExecStart=$PYTHON $SCRIPT_DIR/dxf_watcher.py --config $SCRIPT_DIR/watcher_config.json
WorkingDirectory=$SCRIPT_DIR
Restart=on-failure
RestartSec=10
StandardOutput=append:$SCRIPT_DIR/dxf_watcher.log
StandardError=append:$SCRIPT_DIR/dxf_watcher.log

[Install]
WantedBy=default.target
EOF

echo "Servicio creado: $SERVICE_FILE"
echo ""

# Habilitar e iniciar
systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME"
systemctl --user start "$SERVICE_NAME"

echo "Estado del servicio:"
systemctl --user status "$SERVICE_NAME" --no-pager

echo ""
echo "Comandos útiles:"
echo "  Estado  : systemctl --user status $SERVICE_NAME"
echo "  Parar   : systemctl --user stop $SERVICE_NAME"
echo "  Iniciar : systemctl --user start $SERVICE_NAME"
echo "  Logs    : journalctl --user -u $SERVICE_NAME -f"
echo "  Desinstalar: systemctl --user disable --now $SERVICE_NAME && rm $SERVICE_FILE"
