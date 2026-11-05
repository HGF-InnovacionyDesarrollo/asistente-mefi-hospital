"""Redacta campos identificatorios (ID, Nombre, RUT, Paciente) de casos MEFI reales.

Uso: python scripts/pipeline/redactar_casos.py
Lee de SRC_DIR (fuera del repo) y escribe imágenes PNG redactadas en fixtures/casos_redactados/.
No modifica ni sube los originales a ningún lado.
"""

import os
from collections import defaultdict

import fitz  # PyMuPDF
import numpy as np
import pytesseract
from PIL import Image, ImageDraw, ImageOps

TESSERACT_CANDIDATES = [
    r"C:\Users\usuariohgf\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
]
for candidate in TESSERACT_CANDIDATES:
    if os.path.exists(candidate):
        pytesseract.pytesseract.tesseract_cmd = candidate
        break

SRC_DIR = r"C:\Users\usuariohgf\Desktop\Casos"
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "casos_redactados")
# Coincidencia amplia a propósito (más falsos positivos = más seguro que falsos negativos
# tratándose de PHI): variantes e incluso fragmentos que suele dejar el OCR sobre texto chico.
KEYWORDS = ["id", "nombre", "ombre", "rut", "pacient", "nom"]
DPI = 300
PAD = 14
UPSCALE_MIN_DIM = 1800  # si la imagen es más chica que esto, se agranda antes de OCR
PSMS = (3, 4, 6, 11, 12)


def redactar_texto_pdf(page):
    """Tapa (borra de verdad, vía apply_redactions) las líneas de texto nativo que calzan con KEYWORDS."""
    words = page.get_text("words")
    if not words:
        return
    lineas = defaultdict(list)
    for x0, y0, x1, y1, texto, block, line, word_no in words:
        lineas[(block, line)].append((x0, y0, x1, y1, texto))
    huecos = False
    for grupo in lineas.values():
        texto_linea = " ".join(w[4] for w in grupo).lower()
        if any(kw in texto_linea for kw in KEYWORDS):
            x0 = min(w[0] for w in grupo)
            y0 = min(w[1] for w in grupo)
            x1 = max(w[2] for w in grupo)
            y1 = max(w[3] for w in grupo)
            page.add_redact_annot(fitz.Rect(x0, y0, x1, y1), fill=(0, 0, 0))
            huecos = True
    if huecos:
        page.apply_redactions()


def _preparar_para_ocr(img: Image.Image) -> Image.Image:
    """Escala de grises + autocontraste + upscale si la imagen es chica: el texto de las
    tiras MEFI es diminuto (fuente de impresora térmica) y Tesseract lo pierde a resolución baja."""
    gris = ImageOps.grayscale(img)
    gris = ImageOps.autocontrast(gris, cutoff=1)
    if min(gris.size) < UPSCALE_MIN_DIM:
        factor = UPSCALE_MIN_DIM / min(gris.size)
        gris = gris.resize((int(gris.width * factor), int(gris.height * factor)), Image.LANCZOS)
    return gris


