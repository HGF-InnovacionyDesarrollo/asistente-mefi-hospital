#!/usr/bin/env python3
"""Genera las figuras del documento ESTADO_DELARTE_2026.md.

Todos los valores salen de las fuentes citadas en el documento — nada se inventa.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

DOCS = Path(__file__).parent.parent / "docs"
DOCS.mkdir(exist_ok=True)

AZUL = "#2563eb"
GRIS = "#64748b"
NARANJA = "#ea580c"
VERDE = "#16a34a"

# --------------------------------------------------------------------------
# Figura 1: AUC sobre CTU-UHB por método (tabla 6 de DeepCTG 1.0 + CAP 2026
# + foundation model arXiv 2026-01 + feature propia)
# --------------------------------------------------------------------------
metodos = [
    "SVM disperso\n(Abry 2018)",
    "Reg. logística\n(Gatellier 2020)",
    "CNN\n(Ogasawara 2021)",
    "CNN\n(Fergus 2021)",
    "Reg. logística 4 feat.\n(DeepCTG® 1.0, 2023)",
    "LSTM\n(CAP-L, multicéntrico 2026)",
    "Transformer\n(foundation model, 2026)",
    "CNN\n(Petrozziello 2018)",
    "Área desaceleraciones\n(feature propia, este MVP)",
]
aucs = [0.72, 0.72, 0.73, 0.73, 0.74, 0.72, 0.72, 0.82, 0.71]
colores = [GRIS, GRIS, GRIS, GRIS, GRIS, GRIS, GRIS, "#b91c1c", AZUL]

fig, ax = plt.subplots(figsize=(10, 6))
barras = ax.barh(metodos, aucs, color=colores, height=0.6)
ax.axvspan(0.68, 0.75, color=VERDE, alpha=0.12)
ax.text(0.715, 8.35, "rango de métodos bien evaluados\nsobre CTU-UHB (0.68-0.75)",
        ha="center", fontsize=8.5, color=VERDE)
for b, v in zip(barras, aucs):
    ax.text(v + 0.004, b.get_y() + b.get_height() / 2, f"{v:.2f}", va="center", fontsize=9)
ax.axvline(0.5, color="k", lw=0.8, ls="--", alpha=0.4)
ax.set_xlim(0.4, 0.9)
ax.set_xlabel("AUC (área bajo la curva ROC), outcome pH de cordón, dataset CTU-UHB")
ax.set_title("Rendimiento reportado sobre CTU-UHB por método (2018-2026)\n"
             "El valor atípico de Petrozziello 2018 (0.82) no fue replicado por estudios posteriores", fontsize=10)
ax.invert_yaxis()
plt.tight_layout()
plt.savefig(DOCS / "fig_auroc_ctu_uhb.png", dpi=160)
plt.close()

# --------------------------------------------------------------------------
# Figura 2: mapa sensibilidad/especificidad de enfoques (incluido este MVP)
# --------------------------------------------------------------------------
puntos = [
    # (sens, spec, label, color, offset_xy)
    (95.0, 12.3, "MVP MEFI (antes de esta sesión)", NARANJA, (10, -14)),
    (95.0, 21.8, "FIGO computarizado\n(Ginekologia Polska 2022)", GRIS, (10, 4)),
    (62.0, 29.0, "Categoría I ACOG humana\n(Tomich 2023)", GRIS, (-10, 14)),
    (31.0, 78.0, "Categoría II ACOG humana\n(Tomich 2023)", GRIS, (-30, -28)),
    (45.0, 67.0, "Expertos sobre CTU-UHB\n(9 obstetras)", GRIS, (-30, -30)),
    (67.5, 64.3, "MVP + criterio FIGO real\n(diagnóstico, no adoptado)", "#b91c1c", (10, 6)),
    (45.0, 88.0, "DeepCTG® 1.0\n(sens 45% / FPR 12%)", GRIS, (-60, 12)),
]
fig, ax = plt.subplots(figsize=(8.5, 6.5))
for s, e, label, c, off in puntos:
    ax.scatter(e, s, s=90, color=c, zorder=3)
    ax.annotate(label, (e, s), textcoords="offset points", xytext=off, fontsize=8)
ax.set_xlabel("Especificidad (%)")
ax.set_ylabel("Sensibilidad (%)")
ax.set_xlim(0, 105)
ax.set_ylim(0, 105)
ax.grid(alpha=0.25)
ax.set_title("El trade-off fundamental sensibilidad-especificidad contra pH < 7.05:\n"
             "ningún método basado en CTG escapa del patrón alta-sens / baja-espec "
             "o viceversa", fontsize=10)
plt.tight_layout()
plt.savefig(DOCS / "fig_sens_spec_tradeoff.png", dpi=160)
plt.close()

print("Figuras guardadas en", DOCS)
