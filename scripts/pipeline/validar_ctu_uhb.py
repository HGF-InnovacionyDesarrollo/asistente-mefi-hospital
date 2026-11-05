#!/usr/bin/env python3
"""
Validación de Fase 4: Carga registros de CTU-UHB (PhysioNet) y valida
la clasificación FIGO/NICE contra el outcome real (pH de cordón).

Uso:
    python scripts/pipeline/validar_ctu_uhb.py  [--record-id 1001] [--verbose]

La carpeta data/ctu_uhb/ debe contener archivos .hea y .dat del dataset.
Se puede descargar un registro así:

    mkdir -p data/ctu_uhb
    cd data/ctu_uhb
    curl -O https://physionet.org/files/ctu-uhb-ctgdb/1.0.0/1001.hea
    curl -O https://physionet.org/files/ctu-uhb-ctgdb/1.0.0/1001.dat
"""

import sys
import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import wfdb

# Importar la lógica clínica
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import clinical


def cargar_registro_ctu_uhb(record_id: int, data_dir: str = "data/ctu_uhb") -> dict:
    """Carga un registro .hea/.dat de CTU-UHB usando wfdb.

    Retorna:
        {
            "record": wfdb.Record,
            "fcf_data": np.array,
            "ua_data": np.array,
            "fs": int,  # frecuencia de muestreo
            "metadata": dict,  # atributos del registro (p.ej. outcome)
        }
    """
    data_path = Path(data_dir)
    record_path = data_path / str(record_id)

    print(f"[*] Cargando registro {record_id} desde {data_path}...")

    try:
        record = wfdb.rdrecord(str(record_path), physical=True)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Registro {record_path}.*  no encontrado.\n"
            f"Descargalo así:\n"
            f"  mkdir -p {data_path}\n"
            f"  curl -O https://physionet.org/files/ctu-uhb-ctgdb/1.0.0/{record_id}.hea -o {data_path}/{record_id}.hea\n"
            f"  curl -O https://physionet.org/files/ctu-uhb-ctgdb/1.0.0/{record_id}.dat -o {data_path}/{record_id}.dat"
        )

    print(f"  ✓ Registro cargado: {record.p_signal.shape[0]} muestras, {len(record.sig_name)} señales")
    print(f"  Señales: {', '.join(record.sig_name)}")
    print(f"  Fs: {record.fs} Hz")

    # Extraer FCF (Fetal Heart Rate) y UA (Uterine Activity)
    # En CTU-UHB: típicamente sig_name = ['FHR', 'UC']
    fcf_idx = None
    ua_idx = None
    for i, name in enumerate(record.sig_name):
        if "FHR" in name or "fhr" in name:
            fcf_idx = i
        if "UC" in name or "uc" in name or "contraction" in name.lower():
            ua_idx = i

    if fcf_idx is None:
        raise ValueError(f"No se encontró señal de FCF/FHR. Señales disponibles: {record.sig_name}")

    fcf_data = record.p_signal[:, fcf_idx]
    ua_data = record.p_signal[:, ua_idx] if ua_idx is not None else np.full_like(fcf_data, np.nan)

    # Metadata (outcome, atributos del sujeto, etc.)
    # Formato real de CTU-UHB en los comentarios del .hea: "pH           7.14"
    # (separado por espacios múltiples, no ":"). Las líneas de sección
    # ("-- Outcome measures") y placeholders ("!NotReadyYet!") se ignoran.
    metadata = {}
    if hasattr(record, "comments"):
        for comment in record.comments:
            comment = comment.strip()
            if not comment or comment.startswith("--") or "!NotReadyYet!" in comment:
                continue
            partes = re.split(r"\s{2,}", comment, maxsplit=1)
            if len(partes) == 2:
                key, val = partes
                metadata[key.strip()] = val.strip()

    return {
        "record": record,
        "fcf_data": fcf_data,
        "ua_data": ua_data,
        "fs": record.fs,
        "metadata": metadata,
    }


FCF_MIN_FISIOLOGICO = 50.0  # lpm — por debajo de esto es dropout del sensor Doppler, no señal real
FCF_MAX_FISIOLOGICO = 220.0


