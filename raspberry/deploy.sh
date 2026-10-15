#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# deploy.sh  —  copia nuestros paquetes ROS 2 (carpeta ros2/ del repo)
#               al PC del LiDAR y los compila allí dentro de ~/slam_ws
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
LOCAL_ROS2="$(cd "$(dirname "$0")/../ros2" && pwd)"
# carpeta del repo -> carpeta en ~/slam_ws/src (dron_control mantiene el destino de antes)
declare -A PKGS=(
    [dron_control]=dron_control_sistema
    [dron_percepcion]=dron_percepcion
    [dron_gcs_bridge]=dron_gcs_bridge
    [dron_bringup]=dron_bringup
)

echo "==> Destino: ${REMOTE}:${REMOTE_WS}/src"

for DIR in "${!PKGS[@]}"; do
    REMOTE_PKG="${REMOTE_WS}/src/${PKGS[$DIR]}"

    # 1. Crear directorio destino si no existe
    ssh "$REMOTE" "mkdir -p ${REMOTE_PKG}"

    # 2. Sincronizar el paquete (excluye caché Python, build artefacts y datos pesados)
    rsync -avz --progress \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        --exclude '*.png' \
        --exclude '*.html' \
        --exclude 'demo_real/logs/*.csv' \
        "${LOCAL_ROS2}/${DIR}/" \
        "${REMOTE}:${REMOTE_PKG}/"
done

echo ""
echo "==> Compilando en el PC remoto..."
ssh "$REMOTE" bash <<EOF
    set -e
    source /opt/ros/humble/setup.bash
    cd ${REMOTE_WS}
    colcon build --packages-select dron_control_sistema dron_percepcion dron_gcs_bridge dron_bringup
    echo ""
    echo "✓ Paquetes listos en ${REMOTE_WS}"
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
