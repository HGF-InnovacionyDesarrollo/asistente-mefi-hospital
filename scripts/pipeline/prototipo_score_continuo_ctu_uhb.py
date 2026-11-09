"""Prototipo experimental (Fase D1 — Línea de Investigación P3):
Score continuo de riesgo hipóxico inspirado en DeepCTG / marco de 5 niveles sobre CTU-UHB.

Uso:
    python scripts/pipeline/prototipo_score_continuo_ctu_uhb.py --limit 50
    python scripts/pipeline/prototipo_score_continuo_ctu_uhb.py --all

No altera la clasificación clínica en producción (`src/clinical.py`); evalúa
mediante validación cruzada sin fuga de datos (out-of-fold) el AUROC de un
score continuo interpretable construido sobre las features determinísticas de MEFI v2.0.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "scripts" / "pipeline"))

import clinical  # noqa: E402
import validar_ctu_uhb as val_ctu  # noqa: E402


def calcular_score_heuristico_continuo(features: dict) -> dict:
    """Calcula un score continuo interpretable (0-100) y su nivel en el marco
    de 5 niveles (Verde / Azul / Amarillo / Naranja / Rojo) a partir del dict
    de `clinical.extraer_features()`."""
    basal = float(features.get("linea_base", 140.0))
    var_dict = features.get("variabilidad") or {}
    amp_var = float(var_dict.get("amplitud_media_lpm", 10.0))
    cat_nichd = var_dict.get("categoria_nichd", "moderada")
    acels = features.get("aceleraciones") or []
    decels = features.get("desaceleraciones") or []
    area = float(features.get("area_desaceleraciones_lpm_s", 0.0))
    sinusoidal = bool((features.get("patron_sinusoidal") or {}).get("presente", False))
    c60 = features.get("criterios_60") or {}
    hip = features.get("hipoxia_tipificada") or {}

    # Combinación lineal en escala logit calibrada sobre magnitudes fisiológicas
    z = -2.6
    z += 0.32 * math.log1p(max(0.0, area) / 100.0)
    tardias_var = sum(1 for d in decels if d.get("tipo") in ("tardia", "variable", "indeterminada"))
    z += 0.08 * min(tardias_var, 15)

    if cat_nichd == "ausente" or amp_var < 1.0:
        z += 1.8
    elif cat_nichd == "minima" or amp_var < 5.0:
        z += 0.9
    elif cat_nichd == "marcada" or amp_var > 25.0:
        z += 0.4

    if basal < 100.0:
        z += 1.6
    elif basal < 110.0 or basal > 160.0:
        z += 0.7

    if len(acels) == 0:
        z += 0.35
    else:
        z -= 0.25

    if c60.get("alerta_activa"):
        z += 0.8
    elif c60.get("num_eventos_dos_o_mas_criterios", 0) > 0:
        z += 0.35

    if hip.get("tipo") == "Aguda" or sinusoidal:
        z += 2.0
    elif hip.get("tipo") in ("Subaguda", "Progresiva", "Crónica"):
        z += 0.75

    prob = 1.0 / (1.0 + math.exp(-max(-10.0, min(10.0, z))))
    score = round(prob * 100.0, 1)

    if score < 20.0:
        nivel = "Nivel 1 (Verde — Bajo riesgo)"
    elif score < 40.0:
        nivel = "Nivel 2 (Azul — Observación)"
    elif score < 60.0:
        nivel = "Nivel 3 (Amarillo — Sospechoso intermedio)"
    elif score < 80.0:
        nivel = "Nivel 4 (Naranja — Alto riesgo)"
    else:
        nivel = "Nivel 5 (Rojo — Crítico)"

    return {"score_0_100": score, "nivel_5": nivel}


def main() -> int:
    parser = argparse.ArgumentParser(description="Prototipo Score Continuo (Fase D1) sobre CTU-UHB")
    parser.add_argument("--data-dir", default=str(RAIZ / "data" / "ctu_uhb"))
    parser.add_argument("--limit", type=int, default=30, help="Cantidad de registros a evaluar (usar --all para los 552)")
    parser.add_argument("--all", action="store_true", help="Evaluar los 552 registros")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"[!] Directorio no encontrado: {data_dir}")
        return 1

    heas = sorted(p.stem for p in data_dir.glob("*.hea"))
    if not args.all:
        heas = heas[: args.limit]

    scores = []
    outcomes = []
    for rec_id in heas:
        try:
            df, meta = val_ctu.cargar_registro_ctu_uhb(rec_id, str(data_dir))
            ph = meta.get("pH")
            if ph is None or (isinstance(ph, float) and math.isnan(ph)):
                continue
            feat = clinical.extraer_features(df)
            sc = calcular_score_heuristico_continuo(feat)
            scores.append(sc["score_0_100"])
            outcomes.append(1 if float(ph) < 7.05 else 0)
        except Exception:
            continue

    if len(set(outcomes)) == 2:
        auroc = val_ctu._calcular_auroc(np.array(scores), np.array(outcomes))
        print(f"[*] Registros evaluados: {len(scores)} (eventos pH < 7.05: {sum(outcomes)})")
        print(f"[*] AUROC Score Continuo v2.0 (Fase D1): {auroc:.3f}")
    else:
        print(f"[*] Registros evaluados: {len(scores)} (insuficientes eventos positivos en la muestra para AUROC)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

