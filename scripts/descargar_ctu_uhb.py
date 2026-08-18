#!/usr/bin/env python3
"""Descarga registros del dataset CTU-UHB (PhysioNet) a data/ctu_uhb/.

Uso:
    python scripts/descargar_ctu_uhb.py --n-records 10
    python scripts/descargar_ctu_uhb.py --record-ids 1001 1002 1003
    python scripts/descargar_ctu_uhb.py --all   # los 552 registros completos

data/ctu_uhb/ está gitignored: los .hea/.dat nunca se commitean, se
regeneran corriendo este script.
"""

import argparse
from pathlib import Path

import wfdb

DATASET = "ctu-uhb-ctgdb"
DATA_DIR = "data/ctu_uhb"


def listar_record_ids() -> list[str]:
    return wfdb.get_record_list(DATASET)


def descargar(record_ids: list[str], data_dir: str = DATA_DIR) -> None:
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    print(f"[*] Descargando {len(record_ids)} registro(s) a {data_dir}...")
    wfdb.dl_database(DATASET, dl_dir=data_dir, records=record_ids)
    print(f"  ✓ Descarga completada")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--n-records", type=int, help="Descargar los primeros N registros")
    group.add_argument("--record-ids", nargs="+", help="IDs específicos a descargar")
    group.add_argument("--all", action="store_true", help="Descargar los 552 registros completos")
    parser.add_argument("--data-dir", default=DATA_DIR)

    args = parser.parse_args()

    if args.record_ids:
        record_ids = args.record_ids
    else:
        todos = listar_record_ids()
        print(f"[*] Dataset CTU-UHB tiene {len(todos)} registros disponibles")
        if args.all:
            record_ids = todos
        elif args.n_records:
            record_ids = todos[: args.n_records]
        else:
            record_ids = todos[:10]
            print("  (sin --n-records/--record-ids/--all, se descargan los primeros 10 por defecto)")

    descargar(record_ids, args.data_dir)


if __name__ == "__main__":
    main()
