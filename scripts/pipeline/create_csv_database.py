#!/usr/bin/env python3
"""Convierte todos los registros CTU-UHB descargados en data/ctu_uhb/ a un
formato tabular reutilizable:

- data/extracted/ctu_uhb/{record_id}.csv — una serie de tiempo por registro,
  en el formato espejo (tiempo, fcf, fcf_confiable, ua, ua_confiable) que
  también produce src/digitizer.py.
- data/extracted/ctu_uhb_outcomes.csv — una fila por registro con las
  variables clínicas de outcome (pH, Apgar, etc.), separadas de las series
  de tiempo.

Uso:
    python scripts/pipeline/create_csv_database.py
    python scripts/pipeline/create_csv_database.py --data-dir data/ctu_uhb --out-dir data/extracted/ctu_uhb
"""

import argparse
import csv
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
from validar_ctu_uhb import cargar_registro_ctu_uhb, convertir_a_dataframe, listar_record_ids_locales


def construir_database(data_dir: str = "data/ctu_uhb", out_dir: str = "data/extracted/ctu_uhb",
                        outcomes_path: str = "data/extracted/ctu_uhb_outcomes.csv") -> None:
    record_ids = listar_record_ids_locales(data_dir)
    print(f"[*] {len(record_ids)} registro(s) encontrados en {data_dir}")

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(outcomes_path).parent.mkdir(parents=True, exist_ok=True)

    filas_outcomes = []
    todas_las_keys = set()

    for record_id in record_ids:
        try:
            registro = cargar_registro_ctu_uhb(int(record_id), data_dir)
        except Exception as e:
            print(f"  ✗ {record_id}: error al cargar ({e})")
            continue

        df = convertir_a_dataframe(registro["fcf_data"], registro["ua_data"], registro["fs"])
        df.to_csv(f"{out_dir}/{record_id}.csv", index=False)

        fila = {"record_id": record_id}
        fila.update(registro["metadata"])
        filas_outcomes.append(fila)
        todas_las_keys.update(registro["metadata"].keys())

    columnas = ["record_id"] + sorted(todas_las_keys)
    with open(outcomes_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columnas)
        writer.writeheader()
        writer.writerows(filas_outcomes)

    print(f"  ✓ {len(filas_outcomes)} series de tiempo guardadas en {out_dir}/")
    print(f"  ✓ Outcomes guardados en {outcomes_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/ctu_uhb")
    parser.add_argument("--out-dir", default="data/extracted/ctu_uhb")
    parser.add_argument("--outcomes-path", default="data/extracted/ctu_uhb_outcomes.csv")
    args = parser.parse_args()

    construir_database(args.data_dir, args.out_dir, args.outcomes_path)


if __name__ == "__main__":
    main()
