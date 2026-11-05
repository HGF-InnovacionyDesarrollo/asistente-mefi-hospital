#!/usr/bin/env python3
"""Prototipo: detector de contracciones UA mejorado (v2) vs detector actual (v1).

Validación sobre CTU-UHB sin tocar clinical.py todavía:
- plausibilidad del conteo (contracciones/10 min dentro de rangos fisiológicos),
- impacto en el criterio FIGO real (>50% de contracciones asociadas),
- sensibilidad/especificidad resultante.

Uso:
    python scripts/analisis/prototipo_contracciones.py [--data-dir data/ctu_uhb]
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import clinical  # noqa: E402
from validar_ctu_uhb import (  # noqa: E402
    PH_UMBRAL_HIPOXIA,
    cargar_registro_ctu_uhb,
    convertir_a_dataframe,
    listar_record_ids_locales,
)

# El detector v2 ya vive en clinical.detectar_contracciones(); este script
# solo lo evalúa contra CTU-UHB y contra el criterio real de FIGO (>50%).
detectar_contracciones_v2 = clinical.detectar_contracciones


def _desaceleraciones_asociadas(decels: list[dict], picos_ua: list[float],
                                ventana_s: float = 90.0) -> int:
    """Cuenta desaceleraciones tardías/variables/indeterminadas cuyo nadir cae
    dentro de ±ventana_s de un pico de contracción."""
    n = 0
    for d in decels:
        if d.get("tipo") not in ("tardia", "variable", "indeterminada"):
            continue
        t_nadir = d["inicio_s"] + (d["fin_s"] - d["inicio_s"]) * 0.0  # conservador: usar inicio
        # mejor: nadir aproximado al punto medio si no tenemos el exacto; los eventos de
        # clinical.py no guardan t_nadir, así que se aproxima con el momento de mayor
        # profundidad no disponible — se usa el centro del evento, suficiente para ±90s
        t_ref = (d["inicio_s"] + d["fin_s"]) / 2.0
        if picos_ua and min(abs(p - t_ref) for p in picos_ua) <= ventana_s:
            n += 1
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/ctu_uhb")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    record_ids = listar_record_ids_locales(args.data_dir)

    filas = []
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

        duracion_min = df["tiempo"].max() / 60.0
        picos_v1 = clinical._picos_contraccion(df)
        picos_v2 = detectar_contracciones_v2(df)

        decels_tv = [d for d in features["desaceleraciones"]
                     if d.get("tipo") in ("tardia", "variable", "indeterminada")]

        # Criterio FIGO real: desaceleraciones asociadas a >50% de las contracciones
        asoc_v1 = _desaceleraciones_asociadas(decels_tv, picos_v1)
        asoc_v2 = _desaceleraciones_asociadas(decels_tv, picos_v2)
        figo_real_v1 = (len(picos_v1) > 0 and asoc_v1 > 0.5 * len(picos_v1) and asoc_v1 >= 2)
        figo_real_v2 = (len(picos_v2) > 0 and asoc_v2 > 0.5 * len(picos_v2) and asoc_v2 >= 2)

        filas.append({
            "record": record_id,
            "ph": ph,
            "hipoxia": ph < PH_UMBRAL_HIPOXIA,
            "duracion_min": duracion_min,
            "n_v1": len(picos_v1),
            "n_v2": len(picos_v2),
            "v2_por_10min": len(picos_v2) / (duracion_min / 10.0) if duracion_min > 0 else np.nan,
            "n_decels_tv": len(decels_tv),
            "asoc_v1": asoc_v1,
            "asoc_v2": asoc_v2,
            "figo_actual": features["figo"]["categoria"],
            "repetitivas_proxy": clinical._hay_desaceleraciones_repetitivas(decels_tv),
            "figo_real_v1": figo_real_v1,
            "figo_real_v2": figo_real_v2,
        })

    df_out = pd.DataFrame(filas)
    hipoxia = df_out["hipoxia"]

    print("\n=== Plausibilidad del conteo de contracciones (CTU-UHB, ~80 min/registro) ===")
    print(f"v1 (actual):  mediana {df_out['n_v1'].median():.0f} contracciones/registro "
          f"({df_out['n_v1'].median() / (df_out['duracion_min'].median() / 10):.1f}/10 min)")
    print(f"v2 (nuevo):   mediana {df_out['n_v2'].median():.0f} contracciones/registro "
          f"({df_out['n_v2'].median() / (df_out['duracion_min'].median() / 10):.1f}/10 min)")
    print(f"v2 por registro — p5/p25/p50/p75/p95: "
          f"{df_out['n_v2'].quantile([.05, .25, .5, .75, .95]).round(0).tolist()}")
    print(f"v2 registros sin contracciones detectadas: {(df_out['n_v2'] == 0).sum()}")
    print(f"v2 registros con >=5 contracciones/10min (tachisistolia NICE): "
          f"{(df_out['v2_por_10min'] >= 5).sum()}")

    print("\n=== Asociación desaceleración-contracción ===")
    print(f"v1: mediana {df_out['asoc_v1'].median():.0f} desacels asociadas de {df_out['n_decels_tv'].median():.0f}")
    print(f"v2: mediana {df_out['asoc_v2'].median():.0f} desacels asociadas de {df_out['n_decels_tv'].median():.0f}")

    def metricas(mask_sospecha, nombre):
        vp = int((mask_sospecha & hipoxia).sum())
        fp = int((mask_sospecha & ~hipoxia).sum())
        vn = int((~mask_sospecha & ~hipoxia).sum())
        fn = int((~mask_sospecha & hipoxia).sum())
        sens = vp / (vp + fn) if vp + fn else float("nan")
        spec = vn / (vn + fp) if vn + fp else float("nan")
        print(f"{nombre}: VP={vp} FP={fp} VN={vn} FN={fn} → sens={sens:.1%} spec={spec:.1%}")
        return sens, spec

    print("\n=== Clasificación: sensibilidad/especificidad (vs pH<7.05) ===")
    sospecha_actual = df_out["figo_actual"].isin(["II", "III"])
    metricas(sospecha_actual, "Actual (proxy 3+/20min, clasificador completo)")
    metricas(df_out["repetitivas_proxy"], "Solo proxy repetitivas (diagnóstico)")
    metricas(df_out["figo_real_v1"], "FIGO real >50% con detector v1 (diagnóstico)")
    metricas(df_out["figo_real_v2"], "FIGO real >50% con detector v2 (diagnóstico)")

    # Matiz: ¿qué pasa si solo se cambia el criterio de "repetitivas" dentro del
    # clasificador completo? (las demás variables siguen clasificando igual)
    print("\n=== Clasificador completo con criterio real v2 en vez de proxy ===")
    es_I_actual = df_out["figo_actual"] == "I"
    sospecha_real_v2 = (~es_I_actual) | df_out["figo_real_v2"] & False  # placeholder no usado
    # Reconstrucción correcta: Categoría I exige además no-repetitivas; II/III se quedan.
    # Caso A: si es II SOLO por repetitivas y con v2 no es repetitiva → baja a I.
    df_out["baja_a_I"] = (
        (df_out["figo_actual"] == "II")
        & (~df_out["repetitivas_proxy"] | ~df_out["figo_real_v2"])
        & (df_out["repetitivas_proxy"])  # solo aplica a las que el proxy marcó
    )
    # Caso más limpio: reemplazar repetitivas_proxy por figo_real_v2 en la regla de Categoría I
    df_out["figo_hibrido"] = df_out["figo_actual"]
    df_out.loc[(df_out["figo_actual"] == "II") & df_out["repetitivas_proxy"] & ~df_out["figo_real_v2"], "figo_hibrido"] = "I"
    metricas(df_out["figo_hibrido"].isin(["II", "III"]), "Híbrido (v2 real en vez de proxy, resto igual)")

    df_out.to_csv("data/extracted/prototipo_contracciones.csv", index=False)
    print("\nDetalle en data/extracted/prototipo_contracciones.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