def convertir_a_dataframe(fcf_data: np.ndarray, ua_data: np.ndarray, fs: int) -> pd.DataFrame:
    """Convierte arrays de CTU-UHB a un DataFrame en el formato de digitizer.py
    (tiempo en segundos, FCF/UA en los valores físicos).

    Asume que CTU-UHB ya está en unidades físicas (lpm para FCF, %).

    CTU-UHB marca la pérdida de contacto del sensor Doppler con FCF=0 (no NaN) —
    en el registro 1001, ~22% de las muestras son ceros de dropout. Sin filtrarlos,
    inflan artificialmente la variabilidad calculada en clinical.py (un 0 dentro de
    una ventana de 1 minuto arruina el máximo-mínimo) y arrastran la clasificación
    FIGO hacia "sospechoso"/"patológico" incluso en registros con outcome normal
    (confirmado: especificidad 0% en el batch de los 552 registros antes de este fix).
    Se descartan como no confiables los valores fuera de rango fisiológico plausible,
    igual que digitizer.py hace con sus propios tramos de lectura dudosa.
    """
    n = len(fcf_data)
    tiempo = np.arange(n) / fs  # segundos

    fcf_valido = ~np.isnan(fcf_data) & (fcf_data >= FCF_MIN_FISIOLOGICO) & (fcf_data <= FCF_MAX_FISIOLOGICO)

    df = pd.DataFrame({
        "tiempo": tiempo,
        "fcf": fcf_data,
        "fcf_confiable": fcf_valido,
        "ua": ua_data,
        "ua_confiable": ~np.isnan(ua_data),
    })

    return df


def imprimir_features(features: dict, indent: int = 0) -> None:
    """Pretty-print de los features extraidos."""
    prefix = " " * indent

    print(f"{prefix}Línea base: {features['linea_base']} lpm")
    print(f"{prefix}Variabilidad: {features['variabilidad']['amplitud_media_lpm']} lpm ({features['variabilidad']['categoria']})")

    acels = features["aceleraciones"]
    print(f"{prefix}Aceleraciones: {len(acels)}")
    for i, accel in enumerate(acels[:3]):  # mostrar primeras 3
        print(
            f"{prefix}  [{i+1}] {accel['duracion_s']:.0f}s, "
            f"+{accel['amplitud_max_lpm']:.0f} lpm @ t={accel['inicio_s']:.0f}s"
        )
    if len(acels) > 3:
        print(f"{prefix}  ... y {len(acels) - 3} más")

    decels = features["desaceleraciones"]
    print(f"{prefix}Desaceleraciones: {len(decels)}")
    for i, decel in enumerate(decels[:3]):  # mostrar primeras 3
        tipo = decel.get("tipo", "?")
        duracion_label = ""
        if decel["muy_prolongada"]:
            duracion_label = " ⚠️ MUY PROLONGADA (>=5 min)"
        elif decel["prolongada"]:
            duracion_label = " ⚠️ PROLONGADA (>=3 min)"

        print(
            f"{prefix}  [{i+1}] {decel['duracion_s']:.0f}s ({tipo}), "
            f"-{decel['amplitud_max_lpm']:.0f} lpm{duracion_label}"
        )
    if len(decels) > 3:
        print(f"{prefix}  ... y {len(decels) - 3} más")

    sinusoidal = features["patron_sinusoidal"]
    if sinusoidal["presente"]:
        print(f"{prefix}Patrón sinusoidal: ✓ PRESENTE")
        print(f"{prefix}  Frecuencia dominante: {sinusoidal.get('frecuencia_dominante_cpm', '?'):.2f} cpm")
        print(f"{prefix}  Amplitud: {sinusoidal.get('amplitud_lpm', '?'):.1f} lpm")
    else:
        print(f"{prefix}Patrón sinusoidal: ✗ No presente ({sinusoidal.get('motivo', '?')})")

    figo = features["figo"]
    print(f"{prefix}Categoría FIGO: {figo['categoria']} {figo.get('semaforo_nice', '')}")
    if figo.get("razones"):
        for razon in figo["razones"]:
            print(f"{prefix}  - {razon}")


