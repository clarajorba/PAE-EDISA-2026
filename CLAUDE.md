# PAE-EDISA 2026 — instrucciones para Claude Code

Dron autónomo de inventario en interiores (EDISA × UPC). Demo: 29/01/2027.
Equipo: Alex (Alejandro Jové, LiDAR/SLAM/Pi + vuelo) y Marc Elvira (visión).

## Antes de empezar
1. `git pull` (Marc y otros chats trabajan en la misma rama).
2. Lee el archivo de estado de tu área (abajo) y `README.md` para la estructura del repo.

## Reparto de chats y archivos de estado
Cada chat actualiza SOLO su archivo de estado al acabar una sesión
(hecho / pendiente / problemas abiertos, con fecha). No edites el de otro chat.

| Chat | Ámbito | Estado |
|---|---|---|
| SLAM | LiDAR Unitree L2, Point-LIO, Raspberry Pi | [docs/estado/ESTADO_SLAM.md](docs/estado/ESTADO_SLAM.md) |
| Vuelo | Pixhawk, PX4, MAVROS, simulador, `ros2/dron_control/` | [docs/estado/ESTADO_VUELO.md](docs/estado/ESTADO_VUELO.md) |

Frontera SLAM ↔ vuelo: el chat SLAM entrega la odometría (topic, frecuencia,
marcos, extrínseca LiDAR→base_link); el chat de vuelo la convierte para PX4/EKF2.
No toques código del otro ámbito sin preguntar.

## Cómo trabajar con Alex
- En español, lenguaje sencillo. Un paso cada vez: explica qué y por qué,
  comprueba con un comando y espera su "ok".
- `sudo` o instalaciones grandes: explica qué hacen y cuánto ocupan; él los lanza.
- No modifiques código sin explicar antes el cambio.
- Si algo no cuadra entre repo, documentos y sistema, avisa en vez de suponer.
  Versiones de software: documentación oficial actual.
- `ros2 topic ...` con `timeout -s INT`, no `timeout` a secas.
- Sistema en catalán (Xubuntu 24.04): los mensajes de apt/git salen en catalán.

## Git
- Rama `feature/AiM`. `main` no se toca.
- Commits solo cuando Alex lo pida. El push lo hace él.

## Documentos de referencia
- `docs/estado/INVENTARIO.md`: revisión del código.
- `docs/estado/REORGANIZACION.md`: rutas antiguas (WP2/WP3/src) → actuales.
- `docs/estado/CONTEXTO_PROYECTO.md`: DESACTUALIZADO (Humble/Docker), no fiarse.
