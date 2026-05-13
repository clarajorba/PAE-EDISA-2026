#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# deploy.sh  —  copia el paquete dron_control_sistema al PC del LiDAR
#               y lo compila allí dentro de ~/slam_ws
#
# Uso:
#   ./deploy.sh <usuario>@<ip>
#   ./deploy.sh unitree@192.168.1.100
# ---------------------------------------------------------------------------
set -euo pipefail

REMOTE="${1:-}"
if [[ -z "$REMOTE" ]]; then
    echo "Uso: $0 <usuario>@<ip_del_lidar>"
    echo "  Ejemplo: $0 unitree@192.168.1.100"
    exit 1
fi

REMOTE_WS="~/slam_ws"
REMOTE_PKG="${REMOTE_WS}/src/dron_control_sistema"
LOCAL_PKG="$(cd "$(dirname "$0")" && pwd)"

echo "==> Destino: ${REMOTE}:${REMOTE_PKG}"

# 1. Crear directorio destino si no existe
ssh "$REMOTE" "mkdir -p ${REMOTE_PKG}"

# 2. Sincronizar el paquete (excluye caché Python, build artefacts y datos pesados)
rsync -avz --progress \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '*.png' \
    --exclude '*.html' \
    --exclude 'demo_real/logs/*.csv' \
    "${LOCAL_PKG}/" \
    "${REMOTE}:${REMOTE_PKG}/"

echo ""
echo "==> Compilando en el PC remoto..."
ssh "$REMOTE" bash <<EOF
    set -e
    source /opt/ros/humble/setup.bash
    cd ${REMOTE_WS}
    colcon build --packages-select dron_control_sistema
    echo ""
    echo "✓ Paquete listo en ${REMOTE_WS}"
EOF

echo ""
echo "==> Despliegue completado."
echo ""
echo "Para ejecutar en el PC del LiDAR:"
echo "  Terminal 1: ros2 launch unitree_lidar_ros2 launch.py"
echo "  Terminal 2: ros2 launch point_lio mapping_unilidar_l2.launch.py rviz:=false"
echo "  Terminal 3: source ~/slam_ws/install/setup.bash && ros2 run dron_control_sistema lidar_bridge_node"
echo "  Terminal 4: source ~/slam_ws/install/setup.bash && ros2 run dron_control_sistema cerebro_node"
echo "  Terminal 5: source ~/slam_ws/install/setup.bash && ros2 run dron_control_sistema mavros_node"
