# Contexto del Proyecto: Dron Control Sistema (ROS 2)

## 🎯 Objetivo
Simulación de un dron en un entorno de almacén (pasillo) que debe realizar un escaneo de 3 estanterías siguiendo un patrón específico de "Z" triple.

## 🛠️ Arquitectura Técnica
- **Sistema:** ROS 2 Humble.
- **Entorno:** Contenedor Docker (`osrf/ros:humble-desktop`).
- **Nodos principales:**
  - `cerebro_node.py`: Lógica de misión y decisión de hitos.
  - `simulador_dron.py`: Simulación física y visualización.
  - `simulacion_montecarlo.py`: Pruebas de estrés con ruido y aleatoriedad.
- **Visualización:** Plotly (HTML interactivo) y Matplotlib (PNG).

## 📐 Especificación del Patrón de Movimiento (Triple Z)
El dron debe moverse en el plano X-Y (Z constante = 1.0) siguiendo esta secuencia por cada estantería:
1. **Punto Inicio (Arriba-Izq):** `[0, 3]`
2. **Tramo Superior:** Horizontal hasta `[3, 3]` (Arriba-Der).
3. **Tramo Diagonal:** Cruce hasta `[0, 0]` (Abajo-Izq).
4. **Tramo Inferior:** Horizontal hasta `[3, 0]` (Abajo-Der).
5. **Conector:** Salto a la siguiente estantería (desplazamiento en X).

## ⚠️ Variables de Error (Simulación Montecarlo)
Para el análisis de riesgo, usamos:
- `RUIDO_LIDAR_STD`: Error en la posición que el dron *cree* tener (percepción).
- `RUIDO_MOVIMIENTO_STD`: Micro-variaciones aleatorias en la ejecución del motor (fuerzas físicas).
- `MARGEN`: Tolerancia de cercanía para dar un hito por alcanzado.

## 📂 Archivos Clave
- `mision.json`: Definición de waypoints.
- `simulacion_interactiva.py`: Script para generar el HTML con Plotly.
