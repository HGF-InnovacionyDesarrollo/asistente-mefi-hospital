#!/usr/bin/env python3
"""Asigna IDs anonimos (casoNN) a los escaneos originales del hospital y los
renombra al estandar documentado en data/README.md
(YYYY-MM-DD_casoNN_HoraInicio.ext).

El mapeo nombre_real <-> casoNN contiene PHI y vive FUERA del proyecto
(por defecto C:\\MEFI-privado\\mapeo_casos.csv): nunca en el repo ni en una
carpeta sincronizada a la nube. Si ese CSV ya existe, se toma como base y se
continua la numeracion desde el casoNN maximo ya usado.

IDs preservados por compatibilidad con data/extracted/:
  caso01 = 2026-06-24 07:27:47   caso02 = 2026-06-06 02:21:59
caso03 y caso04 quedan reservados: sus CSV ya existen en data/extracted/
aunque su escaneo original no este identificado todavia.

El renombrado no toca el contenido ni afecta el analisis: el pipeline trabaja
sobre fixtures/casos_redactados/ y data/extracted/, nunca sobre estos originales.

Uso:
    python scripts/pipeline/mapear_casos.py --src "<carpeta con escaneos>" --dst casos_hospital/escaneos --dry-run
    python scripts/pipeline/mapear_casos.py --src "<carpeta con escaneos>" --dst casos_hospital/escaneos --apply
"""

import argparse
import csv
import re
import shutil
import sys
import unicodedata
from pathlib import Path

MAPEO_CSV = Path(r"C:\MEFI-privado\mapeo_casos.csv")

RESERVADOS = {1, 2, 3, 4}  # caso01/caso02 ya usados en data/extracted; 03/04 reservados

# Identidades ya consagradas en data/extracted/: (fecha, hora) -> casoNN.
# El par PDF+JPG de "Casos Digitalizados" comparte caso01 (mismo caso, misma
# fecha/hora); comparten sufijo de ext distinto, asi que no colisionan.
IDENTIDADES_CONOCIDAS = {
    ("2026-06-24", "07h27min47s"): 1,  # data/extracted/2026-06-24_caso01_07h27min47s.csv (+ _jpg)
    ("2026-06-06", "02h21min59s"): 2,  # data/extracted/2026-06-06_caso02_02h21min59s.csv
}

# Archivos legacy cuya fecha no sigue el patron YYYY-MM-DD del nombre.
# Valores inferidos del nombre (ddmmaaaa); verificar contra la cabecera del papel.
FECHAS_MANUALES = {
    "CCI26062025.pdf": ("2025-06-26", "fecha del nombre; corresponde a data/extracted/2025-06-26_CCI.csv"),
    "MEFI126062025.pdf": ("2025-06-26", "fecha del nombre; corresponde a data/extracted/2025-06-26_MEFI1.csv"),
    "mefi03092025.pdf": ("2025-09-03", "fecha inferida del nombre (ddmmaaaa); verificar con cabecera"),
    "Mefi09092025.pdf": ("2025-09-09", "fecha inferida del nombre (ddmmaaaa); verificar con cabecera"),
    "mefi103092025.pdf": ("2025-09-10", "fecha inferida del nombre (ddmmaaaa); verificar con cabecera"),
    "mefi227102025.pdf": ("2025-07-22", "fecha inferida del nombre (ddmmaaaa); verificar con cabecera"),
    "mefi28072025.pdf": ("2025-07-28", "fecha inferida del nombre (ddmmaaaa); verificar con cabecera"),
    "mefi327102025.pdf": ("2025-10-27", "fecha inferida del nombre (mefi3 + 27102025); verificar con cabecera"),
    "gase mefi227102025.pdf": ("2025-07-22", "fecha inferida del nombre (ddmmaaaa); verificar con cabecera"),
}

RE_FECHA_HORA = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[_ ]+(\d{1,2})h[-_]?(\d{2})min[-_]?(\d{2})s", re.IGNORECASE
)


def _slug(texto: str) -> str:
    """Descriptor corto y sin PHI a partir del nombre original (sin fecha)."""
    normalizado = unicodedata.normalize("NFKD", texto)
    ascii_txt = normalizado.encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_txt.lower()).strip("-")
    return slug or "escaneo"


def _ext_normalizada(path: Path) -> str:
    ext = path.suffix.lower()
    return ".jpg" if ext == ".jpeg" else ext


