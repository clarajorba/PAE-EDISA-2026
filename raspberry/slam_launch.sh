#!/usr/bin/env bash
# slam_launch.sh — replicates the 3-terminal manual startup sequence:
#   1. Configure eth1 for LiDAR (Pi: 192.168.1.2/24, LiDAR: 192.168.1.62)
#   2. Start unitree_lidar_ros2 driver and wait until it publishes
#   3. Start Point-LIO (mapping_unilidar_l2, no RViz)
#
# Called by gcs_control.py when the SLAM button is pressed in the dashboard.

source /opt/ros/jazzy/setup.bash
source ~/slam_ws/install/setup.bash

# ── 1. Ethernet interface for LiDAR ──────────────────────────────────────────
echo "[slam] Configuring eth0 for LiDAR (192.168.1.2/24)..."

# Check if sudo ip works without password (visudo must be configured)
if ! sudo -n ip addr show eth0 >/dev/null 2>&1; then
    echo "[slam] WARNING: sudo ip requires password — visudo not configured!"
    echo "[slam] Run: sudo visudo  and add:"
    echo "[slam]   raspi5 ALL=(ALL) NOPASSWD: /sbin/ip"
    echo "[slam] Continuing anyway, eth0 may not be configured..."
else
    sudo ip addr flush dev eth0              2>/dev/null || true
    sudo ip addr add 192.168.1.2/24 dev eth0 2>/dev/null || true
    sudo ip link set eth0 up                 2>/dev/null || true
    echo "[slam] eth0 configured ✓  $(ip addr show eth0 2>/dev/null | grep 'inet ' || echo 'no IP assigned')"
fi

# Non-fatal ping check — just informative
if ping -c 2 -W 1 192.168.1.62 >/dev/null 2>&1; then
    echo "[slam] LiDAR reachable at 192.168.1.62 ✓"
else
    echo "[slam] WARNING: LiDAR not responding to ping at 192.168.1.62"
    echo "[slam]   - Check eth0 is physically connected to LiDAR"
    echo "[slam]   - Check LiDAR is powered on"
    echo "[slam] Continuing anyway..."
fi

# ── 2. LiDAR driver ───────────────────────────────────────────────────────────
echo "[slam] Starting unitree_lidar_ros2 driver..."
ros2 launch unitree_lidar_ros2 launch.py &
LIDAR_PID=$!
echo "[slam] LiDAR driver PID=$LIDAR_PID"

# Wait up to 40 s for LiDAR to start publishing
echo "[slam] Waiting for LiDAR topics (up to 40s)..."
for i in $(seq 1 40); do
    if ros2 topic list 2>/dev/null | grep -q "unilidar"; then
        echo "[slam] LiDAR topics active after ${i}s ✓"
        break
    fi
    if [ $i -eq 40 ]; then
        echo "[slam] WARNING: LiDAR topics not found after 40s — starting SLAM anyway"
    fi
    sleep 1
done

# Extra settle time before SLAM (match manual 3-terminal timing)
echo "[slam] Waiting 3s for LiDAR to stabilise..."
sleep 3

# ── 3. Point-LIO ──────────────────────────────────────────────────────────────
echo "[slam] Starting Point-LIO..."
ros2 launch point_lio mapping_unilidar_l2.launch.py rviz:=false &
SLAM_PID=$!
echo "[slam] Point-LIO PID=$SLAM_PID"

# ── Cleanup on exit / SIGTERM (sent by gcs_control.py Stop button) ────────────
trap "echo '[slam] Stopping SLAM and LiDAR...'; kill $LIDAR_PID $SLAM_PID 2>/dev/null; wait" EXIT INT TERM

wait $SLAM_PID
