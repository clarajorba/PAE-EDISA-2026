# sim/

Simulación del dron.

| Qué | Dónde |
|---|---|
| Montar PX4 SITL + Gazebo + MAVROS + QGroundControl | [`docs/setup/SETUP_SIMULADOR.md`](../docs/setup/SETUP_SIMULADOR.md) |
| Simulador de juguete (`simulador_dron`) y Monte Carlo (`simulacion_montecarlo.py`, genera `mision.json`) | `ros2/dron_control/dron_control_sistema/` (siguen dentro del paquete porque `cerebro_node` lee `mision.json` de ahí) |
| Gráficos e HTML de la simulación Monte Carlo del curso pasado | [`resultados/`](resultados/) |

Aquí irán los mundos de Gazebo y los scripts para arrancar la simulación PX4.