def cargar_mapeo(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def parsear(nombre: str) -> tuple[str | None, str | None, str]:
    """Devuelve (fecha, hora, nota) a partir del nombre de archivo."""
    if nombre in FECHAS_MANUALES:
        fecha, nota = FECHAS_MANUALES[nombre]
        return fecha, None, nota
    m = RE_FECHA_HORA.search(nombre)
    if m:
        anio, mes, dia, h, mi, s = m.groups()
        fecha = f"{anio}-{mes}-{dia}"
        hora = f"{int(h):02d}h{mi}min{s}s"
        return fecha, hora, "fecha/hora del nombre"
    fecha_manual = re.search(r"(19|20)\d{2}-\d{2}-\d{2}", nombre)
    if fecha_manual:
        return fecha_manual.group(0), None, "fecha del nombre"
    return None, None, "sin fecha en el nombre; asignado slug descriptivo"


def nombre_destino(caso_id: int, fecha: str | None, hora: str | None, slug: str, ext: str) -> str:
    if fecha and hora:
        return f"{fecha}_caso{caso_id:02d}_{hora}{ext}"
    if fecha:
        return f"{fecha}_caso{caso_id:02d}{ext}"
    return f"caso{caso_id:02d}_{slug}{ext}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, type=Path, help="Carpeta origen (solo archivos directos).")
    ap.add_argument("--dst", required=True, type=Path, help="Carpeta destino (se crea si falta).")
    ap.add_argument("--mapeo", type=Path, default=MAPEO_CSV, help=f"CSV de mapeo (default: {MAPEO_CSV}).")
    ap.add_argument("--apply", action="store_true", help="Ejecutar renombres (default: dry-run).")
    ap.add_argument("--dry-run", action="store_true", help="Solo mostrar el plan (es el default; flag de claridad).")
    args = ap.parse_args()

    if not args.src.is_dir():
        print(f"ERROR: no existe {args.src}", file=sys.stderr)
        return 1

    archivos = sorted(p for p in args.src.iterdir() if p.is_file())
    if not archivos:
        print(f"ERROR: {args.src} no tiene archivos directos", file=sys.stderr)
        return 1

    filas_existentes = cargar_mapeo(args.mapeo)
    usados = {int(re.search(r"\d+", f["caso_id"]).group()) for f in filas_existentes if f.get("caso_id")}
    siguiente = max(usados | RESERVADOS) + 1

    plan = []
    for original in archivos:
        fecha, hora, nota = parsear(original.name)
        slug = _slug(original.stem)
        plan.append({"original": original, "fecha": fecha, "hora": hora, "nota": nota, "slug": slug})

    plan.sort(key=lambda p: (p["fecha"] or "9999-99-99", p["hora"] or "99h99min99s", p["original"].name))

    destinos_vistos: dict[str, Path] = {}
    nuevas_filas = []
    for item in plan:
        clave = (item["fecha"], item["hora"])
        if clave in IDENTIDADES_CONOCIDAS:
            # Reutiliza el ID aunque ya se uso en esta corrida: archivos
            # companeros del mismo caso (misma fecha/hora, distinta extension
            # o carpeta) comparten casoNN. La verificacion de colision de
            # nombres destino aborta si dos archivos distintos chocaran.
            caso_id = IDENTIDADES_CONOCIDAS[clave]
        else:
            while siguiente in usados:
                siguiente += 1
            caso_id = siguiente
            siguiente += 1
        usados.add(caso_id)
        nuevo_nombre = nombre_destino(caso_id, item["fecha"], item["hora"], item["slug"], _ext_normalizada(item["original"]))
        destino = args.dst / nuevo_nombre
        if nuevo_nombre in destinos_vistos:
            print(f"ERROR: colision de nombres destino: {nuevo_nombre}", file=sys.stderr)
            return 1
        if destino.exists():
            print(f"ERROR: ya existe {destino}", file=sys.stderr)
            return 1
        destinos_vistos[nuevo_nombre] = item["original"]
        nuevas_filas.append({
            "caso_id": f"caso{caso_id:02d}",
            "fecha": item["fecha"] or "",
            "hora": item["hora"] or "",
            "nombre_original": item["original"].name,
            "ruta_original": str(item["original"]),
            "ruta_nueva": str(destino),
            "notas": item["nota"],
        })

    print(f"{'caso':<8} {'destino':<48} <- origen")
    for f in nuevas_filas:
        print(f"{f['caso_id']:<8} {Path(f['ruta_nueva']).name:<48} <- {f['nombre_original']}")

    if not args.apply:
        print("\nDRY-RUN: nada se movio. Revisa la tabla y vuelve a correr con --apply.")
        return 0

    args.dst.mkdir(parents=True, exist_ok=True)
    args.mapeo.parent.mkdir(parents=True, exist_ok=True)
    for item, f in zip(plan, nuevas_filas):
        shutil.move(str(item["original"]), f["ruta_nueva"])

    existe = args.mapeo.exists()
    with args.mapeo.open("a", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["caso_id", "fecha", "hora", "nombre_original", "ruta_original", "ruta_nueva", "notas"])
        if not existe:
            writer.writeheader()
        writer.writerows(nuevas_filas)

    print(f"\nOK: {len(nuevas_filas)} archivos movidos. Mapeo: {args.mapeo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