def validar_registro(record_id: int, data_dir: str = "data/ctu_uhb", verbose: bool = False) -> dict:
    """Corre el pipeline completo de validación."""
    print(f"\n{'='*70}")
    print(f"VALIDACIÓN REGISTRO {record_id} — Dataset CTU-UHB (PhysioNet)")
    print(f"{'='*70}\n")

    # 1. Cargar datos
    registro = cargar_registro_ctu_uhb(record_id, data_dir)
    metadata = registro["metadata"]

    # 2. Convertir a DataFrame
    print(f"\n[*] Convirtiendo a DataFrame...")
    df = convertir_a_dataframe(registro["fcf_data"], registro["ua_data"], registro["fs"])
    print(f"  ✓ {len(df)} muestras, duración: {df['tiempo'].max() / 60:.1f} minutos")
    print(f"  FCF: {df['fcf'].mean():.0f}±{df['fcf'].std():.0f} lpm (rango: {df['fcf'].min():.0f}-{df['fcf'].max():.0f})")
    if not np.isnan(df["ua"]).all():
        print(f"  UA: {df['ua'].mean():.1f}±{df['ua'].std():.1f} % (rango: {df['ua'].min():.1f}-{df['ua'].max():.1f})")

    # 3. Extraer features
    print(f"\n[*] Extrayendo features con lógica FIGO/NICE...")
    try:
        features = clinical.extraer_features(df)
        print(f"  ✓ Pipeline completado exitosamente")
    except Exception as e:
        print(f"  ✗ Error durante extracción: {e}")
        return {"success": False, "error": str(e)}

    # 4. Mostrar resultados
    print(f"\n[*] RESULTADOS:")
    print()
    imprimir_features(features, indent=2)

    # 5. Outcome real (si está disponible en metadata)
    print(f"\n[*] METADATA DEL REGISTRO:")
    if metadata:
        for key, val in sorted(metadata.items()):
            print(f"  {key}: {val}")
    else:
        print(f"  (sin metadata disponible en los comentarios)")

    # 6. Resumen de validación
    print(f"\n[*] RESUMEN:")
    figo_cat = features["figo"]["categoria"]
    nice_semaforo = features["figo"].get("semaforo_nice", "?")

    print(f"  Clasificación: FIGO {figo_cat} | NICE {nice_semaforo}")
    print(f"  Bases de la clasificación:")
    for razon in features["figo"].get("razones", []):
        print(f"    - {razon}")

    return {
        "success": True,
        "record_id": record_id,
        "features": features,
        "metadata": metadata,
        "dataframe_shape": df.shape,
        "duracion_minutos": df["tiempo"].max() / 60,
    }


PH_UMBRAL_HIPOXIA = 7.05  # pH de arteria umbilical por debajo de esto = hipoxia real


def listar_record_ids_locales(data_dir: str) -> list:
    """IDs de registros con .hea/.dat ya descargados en data_dir."""
    return sorted(p.stem for p in Path(data_dir).glob("*.hea"))


