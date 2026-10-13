#!/usr/bin/env python3
"""Análisis de errores del batch CTU-UHB: qué criterio dispara cada falso positivo
y cada falso negativo, y estado de las variables por grupo.

Uso:
    python scripts/analizar_falsos_positivos.py [--data-dir data/ctu_uhb]

Salida: conteo de drivers de FP/FN y CSV opcional con detalle por registro.
No modifica la clasificación — solo diagnostica.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import clinical  # noqa: E402
from validar_ctu_uhb import (  # noqa: E402
    PH_UMBRAL_HIPOXIA,
    cargar_registro_ctu_uhb,
    convertir_a_dataframe,
    listar_record_ids_locales,
)


def _drivers_figo(features: dict) -> list[str]:
    """Replica las razones de clasificar_figo() como labels contables."""
    razones = features["figo"]["razones"]
    drivers = []
    texto = " ".join(razones).lower()
    if "repetitiva" in texto:
        drivers.append("desaceleraciones_repetitivas")
    if "desaceleración(es) tardía(s)/variable(s)" in texto:
        drivers.append("desaceleraciones_no_repetitivas")
    if "línea base fuera de rango" in texto:
        drivers.append("linea_base_fuera_rango")
    if "variabilidad" in texto and ("aumentada" in texto or "reducida" in texto):
        drivers.append("variabilidad_anormal")
    if "sinusoidal" in texto:
        drivers.append("patron_sinusoidal")
    if "prolongada" in texto:
        drivers.append("desacel_muy_prolongada")
    if "contracciones elevada" in texto:
        drivers.append("tachisistolia")
    if not drivers and features["figo"]["categoria"] != "I":
        drivers.append("otro")
    return drivers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/ctu_uhb")
    parser.add_argument("--csv-out", default=None, help="Guardar detalle por registro en un CSV")
    args = parser.parse_args()

    record_ids = listar_record_ids_locales(args.data_dir)
    print(f"[*] {len(record_ids)} registro(s) en {args.data_dir}")

    filas = []
    conteo = {"FP": Counter(), "FN": Counter(), "VP": Counter(), "VN": Counter()}

    for record_id in record_ids:
        try:
            registro = cargar_registro_ctu_uhb(int(record_id), args.data_dir)
        except Exception:
            continue
        df = convertir_a_dataframe(registro["fcf_data"], registro["ua_data"], registro["fs"])
        try:
            features = clinical.extraer_features(df)
        except Exception as e:
            print(f"  ✗ {record_id}: {e}")
            continue

        ph_str = registro["metadata"].get("pH")
        try:
            ph = float(ph_str)
        except (TypeError, ValueError):
            continue

        hipoxia = ph < PH_UMBRAL_HIPOXIA
        sospecha = features["figo"]["categoria"] in ("II", "III")
        grupo = "VP" if (sospecha and hipoxia) else "FP" if sospecha else "FN" if hipoxia else "VN"

        drivers = _drivers_figo(features)
        for d in drivers:
            conteo[grupo][d] += 1

        filas.append({
            "record": record_id,
            "grupo": grupo,
            "ph": ph,
            "figo": features["figo"]["categoria"],
            "linea_base": features["linea_base"],
            "variabilidad_cat": features["variabilidad"]["categoria"],
            "variabilidad_lpm": features["variabilidad"]["amplitud_media_lpm"],
            "n_aceleraciones": len(features["aceleraciones"]),
            "n_desaceleraciones": len(features["desaceleraciones"]),
            "n_contracciones": features.get("num_contracciones"),
            "sinusoidal": features["patron_sinusoidal"]["presente"],
            "drivers": "|".join(drivers),
        })

    print("\n=== Drivers por grupo (un registro puede tener varios drivers) ===")
    for grupo in ("VP", "FP", "VN", "FN"):
        total = sum(1 for f in filas if f["grupo"] == grupo)
        print(f"\n{grupo} (n={total}):")
        for driver, n in conteo[grupo].most_common():
            print(f"  {driver}: {n}")

    df_out = pd.DataFrame(filas)
    print("\n=== Variabilidad y línea base por grupo ===")
    print(df_out.groupby("grupo")[["variabilidad_lpm", "linea_base", "n_desaceleraciones", "n_contracciones"]]
          .agg(["median", "mean"]).round(1))

    if args.csv_out:
        df_out.to_csv(args.csv_out, index=False)
        print(f"\nDetalle guardado en {args.csv_out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