def redactar_imagen_ocr(img: Image.Image) -> Image.Image:
    """Tapa texto detectado por OCR que calza con KEYWORDS. Corre muchas pasadas
    (4 rotaciones x varios modos de segmentación de página de Tesseract) sobre una versión
    preprocesada para mejorar recall, y tapa tanto líneas completas como palabras sueltas que
    matcheen (más redundancia = menos probabilidad de dejar algo sin tapar). Combina todas las
    pasadas tomando el mínimo por píxel sobre la imagen ORIGINAL (a color, sin upscale)."""
    img = img.convert("RGB")
    tamano_original = img.size
    compuesto = np.array(img).astype(np.int16)
    preparada = _preparar_para_ocr(img)
    factor_escala = preparada.size[0] / tamano_original[0]

    for angulo in (0, 90, 180, 270):
        rotada = preparada.rotate(angulo, expand=True)
        capa = Image.new("L", rotada.size, color=255)  # máscara: 0 = tapar
        draw = ImageDraw.Draw(capa)
        cajas_detectadas = []

        for psm in PSMS:
            try:
                data = pytesseract.image_to_data(
                    rotada, output_type=pytesseract.Output.DICT, config=f"--psm {psm}", lang="spa+eng"
                )
            except pytesseract.TesseractError:
                continue
            n = len(data["text"])
            lineas = defaultdict(list)
            for i in range(n):
                clave = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
                lineas[clave].append(i)
            for idxs in lineas.values():
                texto_linea = " ".join(data["text"][i] for i in idxs).strip().lower()
                if texto_linea and any(kw in texto_linea for kw in KEYWORDS):
                    x0 = min(data["left"][i] for i in idxs)
                    y0 = min(data["top"][i] for i in idxs)
                    x1 = max(data["left"][i] + data["width"][i] for i in idxs)
                    y1 = max(data["top"][i] + data["height"][i] for i in idxs)
                    cajas_detectadas.append((x0, y0, x1, y1))
            # además, palabra por palabra (por si el agrupado por línea falla)
            for i in range(n):
                palabra = data["text"][i].strip().lower()
                if palabra and any(kw in palabra for kw in KEYWORDS):
                    x0, y0 = data["left"][i], data["top"][i]
                    x1, y1 = x0 + data["width"][i], y0 + data["height"][i]
                    cajas_detectadas.append((x0, y0, x1, y1))

        pad_escalado = int(PAD * factor_escala)
        for x0, y0, x1, y1 in cajas_detectadas:
            draw.rectangle(
                [x0 - pad_escalado, y0 - pad_escalado, x1 + pad_escalado, y1 + pad_escalado], fill=0
            )

        # bajar la máscara a la resolución/orientación original y componer
        de_vuelta = capa.rotate(-angulo, expand=True)
        de_vuelta = de_vuelta.resize(tamano_original, Image.NEAREST)
        mascara = np.array(de_vuelta)  # 0 donde hay que tapar, 255 donde no
        negro = np.zeros_like(compuesto)
        tapar = (mascara == 0)[:, :, None]
        compuesto = np.where(tapar, negro, compuesto)

    return Image.fromarray(compuesto.astype(np.uint8))


def procesar_pdf(ruta, nombre_base):
    doc = fitz.open(ruta)
    salidas = []
    for i, page in enumerate(doc):
        redactar_texto_pdf(page)  # borra texto nativo con OCR/PDF-text layer, si existe
        pix = page.get_pixmap(dpi=DPI)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        img = redactar_imagen_ocr(img)  # defensa adicional por si hay texto rasterizado
        out_path = os.path.join(OUT_DIR, f"{nombre_base}_p{i+1}_redacted.png")
        img.save(out_path)
        salidas.append(out_path)
    doc.close()
    return salidas


def procesar_imagen(ruta, nombre_base):
    img = Image.open(ruta)
    img = redactar_imagen_ocr(img)
    out_path = os.path.join(OUT_DIR, f"{nombre_base}_redacted.png")
    img.save(out_path)
    return [out_path]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    archivos = sorted(os.listdir(SRC_DIR))
    resumen = []
    for nombre_archivo in archivos:
        ruta = os.path.join(SRC_DIR, nombre_archivo)
        base, ext = os.path.splitext(nombre_archivo)
        base_segura = "".join(c if c.isalnum() else "_" for c in base)
        ext = ext.lower()
        print(f"Procesando: {nombre_archivo}")
        try:
            if ext == ".pdf":
                salidas = procesar_pdf(ruta, base_segura)
            elif ext in (".jpg", ".jpeg", ".png"):
                salidas = procesar_imagen(ruta, base_segura)
            else:
                print(f"  omitido (extensión no soportada: {ext})")
                continue
            for s in salidas:
                print(f"  -> {s}")
            resumen.append((nombre_archivo, len(salidas)))
        except Exception as e:
            print(f"  ERROR procesando {nombre_archivo}: {e}")

    print("\nResumen:")
    for nombre, n in resumen:
        print(f"  {nombre}: {n} página(s) redactada(s)")
    print(f"\nTotal archivos de salida en: {OUT_DIR}")
    print("IMPORTANTE: revisa visualmente cada imagen en fixtures/casos_redactados/ antes de usarla para nada más.")


if __name__ == "__main__":
    main()
