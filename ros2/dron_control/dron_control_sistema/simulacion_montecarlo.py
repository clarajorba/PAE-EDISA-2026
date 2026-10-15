"""
simulacion_montecarlo.py
Dos mejoras clave para que el simulado se parezca al teórico:
  1. CHECKPOINTS DENSOS: cada segmento se divide en puntos cada ~0.3 m
     → el dron corrige su error mucho más frecuentemente
  2. RUIDO REALISTA DE DRON REAL: σ_LiDAR=0.01 m, σ_Motor=0.005 m
     → refleja la precisión real de un LiDAR + controlador de vuelo
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import BoundaryNorm
from scipy.spatial import cKDTree
import json, pathlib

# ─────────────────────────────────────────────────────────────────────────────
# GEOMETRÍA
# ─────────────────────────────────────────────────────────────────────────────
SHELF_W = 3.0
SHELF_H = 4.0
Y_MID   = 2.0
GAP     = 2.0
Z_FIJO  = 1.0
E       = [i * (SHELF_W + GAP) for i in range(3)]

def waypoints_base(x0, nombre):
    x1, z = x0 + SHELF_W, Z_FIJO
    return [
        {"pos": [x0, 0.0,    z], "next": [x1, 0.0,    z], "msg": f"{nombre}: → row1"},
        {"pos": [x1, 0.0,    z], "next": [x1, Y_MID,  z], "msg": f"{nombre}: ↑ der"},
        {"pos": [x1, Y_MID,  z], "next": [x0, Y_MID,  z], "msg": f"{nombre}: ← row2"},
        {"pos": [x0, Y_MID,  z], "next": [x0, SHELF_H,z], "msg": f"{nombre}: ↑ izq"},
        {"pos": [x0, SHELF_H,z], "next": [x1, SHELF_H,z], "msg": f"{nombre}: → row3"},
        {"pos": [x1, SHELF_H,z], "next": [x0, 0.0,    z], "msg": f"{nombre}: ↙ vuelve inicio"},
    ]

mapa_base = (
    [{"pos": [0.0, 0.0, Z_FIJO], "next": [E[0], 0.0, Z_FIJO], "msg": "Inicio pasillo"}]
    + waypoints_base(E[0], "E1")
    + [{"pos": [E[0], 0.0, Z_FIJO], "next": [E[1], 0.0, Z_FIJO], "msg": "Tránsito E1→E2"}]
    + waypoints_base(E[1], "E2")
    + [{"pos": [E[1], 0.0, Z_FIJO], "next": [E[2], 0.0, Z_FIJO], "msg": "Tránsito E2→E3"}]
    + waypoints_base(E[2], "E3")
)

# ─────────────────────────────────────────────────────────────────────────────
# DENSIFICACIÓN DE CHECKPOINTS
# Cada segmento se divide en sub-puntos cada STEP metros.
# Efecto: el dron corrige el error cada ~0.3 m en lugar de cada 2-3 m
# ─────────────────────────────────────────────────────────────────────────────
CHECKPOINT_STEP = 0.30   # metros entre checkpoints consecutivos

def densificar(mapa_original, step=CHECKPOINT_STEP):
    denso = []
    for hito in mapa_original:
        pos    = np.array(hito["pos"][:3])
        nextpt = np.array(hito["next"][:3])
        dist   = np.linalg.norm(nextpt[:2] - pos[:2])

        if dist <= step:
            denso.append(hito)
            continue

        n = int(np.ceil(dist / step))          # número de sub-segmentos
        pts = [pos + (i/n)*(nextpt-pos) for i in range(n+1)]

        for j in range(n):
            denso.append({
                "pos":  pts[j].tolist(),
                "next": pts[j+1].tolist(),
                "msg":  hito["msg"] + (f" ·{j+1}/{n}" if n > 1 else "")
            })
    return denso

mapa = densificar(mapa_base)
N_WP = len(mapa)
print(f"Waypoints base: {len(mapa_base)}  →  Checkpoints densos: {N_WP}")

# Ruta teórica (usa sólo waypoints base para la línea limpia)
ruta_x = [mapa_base[0]["pos"][0]] + [h["next"][0] for h in mapa_base]
ruta_y = [mapa_base[0]["pos"][1]] + [h["next"][1] for h in mapa_base]

pathlib.Path("mision.json").write_text(
    json.dumps({"mapa_mision": mapa,
                "config": {"margen": 0.18, "z_fijo": Z_FIJO,
                           "checkpoint_step": CHECKPOINT_STEP}},
               indent=2, ensure_ascii=False)
)

# ─────────────────────────────────────────────────────────────────────────────
# PARÁMETROS DE RUIDO  (dron real de alta precisión)
#   σ_LiDAR = 0.01 m   → LiDAR de grado industrial (p. ej. Velodyne, Livox)
#   σ_Motor = 0.005 m  → controlador de vuelo (PX4/ArduPilot con RTK)
# ─────────────────────────────────────────────────────────────────────────────
NUM_SIMS        = 200
RUIDO_LIDAR_STD = 0.01     # 1 cm
RUIDO_MOTOR_STD = 0.005    # 5 mm
DISP_INICIAL    = 0.02     # 2 cm de dispersión en el despegue
DT              = 0.1
K_P             = 2.0      # controlador más agresivo → converge más rápido
MAX_ITER        = 400
MARGEN          = 0.18     # margen reducido acorde a checkpoints densos

# ─────────────────────────────────────────────────────────────────────────────
# SIMULACIÓN MONTECARLO
# ─────────────────────────────────────────────────────────────────────────────
trayectorias = []
errores_finales = []

for _ in range(NUM_SIMS):
    pos = np.array(mapa[0]["pos"], dtype=float)
    pos[:2] += np.random.normal(0, DISP_INICIAL, 2)
    tray = [pos.copy()]

    for hito in mapa:
        pos_hito = np.array(hito["pos"][:2])
        pos_next = np.array(hito["next"], dtype=float)

        for _ in range(MAX_ITER):
            perc = pos.copy()
            perc[:2] += np.random.normal(0, RUIDO_LIDAR_STD, 2)

            if np.linalg.norm(perc[:2] - pos_hito) <= MARGEN:
                break

            vel = np.clip(K_P * (pos_next - perc), -3.0, 3.0)
            ruido_mot = np.zeros(3)
            ruido_mot[:2] = np.random.normal(0, RUIDO_MOTOR_STD, 2)
            pos = pos + (vel + ruido_mot) * DT
            pos[2] = Z_FIJO
            tray.append(pos.copy())

    trayectorias.append(np.array(tray))
    fin_teorico = np.array(mapa[-1]["next"][:2])
    errores_finales.append(np.linalg.norm(pos[:2] - fin_teorico))

print(f"✓ {NUM_SIMS} simulaciones  |  error final: μ={np.mean(errores_finales):.4f} m  σ={np.std(errores_finales):.4f} m")

# ─────────────────────────────────────────────────────────────────────────────
# FIGURA 1 — ANÁLISIS ESTADÍSTICO
# ─────────────────────────────────────────────────────────────────────────────
fig1 = plt.figure(figsize=(20, 9))
fig1.patch.set_facecolor("#f8f8f5")

ax_tray = fig1.add_subplot(1, 3, (1, 2))
ax_hist = fig1.add_subplot(3, 3, 3)
ax_evol = fig1.add_subplot(3, 3, 6)
ax_info = fig1.add_subplot(3, 3, 9)

ax_tray.set_facecolor("#ffffff")

# Trayectorias MC
for tray in trayectorias:
    ax_tray.plot(tray[:, 0], tray[:, 1],
                 color="#3377bb", alpha=0.07, linewidth=0.6, zorder=2)

# Estanterías
for idx, xi in enumerate(E):
    ax_tray.add_patch(mpatches.FancyBboxPatch(
        (xi, 0), SHELF_W, SHELF_H, boxstyle="round,pad=0.05",
        linewidth=1.8, edgecolor="#8b6914", facecolor="#f5e8c8",
        alpha=0.45, zorder=1))
    ax_tray.plot([xi, xi+SHELF_W], [Y_MID, Y_MID],
                 color="#b08040", linewidth=0.9, linestyle=":", alpha=0.6)
    ax_tray.text(xi + SHELF_W/2, SHELF_H + 0.28, f"E{idx+1}",
                 ha="center", fontsize=11, fontweight="bold", color="#5a3800")

ax_tray.axhline(0, color="#aaa", linewidth=1.0, linestyle="--", alpha=0.5)

# Ruta teórica
ax_tray.plot(ruta_x, ruta_y, color="black", linewidth=3.0, zorder=6,
             solid_capstyle="round", solid_joinstyle="round")

# Flechas
for i in range(len(ruta_x)-1):
    dx, dy = ruta_x[i+1]-ruta_x[i], ruta_y[i+1]-ruta_y[i]
    if abs(dx)+abs(dy) < 0.01: continue
    ax_tray.annotate("",
                     xy=(ruta_x[i]+dx*0.62, ruta_y[i]+dy*0.62),
                     xytext=(ruta_x[i]+dx*0.38, ruta_y[i]+dy*0.38),
                     arrowprops=dict(arrowstyle="->", color="black", lw=1.8), zorder=7)

# Checkpoints densos (pequeños puntos grises)
cp_x = [h["pos"][0] for h in mapa]
cp_y = [h["pos"][1] for h in mapa]
ax_tray.scatter(cp_x, cp_y, s=6, color="#aaa", zorder=5, alpha=0.5,
                label=f"{N_WP} checkpoints (cada {CHECKPOINT_STEP} m)")

ax_tray.scatter(ruta_x[0],  ruta_y[0],  s=180, color="limegreen", marker="^",
                zorder=9, edgecolors="black", linewidths=1.2)
ax_tray.scatter(ruta_x[-1], ruta_y[-1], s=180, color="tomato",    marker="v",
                zorder=9, edgecolors="black", linewidths=1.2)

ax_tray.legend(handles=[
    plt.Line2D([0],[0], color="black", lw=3, label="Ruta teórica"),
    mpatches.Patch(color="#3377bb", alpha=0.5, label=f"{NUM_SIMS} trayectorias simuladas"),
    plt.Line2D([0],[0], marker=".", color="#aaa", lw=0, markersize=6,
               label=f"{N_WP} checkpoints (c/ {CHECKPOINT_STEP} m)"),
    plt.Line2D([0],[0], marker="^", color="w", markerfacecolor="limegreen",
               markersize=9, label="Inicio"),
    plt.Line2D([0],[0], marker="v", color="w", markerfacecolor="tomato",
               markersize=9, label="Fin"),
], fontsize=9, loc="upper left", framealpha=0.92)

ax_tray.set_xlim(-1.2, E[-1]+SHELF_W+1.0)
ax_tray.set_ylim(-0.7, SHELF_H+0.9)
ax_tray.set_xlabel("X — Pasillo (m)", fontsize=12)
ax_tray.set_ylabel("Y — Altura (m)",  fontsize=12)
ax_tray.set_aspect("equal")
ax_tray.set_title(
    f"Trayectorias Montecarlo — azul = recorrido simulado real  |  negro = ruta teórica\n"
    f"Checkpoints cada {CHECKPOINT_STEP} m  |  "
    f"σ_LiDAR={RUIDO_LIDAR_STD} m  |  σ_Motor={RUIDO_MOTOR_STD} m",
    fontsize=11)
ax_tray.grid(True, alpha=0.2)

# Histograma error final
mu_e, sig_e = np.mean(errores_finales), np.std(errores_finales)
ax_hist.set_facecolor("#ffffff")
ax_hist.hist(errores_finales, bins=28, color="#3377bb", edgecolor="white",
             linewidth=0.6, alpha=0.85, density=True)
ax_hist.axvline(mu_e, color="black", linewidth=2.0, label=f"μ={mu_e:.4f} m")
ax_hist.axvline(mu_e+sig_e, color="tomato", linewidth=1.5, linestyle="--",
                label=f"σ={sig_e:.4f} m")
ax_hist.axvline(mu_e-sig_e, color="tomato", linewidth=1.5, linestyle="--")
ax_hist.set_xlabel("Error posición final (m)", fontsize=9)
ax_hist.set_ylabel("Densidad", fontsize=9)
ax_hist.set_title("Error al llegar al Fin", fontsize=10)
ax_hist.legend(fontsize=7)
ax_hist.grid(True, alpha=0.3)

# Evolución del error a lo largo de la ruta
# Muestreamos el error en puntos equidistantes de la ruta teórica
n_muestras = 40
ruta_arr = np.column_stack([ruta_x, ruta_y])
ruta_dists = np.cumsum(np.r_[0, np.linalg.norm(np.diff(ruta_arr, axis=0), axis=1)])
ruta_total = ruta_dists[-1]
sample_dists = np.linspace(0, ruta_total * 0.98, n_muestras)

# Para cada simulación, interpolamos su posición más cercana a cada punto de muestra
errores_en_muestra = np.zeros((NUM_SIMS, n_muestras))
for k, tray in enumerate(trayectorias):
    tray_dists = np.cumsum(np.r_[0, np.linalg.norm(np.diff(tray[:, :2], axis=0), axis=1)])
    for m, sd in enumerate(sample_dists):
        # Encontrar el punto de la trayectoria más cercano en distancia recorrida
        idx_t = np.argmin(np.abs(tray_dists - sd))
        # Encontrar el punto teórico en esa distancia
        idx_r = np.searchsorted(ruta_dists, sd, side='right') - 1
        idx_r = np.clip(idx_r, 0, len(ruta_x)-2)
        t_frac = 0
        d_seg = ruta_dists[idx_r+1] - ruta_dists[idx_r]
        if d_seg > 0:
            t_frac = (sd - ruta_dists[idx_r]) / d_seg
        teorico = ruta_arr[idx_r] + t_frac * (ruta_arr[idx_r+1] - ruta_arr[idx_r])
        errores_en_muestra[k, m] = np.linalg.norm(tray[idx_t, :2] - teorico)

mean_err = errores_en_muestra.mean(axis=0)
std_err  = errores_en_muestra.std(axis=0)
p95_err  = np.percentile(errores_en_muestra, 95, axis=0)

ax_evol.set_facecolor("#ffffff")
ax_evol.fill_between(sample_dists, mean_err-std_err, mean_err+std_err,
                     alpha=0.25, color="#3377bb", label="±1σ")
ax_evol.fill_between(sample_dists, mean_err-2*std_err, mean_err+2*std_err,
                     alpha=0.10, color="#3377bb", label="±2σ")
ax_evol.plot(sample_dists, mean_err, color="#3377bb", linewidth=2.0, label="Error medio")
ax_evol.plot(sample_dists, p95_err,  color="tomato",  linewidth=1.3,
             linestyle="--", label="Percentil 95")
ax_evol.axhline(MARGEN, color="gray", linewidth=1.0, linestyle=":",
                label=f"Margen={MARGEN} m")
ax_evol.set_xlabel("Distancia recorrida (m)", fontsize=9)
ax_evol.set_ylabel("Error vs teórico (m)",    fontsize=9)
ax_evol.set_title("Error vs ruta teórica",    fontsize=10)
ax_evol.legend(fontsize=7)
ax_evol.grid(True, alpha=0.3)

# Tabla de parámetros
ax_info.set_facecolor("#ffffff")
ax_info.axis("off")
all_e = errores_en_muestra.ravel()
filas = [
    ["Parámetro",           "Valor"],
    ["Simulaciones",        f"{NUM_SIMS}"],
    ["Checkpoints",         f"{N_WP}  (c/{CHECKPOINT_STEP} m)"],
    ["σ LiDAR",             f"{RUIDO_LIDAR_STD*100:.0f} mm"],
    ["σ Motor",             f"{RUIDO_MOTOR_STD*1000:.0f} mm"],
    ["K_p controlador",     f"{K_P}"],
    ["Margen activación",   f"{MARGEN} m"],
    ["Error medio global",  f"{all_e.mean():.4f} m"],
    ["Error σ global",      f"{all_e.std():.4f} m"],
    ["Percentil 95",        f"{np.percentile(all_e,95):.4f} m"],
    ["Error final μ",       f"{mu_e:.4f} m"],
]
tbl = ax_info.table(cellText=filas[1:], colLabels=filas[0],
                    loc="center", cellLoc="center")
tbl.auto_set_font_size(False)
tbl.set_fontsize(8)
tbl.scale(1.0, 1.38)
for (r, c), cell in tbl.get_celld().items():
    cell.set_edgecolor("#cccccc")
    if r == 0:
        cell.set_facecolor("#3377bb")
        cell.set_text_props(color="white", fontweight="bold")
    elif r % 2 == 0:
        cell.set_facecolor("#eef3f8")
ax_info.set_title("Parámetros y resultados", fontsize=10, pad=6)

fig1.suptitle(
    f"Análisis Estadístico — {NUM_SIMS} simulaciones  |  "
    f"{N_WP} checkpoints cada {CHECKPOINT_STEP} m  |  "
    f"σ_LiDAR={RUIDO_LIDAR_STD} m  σ_Motor={RUIDO_MOTOR_STD} m",
    fontsize=13, fontweight="bold", y=1.01
)
plt.tight_layout()
plt.savefig("estadistica_mc.png", dpi=200, bbox_inches="tight")
print("✓ estadistica_mc.png")

# ─────────────────────────────────────────────────────────────────────────────
# FIGURA 2 — MAPA DE DECISIONES DEL CEREBRO
# ─────────────────────────────────────────────────────────────────────────────
fig2, ax_m = plt.subplots(figsize=(16, 10))
fig2.patch.set_facecolor("#f0f0ec")
ax_m.set_facecolor("#d8d8d4")

nx, ny = 600, 400
x_grid = np.linspace(-1.2, E[-1]+SHELF_W+1.2, nx)
y_grid = np.linspace(-0.7, SHELF_H+0.7, ny)
XX, YY = np.meshgrid(x_grid, y_grid)
grid_pts = np.column_stack([XX.ravel(), YY.ravel()])

wp_xy = np.array([h["pos"][:2] for h in mapa])
tree  = cKDTree(wp_xy)
dists, nearest_idx = tree.query(grid_pts)
nearest_idx = nearest_idx.reshape(XX.shape)
dists       = dists.reshape(XX.shape)

cmap_v = plt.colormaps.get_cmap("tab20b").resampled(N_WP)
norm_v = BoundaryNorm(np.arange(-0.5, N_WP+0.5, 1), N_WP)

ax_m.pcolormesh(XX, YY, nearest_idx.astype(float),
                cmap=cmap_v, norm=norm_v, alpha=0.30, zorder=1)
within = dists <= MARGEN
ax_m.pcolormesh(XX, YY,
                np.where(within, nearest_idx.astype(float), np.nan),
                cmap=cmap_v, norm=norm_v, alpha=0.88, zorder=2)

# Sólo dibujamos círculos de los waypoints base (no los intermedios) para no saturar
for hito in mapa_base:
    xw, yw = hito["pos"][:2]
    wp_idx = next(i for i, h in enumerate(mapa)
                  if abs(h["pos"][0]-xw)<1e-6 and abs(h["pos"][1]-yw)<1e-6)
    c = cmap_v(wp_idx / N_WP)
    ax_m.add_patch(plt.Circle((xw, yw), MARGEN, fill=False,
                               edgecolor=c, linewidth=2.0,
                               linestyle="--", zorder=5, alpha=1.0))
    xn, yn = hito["next"][:2]
    dx, dy = xn-xw, yn-yw
    nd = np.sqrt(dx**2+dy**2)
    if nd > 0.05:
        sc = min(0.4, nd*0.22)
        ax_m.annotate("",
                      xy=(xw+dx/nd*sc*1.7, yw+dy/nd*sc*1.7),
                      xytext=(xw, yw),
                      arrowprops=dict(arrowstyle="->", color="black",
                                      lw=1.3, alpha=0.65), zorder=6)
    ax_m.scatter(xw, yw, s=100, color="white",
                 edgecolors="black", linewidths=1.6, zorder=7)

for idx, xi in enumerate(E):
    ax_m.add_patch(mpatches.FancyBboxPatch(
        (xi, 0), SHELF_W, SHELF_H, boxstyle="round,pad=0.05",
        linewidth=2.2, edgecolor="#5a3800", facecolor="none", zorder=9))
    ax_m.text(xi + SHELF_W/2, SHELF_H + 0.35, f"Estantería {idx+1}",
              ha="center", fontsize=12, fontweight="bold", color="#3a2000")

ax_m.plot(ruta_x, ruta_y, "k-", linewidth=2.5, zorder=10, label="Ruta teórica")
ax_m.scatter(ruta_x[0],  ruta_y[0],  s=200, color="limegreen", marker="^",
             zorder=11, label="Inicio", edgecolors="black", linewidths=1.5)
ax_m.scatter(ruta_x[-1], ruta_y[-1], s=200, color="tomato",    marker="v",
             zorder=11, label="Fin",   edgecolors="black", linewidths=1.5)

sm = plt.cm.ScalarMappable(cmap=cmap_v, norm=norm_v)
sm.set_array([])
cbar = fig2.colorbar(sm, ax=ax_m, fraction=0.022, pad=0.02)
cbar.set_label(f"Checkpoint activo (total: {N_WP} cada {CHECKPOINT_STEP} m)", fontsize=10)
cbar.set_ticks([0, N_WP//4, N_WP//2, 3*N_WP//4, N_WP-1])
cbar.set_ticklabels(["Inicio", "25%", "50%", "75%", "Fin"], fontsize=9)

ax_m.set_xlim(-1.3, E[-1]+SHELF_W+1.3)
ax_m.set_ylim(-0.8, SHELF_H+1.1)
ax_m.set_xlabel("X — Pasillo (m)", fontsize=12)
ax_m.set_ylabel("Y — Altura (m)",  fontsize=12)
ax_m.set_title(
    "Mapa de Decisiones del Cerebro\n"
    "Cada color = checkpoint más cercano → destino asignado por el Cerebro\n"
    f"Círculos = radio de activación ({MARGEN} m)  |  "
    f"{N_WP} checkpoints cada {CHECKPOINT_STEP} m",
    fontsize=11)
ax_m.axhline(0, color="#888", linewidth=0.9, linestyle="--", alpha=0.4)
ax_m.set_aspect("equal")
ax_m.legend(fontsize=10, loc="upper left")
ax_m.grid(True, alpha=0.15)

plt.tight_layout()
plt.savefig("mapa_decision.png", dpi=200, bbox_inches="tight")
print("✓ mapa_decision.png")
plt.show()
