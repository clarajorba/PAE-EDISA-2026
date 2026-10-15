# Estado — LiDAR / SLAM / Raspberry Pi
Última actualización: 15/10/2026

## Hecho
- Point-LIO del repo (modificado, a9f0879) publica `/slam/odom`; el original publica
  `/aft_mapped_to_init`. Nadie publica `/Odometry`: listeners corregidos en 7bfe4b0
  (parámetro `odom_topic`).
- Alimentación del L2 revisada: PDB con dos MP1584EN (12V fijo y ADJ). El L2 va a la clema
  azul (salida ADJ), medidos 12 V sin carga. Aguanta 3 A; el L2 pide ~0,83 A (pico 1,1 A).
- Conector del L2: jack DC 3.5×1.35 = alimentación; GH1.25 4 pines + adaptador USB-C =
  solo datos serie (no se usa). Usamos Ethernet: L2 192.168.1.62 → Pi 192.168.1.2.

## Pendiente (en orden)
1. Inventario de la Pi (solo lectura): SO, ROS 2, `~/slam_ws`, versión de Point-LIO,
   MAVROS, servicios, espacio. IP en EDISA: 172.25.1.104 (VNC). Usuario: ¿`pi` o `raspi5`?
2. Conectar el L2 y comprobar `/unilidar/cloud` e `/unilidar/imu`.
3. Compilar Point-LIO del repo en la Pi y comprobar `/slam/odom`.
4. Grabar rosbags delante de una estantería.
5. Extrínseca LiDAR → base_link y documentar marcos.

## Abierto / dudas
- Fijar el potenciómetro ADJ (laca/pegamento) o pasar a la salida fija de 12V.
  Medir tensión con el L2 funcionando.
- La Pi no estaba encendida el 15/10; conectividad 172.25.5.x ↔ 172.25.1.x sin probar.
