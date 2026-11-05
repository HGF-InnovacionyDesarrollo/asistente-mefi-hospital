#!/usr/bin/env python3
"""Genera GUIA_PROFESIONALES.docx (raiz del proyecto) a partir de
docs/GUIA_PROFESIONALES.md.

El .md sigue siendo la fuente de verdad; este script solo la vuelca a Word
para distribuirla a personas que no usan editores de texto plano. Volver a
correrlo tras editar la guia.

Uso:
    python scripts/utilidades/generar_guia_docx.py
"""

import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

RAIZ = Path(__file__).resolve().parents[2]
FUENTE = RAIZ / "docs" / "GUIA_PROFESIONALES.md"
DESTINO = RAIZ / "GUIA_PROFESIONALES.docx"

RE_INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)")


def _sombra_gris(paragraph, fill="F2F2F2"):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), fill)
    paragraph._p.get_or_add_pPr().append(shd)


def _agregar_runs(paragraph, texto):
    """Aplica formato inline: **negrita**, *cursiva*, `codigo`. Los links
    [texto](ruta) se reducen a su texto (son rutas internas del repo)."""
    texto = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", texto)
    for trozo in RE_INLINE.split(texto):
        if not trozo:
            continue
        if trozo.startswith("**") and trozo.endswith("**"):
            paragraph.add_run(trozo[2:-2]).bold = True
        elif trozo.startswith("`") and trozo.endswith("`"):
            run = paragraph.add_run(trozo[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt(10)
        elif trozo.startswith("*") and trozo.endswith("*") and len(trozo) > 2:
            paragraph.add_run(trozo[1:-1]).italic = True
        else:
            paragraph.add_run(trozo)


def _estilo_base(doc):
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)


def convertir() -> None:
    lineas = FUENTE.read_text(encoding="utf-8").splitlines()
    doc = Document()
    _estilo_base(doc)

    i = 0
    while i < len(lineas):
        linea = lineas[i].rstrip()

        if not linea.strip():
            i += 1
            continue

        # Bloques de codigo
        if linea.strip().startswith("```"):
            i += 1
            while i < len(lineas) and not lineas[i].strip().startswith("```"):
                p = doc.add_paragraph()
                run = p.add_run(lineas[i])
                run.font.name = "Consolas"
                run.font.size = Pt(9)
                p.paragraph_format.space_after = Pt(0)
                _sombra_gris(p)
                i += 1
            i += 1  # cierra el fence
            continue

        # Tablas markdown
        if linea.lstrip().startswith("|"):
            filas = []
            while i < len(lineas) and lineas[i].lstrip().startswith("|"):
                celda_raw = lineas[i].strip().strip("|")
                celdas = [c.strip() for c in celda_raw.split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c or "---") for c in celdas):
                    filas.append(celdas)
                i += 1
            if filas:
                tabla = doc.add_table(rows=len(filas), cols=max(len(f) for f in filas))
                tabla.style = "Table Grid"
                for r, fila in enumerate(filas):
                    for c, celda in enumerate(fila):
                        celda_doc = tabla.cell(r, c)
                        celda_doc.text = ""
                        _agregar_runs(celda_doc.paragraphs[0], celda)
                        if r == 0:
                            for run in celda_doc.paragraphs[0].runs:
                                run.bold = True
                doc.add_paragraph()
            continue

        # Titulos
        m = re.match(r"^(#{1,4})\s+(.*)", linea)
        if m:
            nivel = min(len(m.group(1)), 4)
            doc.add_heading(m.group(2).strip(), level=0 if nivel == 1 else nivel)
            i += 1
            continue

        # Separadores horizontales
        if re.fullmatch(r"-{3,}", linea.strip()):
            i += 1
            continue

        # Citas
        if linea.lstrip().startswith("> "):
            p = doc.add_paragraph(style="Intense Quote")
            _agregar_runs(p, linea.lstrip()[2:])
            i += 1
            continue

        # Listas con vineta
        if linea.lstrip().startswith("- "):
            p = doc.add_paragraph(style="List Bullet")
            _agregar_runs(p, linea.lstrip()[2:])
            i += 1
            continue

        # Listas numeradas
        m = re.match(r"^(\s*)(\d+)\.\s+(.*)", linea)
        if m:
            p = doc.add_paragraph(style="List Number")
            _agregar_runs(p, m.group(3))
            i += 1
            continue

        # Parrafo normal
        p = doc.add_paragraph()
        _agregar_runs(p, linea)
        i += 1

    # Pie con fecha de generacion
    pie = doc.add_paragraph()
    pie.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = pie.add_run("Documento generado automáticamente desde docs/GUIA_PROFESIONALES.md")
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

    doc.save(DESTINO)
    print(f"OK: {DESTINO}")


if __name__ == "__main__":
    if not FUENTE.exists():
        sys.exit(f"ERROR: no existe {FUENTE}")
    convertir()