def validar_batch(data_dir: str = "data/ctu_uhb", verbose: bool = False) -> dict:
    """Corre validar_registro() sobre todos los registros descargados y compara
    la clasificación FIGO contra el outcome real (pH de cordón)."""
    record_ids = listar_record_ids_locales(data_dir)
    print(f"[*] {len(record_ids)} registro(s) encontrados en {data_dir}")

    resultados = []
    vp = fp = vn = fn = 0
    sin_ph = 0
    filas_métricas = []

    for record_id in record_ids:
        try:
            r = validar_registro(int(record_id), data_dir, verbose=False)
        except Exception as e:
            print(f"  ✗ {record_id}: error ({e})")
            continue

        if not r["success"]:
            continue

        resultados.append(r)

        ph_str = r["metadata"].get("pH")
        if ph_str is None:
            sin_ph += 1
            continue

        try:
            ph = float(ph_str)
        except ValueError:
            sin_ph += 1
            continue

        hipoxia_real = ph < PH_UMBRAL_HIPOXIA
        sospecha_figo = r["features"]["figo"]["categoria"] in ("II", "III")

        if sospecha_figo and hipoxia_real:
            vp += 1
        elif sospecha_figo and not hipoxia_real:
            fp += 1
        elif not sospecha_figo and not hipoxia_real:
            vn += 1
        else:
            fn += 1

        # Features continuos interpretables para el análisis AUROC (evaluación
        # del estado del arte 2026-10: sensibilidad/especificidad binarias no
        # alcanzan para comparar contra la literatura, que reporta AUC 0.68-0.75
        # sobre CTU-UHB para los mejores modelos).
        f = r["features"]
        decels_tv = [d for d in f["desaceleraciones"]
                     if d.get("tipo") in ("tardia", "variable", "indeterminada")]
        area_decels = float(sum(d["duracion_s"] * d["amplitud_max_lpm"] for d in decels_tv))
        area_acels = float(sum(a["duracion_s"] * a["amplitud_max_lpm"] for a in f["aceleraciones"]))
        filas_métricas.append({
            "ph": ph,
            "hipoxia": hipoxia_real,
            "n_decels_tv": len(decels_tv),
            "area_decels": area_decels,
            "area_acels": area_acels,
            "variabilidad_lpm": f["variabilidad"]["amplitud_media_lpm"],
            "basal": f["linea_base"],
            "n_contracciones": f.get("num_contracciones") or 0,
        })

    n_con_ph = vp + fp + vn + fn
    sensibilidad = vp / (vp + fn) if (vp + fn) else None
    especificidad = vn / (vn + fp) if (vn + fp) else None
    ppv = vp / (vp + fp) if (vp + fp) else None
    npv = vn / (vn + fn) if (vn + fn) else None
    bal_acc = ((sensibilidad or 0) + (especificidad or 0)) / 2

    print(f"\n{'='*70}")
    print(f"RESUMEN BATCH — {len(resultados)} registros procesados, {n_con_ph} con pH disponible, {sin_ph} sin pH")
    print(f"{'='*70}")
    print(f"Umbral hipoxia real: pH < {PH_UMBRAL_HIPOXIA}")
    print(f"Proxy de sospecha: FIGO categoría II o III")
    print(f"\nMatriz de confusión:")
    print(f"  Verdaderos positivos (FIGO sospecha + hipoxia real): {vp}")
    print(f"  Falsos positivos     (FIGO sospecha + pH normal):    {fp}")
    print(f"  Verdaderos negativos (FIGO normal + pH normal):      {vn}")
    print(f"  Falsos negativos     (FIGO normal + hipoxia real):   {fn}")
    if sensibilidad is not None:
        print(f"\nSensibilidad: {sensibilidad:.1%}")
    if especificidad is not None:
        print(f"Especificidad: {especificidad:.1%}")
    if ppv is not None:
        print(f"PPV: {ppv:.1%}  (prevalencia hipoxia: {(vp + fn)}/{n_con_ph} = {(vp + fn)/n_con_ph:.1%})")
    if npv is not None:
        print(f"NPV: {npv:.1%}")
    print(f"Exactitud balanceada: {bal_acc:.1%}")

    # --- AUROC de features continuos interpretables ---
    # El estado del arte (ver ESTADO_DELARTE_2026.md) compara modelos por AUC
    # sobre CTU-UHB: 0.68-0.75 para los métodos bien evaluados. Reportar AUC
    # de features individuales da el contexto honesto para la matriz binaria.
    if filas_métricas:
        try:
            from sklearn.metrics import roc_auc_score

            df_m = pd.DataFrame(filas_métricas)
            y = df_m["hipoxia"].astype(int)
            print(f"\nAUROC de features continuos (vs pH < {PH_UMBRAL_HIPOXIA}):")
            for col in ("n_decels_tv", "area_decels", "area_acels", "variabilidad_lpm", "basal", "n_contracciones"):
                try:
                    auc = roc_auc_score(y, df_m[col])
                    print(f"  {col}: {auc:.3f}")
                except Exception as e:
                    print(f"  {col}: no computable ({e})")
        except ImportError:
            print("\n(sklearn no disponible — AUROC omitido)")

    return {
        "n_registros": len(resultados),
        "n_con_ph": n_con_ph,
        "n_sin_ph": sin_ph,
        "vp": vp, "fp": fp, "vn": vn, "fn": fn,
        "sensibilidad": sensibilidad,
        "especificidad": especificidad,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-id", type=int, default=1001, help="ID del registro a validar (default: 1001)")
    parser.add_argument("--all", action="store_true", help="Validar todos los registros descargados en --data-dir y reportar sensibilidad/especificidad vs. pH real")
    parser.add_argument("--data-dir", default="data/ctu_uhb", help="Carpeta donde están los archivos .hea/.dat")
    parser.add_argument("--verbose", "-v", action="store_true", help="Mostrar detalles adicionales")
    parser.add_argument("--json", action="store_true", help="Salida en formato JSON")

    args = parser.parse_args()

    if args.all:
        try:
            validar_batch(args.data_dir, args.verbose)
            return 0
        except Exception as e:
            print(f"\n✗ ERROR: {e}\n", file=sys.stderr)
            if args.verbose:
                import traceback
                traceback.print_exc()
            return 1

    try:
        resultado = validar_registro(args.record_id, args.data_dir, args.verbose)

        if args.json:
            # Serializar features para JSON
            import json

            def default_json(obj):
                if isinstance(obj, np.integer):
                    return int(obj)
                if isinstance(obj, np.floating):
                    return float(obj)
                if isinstance(obj, np.ndarray):
                    return obj.tolist()
                return str(obj)

            print(f"\n{json.dumps(resultado, indent=2, default=default_json)}")

        print(f"\n{'='*70}")
        print(f"✓ VALIDACIÓN COMPLETADA")
        print(f"{'='*70}\n")

        return 0

    except Exception as e:
        print(f"\n✗ ERROR: {e}\n", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
