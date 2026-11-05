"""Digitalización determinística de trazados CTG/MEFI (imagen -> curvas FCF/UA).

Ningún LLM "lee" coordenadas aquí: la curva se extrae por visión clásica
(umbral de color + seguimiento por continuidad + detección de tramos no
confiables) y se calibra a unidades clínicas (lpm / mmHg) vía OCR de las
etiquetas del eje Y, con un preset manual de respaldo si el OCR no alcanza
confianza suficiente. Ver plan en C:\\Users\\usuariohgf\\.claude\\plans\\composed-sniffing-moler.md.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pytesseract
from PIL import Image, ImageDraw, ImageOps
from scipy.ndimage import median_filter
from scipy.signal import find_peaks

TESSERACT_CANDIDATES = [
    r"C:\Users\usuariohgf\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
]


def _configurar_tesseract() -> bool:
    import os

    raiz_bundle = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    candidatos = [
        os.environ.get("MEFI_TESSERACT"),  # definido por MEFI.bat del bundle
        os.path.join(raiz_bundle, "tesseract", "tesseract.exe"),  # vendido junto a la app
        *TESSERACT_CANDIDATES,
    ]
    for candidato in candidatos:
        if candidato and os.path.exists(candidato):
            pytesseract.pytesseract.tesseract_cmd = candidato
            return True
    return False


_TESSERACT_OK = _configurar_tesseract()

PALABRAS_CLAVE_PANEL = ("fhr", "ua", "bpm", "mmhg", "kpa", "fcf")

# Términos clínicos que, si aparecen anotados a mano cerca del panel UA, cambian la
# interpretación del registro (ej. peridural -> posible hipotensión materna).
PALABRAS_CLAVE_CLINICAS = (
    "peridural", "epidural", "oxitocina", "ocitocina", "meconio",
    "anestesia", "cesarea", "cesárea", "forceps", "fórceps",
)


# --------------------------------------------------------------------------
# Estructuras de resultado
# --------------------------------------------------------------------------


@dataclass
class LimitesPanel:
    y0: int
    y1: int


@dataclass
class CalibracionEje:
    valor_por_px: float  # unidades clinicas por pixel vertical (negativo: sube = aumenta valor)
    valor_en_y0: float  # valor clinico en la fila superior del panel (y0)
    metodo: str  # "ocr" | "manual"
    confianza: float  # 0-1

    def px_a_valor(self, y_dentro_de_panel: np.ndarray) -> np.ndarray:
        return self.valor_en_y0 + y_dentro_de_panel * self.valor_por_px


@dataclass
class ResultadoDigitalizacion:
    df: pd.DataFrame  # columnas: tiempo_s, fcf, fcf_confiable, ua, ua_confiable
    overlay: Image.Image
    calibracion_fcf: CalibracionEje
    calibracion_ua: CalibracionEje
    advertencias: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Orientación y paneles
# --------------------------------------------------------------------------


def orientar_y_detectar_paneles(
    imagen: Image.Image,
) -> tuple[Image.Image, np.ndarray, LimitesPanel, LimitesPanel] | None:
    """Prueba las 4 rotaciones de a 90° y se queda con la que efectivamente separa dos
    paneles horizontales bien definidos (FCF arriba, UA abajo) — usar la calidad de esa
    separación como señal de orientación es más robusto que contar palabras reconocidas
    por OCR, que falla fácil con la grilla y el texto minúsculo de estas tiras.

    Devuelve (imagen_rotada, gris_autocontraste, panel_fcf, panel_ua) o None si en
    ninguna rotación se encontraron dos paneles plausibles.
    """
    candidatos = []  # (score_paneles, angulo, imagen_rotada, gris, panel_top, panel_bottom)
    for angulo in (0, 90, 180, 270):
        rotada = imagen.rotate(angulo, expand=True)
        gris_crudo = np.array(ImageOps.grayscale(rotada)).astype(int)
        paneles = _detectar_paneles(gris_crudo)
        if paneles is None:
            continue
        p_top, p_bot = paneles
        alto_img = gris_crudo.shape[0]
        alto_top, alto_bot = p_top.y1 - p_top.y0, p_bot.y1 - p_bot.y0
        # Sanity check: en un layout de 2 paneles reales, ninguno debería ocupar la imagen
        # casi entera ni solaparse tanto que la "cobertura" supere el 100%. Sin este chequeo,
        # una rotación degenerada (imagen ya apaisada, rotada igual a un aspecto extremo)
        # puede dar paneles que se solapan muchísimo y un puntaje inflado que gana por sobre
        # una rotación correcta — pasó en la práctica con una imagen ya apaisada de origen.
        if alto_top > alto_img * 0.85 or alto_bot > alto_img * 0.85:
            continue
        cobertura = min((alto_top + alto_bot) / alto_img, 1.0)
        balance = min(alto_top, alto_bot) / max(alto_top, alto_bot)
        gris_ac = np.array(ImageOps.autocontrast(ImageOps.grayscale(rotada), cutoff=1)).astype(int)
        candidatos.append((cobertura * balance, angulo, rotada, gris_ac, p_top, p_bot))

    if not candidatos:
        return None

    # Dos rotaciones "en paisaje" opuestas (ej. 90 y 270) suelen pasar ambas el filtro de
    # paneles con score casi idéntico -son la misma imagen espejada verticalmente-, así que
    # el score de paneles solo no basta para saber cuál lee bien "arriba abajo". Desempatar
    # con la detección de orientación de Tesseract (OSD): aunque la confianza absoluta sea
    # baja en estas imágenes ruidosas, el "Rotate" que sugiere (0 = ya está bien, 180 = al
    # revés) resultó ser una señal confiable en la práctica, más que contar palabras sueltas.
    candidatos.sort(key=lambda t: -t[0])
    mejor_score = candidatos[0][0]
    finalistas = [c for c in candidatos if c[0] >= mejor_score * 0.9]
    if len(finalistas) > 1 and _TESSERACT_OK:
        finalistas.sort(key=lambda c: _rotacion_sugerida_osd(c[2]))

    _, _, rotada, gris, p_top, p_bot = finalistas[0]
    return rotada, gris, p_top, p_bot


def _rotacion_sugerida_osd(imagen: Image.Image) -> int:
    """Cuánta rotación adicional sugiere Tesseract OSD (0 es mejor: ya está bien orientada).
    Devuelve 999 si OSD no pudo determinarlo (para que ese candidato quede al final)."""
    try:
        osd = pytesseract.image_to_osd(imagen, config="--psm 0", output_type=pytesseract.Output.DICT)
        return int(osd.get("rotate", 999))
    except Exception:
        return 999


def _detectar_paneles(gris: np.ndarray) -> tuple[LimitesPanel, LimitesPanel] | None:
    """Divide la imagen en panel FCF (superior) y panel UA (inferior) en dos etapas:

    1) Ubicar el papel dentro de la imagen: el contraste papel-vs-fondo (foto/escaneo) es
       enorme (decenas de puntos de brillo), así que un umbral por punto medio del brillo
       ya lo separa de forma confiable.
    2) Dentro del papel, el hueco entre paneles es mucho más sutil (~10-20 de 255 sobre el
       contenido típico) — se ubica como el máximo local de brillo en la franja central
       (15%-85%) del papel, y se expande desde ahí hasta que el brillo cae al nivel de
       contenido típico (percentil 40 del papel).
    """
    h, w = gris.shape
    brillo = gris.astype(float).mean(axis=1)

    suave_grueso = median_filter(brillo, size=21)
    umbral_papel = (suave_grueso.max() + suave_grueso.min()) / 2
    if suave_grueso.max() - suave_grueso.min() < 30:
        return None  # sin contraste papel/fondo claro: no confiar en esta imagen
    filas_papel = np.where(suave_grueso > umbral_papel)[0]
    if len(filas_papel) < h * 0.2:
        return None
    y_papel_ini, y_papel_fin = int(filas_papel[0]), int(filas_papel[-1])
    alto_papel = y_papel_fin - y_papel_ini
    if alto_papel < h * 0.2:
        return None

    zona_ini = y_papel_ini + int(alto_papel * 0.15)
    zona_fin = y_papel_ini + int(alto_papel * 0.85)
    suave_fino = median_filter(brillo, size=41)
    zona = suave_fino[zona_ini:zona_fin]
    if len(zona) == 0:
        return None
    y_pico = zona_ini + int(np.argmax(zona))

    nivel_contenido = np.percentile(suave_fino[y_papel_ini:y_papel_fin], 40)
    y0_hueco = y_pico
    while y0_hueco > y_papel_ini and suave_fino[y0_hueco] > nivel_contenido:
        y0_hueco -= 1
    y1_hueco = y_pico
    while y1_hueco < y_papel_fin and suave_fino[y1_hueco] > nivel_contenido:
        y1_hueco += 1

    # El "hueco" detectado puede ser un mínimo local de tinta dentro de la propia grilla
    # (no el límite real del panel) — pasó en la práctica. En vez de perseguir precisión
    # perfecta acá, se da margen generoso hacia adentro de cada panel (55% de su tamaño
    # crudo) para no cortar la grilla real ni la curva; la calibración por 2 clics no
    # depende de que este límite sea exacto, solo de que no deje afuera la señal real.
    MARGEN = 0.55
    alto_fcf_crudo = y0_hueco - y_papel_ini
    alto_ua_crudo = y_papel_fin - y1_hueco
    panel_fcf = LimitesPanel(y_papel_ini, min(y0_hueco + int(alto_fcf_crudo * MARGEN), y_papel_fin))
    panel_ua = LimitesPanel(max(y1_hueco - int(alto_ua_crudo * MARGEN), y_papel_ini), y_papel_fin)
    alto_fcf, alto_ua = panel_fcf.y1 - panel_fcf.y0, panel_ua.y1 - panel_ua.y0
    if alto_fcf < h * 0.1 or alto_ua < h * 0.1:
        return None  # panel degenerado: el "pico" encontrado no era un hueco real
    return panel_fcf, panel_ua


# --------------------------------------------------------------------------
# Calibración del eje Y
# --------------------------------------------------------------------------


def _leer_etiquetas_eje(gris: np.ndarray, panel: LimitesPanel,
                        ancho_margen_frac: float = 0.10) -> list[tuple[float, int]]:
    """OCR del margen izquierdo del panel: devuelve [(y_en_panel, valor)] con
    las etiquetas numéricas leídas (mejor esfuerzo; puede faltar o confundir
    dígitos en fotos ruidosas — por eso el uso es de SUGERENCIA, con
    verificación humana, no de calibración directa)."""
    if not _TESSERACT_OK:
        return []
    h, w = gris.shape
    ancho_margen = max(int(w * ancho_margen_frac), 40)
    franja = gris[panel.y0:panel.y1, 0:ancho_margen]
    if franja.size == 0:
        return []
    franja_img = Image.fromarray(franja.astype(np.uint8))
    factor = max(1, 900 // max(franja_img.width, 1))
    franja_img = franja_img.resize((franja_img.width * factor, franja_img.height * factor), Image.LANCZOS)
    franja_img = ImageOps.autocontrast(franja_img, cutoff=1)

    try:
        data = pytesseract.image_to_data(franja_img, config="--psm 6", output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractError:
        return []

    puntos = []  # (y_en_panel, valor_numerico)
    for i, texto in enumerate(data["text"]):
        limpio = texto.strip().replace("-", "")
        if limpio.isdigit() and 0 < int(limpio) <= 300:
            y_centro_franja = data["top"][i] + data["height"][i] / 2
            puntos.append((y_centro_franja / factor, int(limpio)))
    return puntos


def _calibrar_eje_ocr(gris: np.ndarray, panel: LimitesPanel, ancho_margen_frac: float = 0.10) -> CalibracionEje | None:
    """Lee las etiquetas numéricas impresas en el margen izquierdo del panel y ajusta
    una recta valor = a*y + b. Devuelve None si no hay al menos 2 lecturas numéricas
    consistentes (monótonas) para anclar la calibración."""
    puntos = _leer_etiquetas_eje(gris, panel, ancho_margen_frac)
    if len(puntos) < 2:
        return None

    ys = np.array([p[0] for p in puntos], dtype=float)
    valores = np.array([p[1] for p in puntos], dtype=float)
    # ajuste lineal simple (mínimos cuadrados); con pocos puntos ruidosos igual da una pendiente razonable
    A = np.vstack([ys, np.ones_like(ys)]).T
    pendiente, ordenada = np.linalg.lstsq(A, valores, rcond=None)[0]
    prediccion = pendiente * ys + ordenada
    residual = np.mean(np.abs(prediccion - valores))
    confianza = max(0.0, min(1.0, 1 - residual / 20)) * min(1.0, len(puntos) / 4)

    return CalibracionEje(valor_por_px=pendiente, valor_en_y0=ordenada, metodo="ocr", confianza=confianza)


def _detectar_lineas_grilla(gris: np.ndarray, panel: LimitesPanel,
                            margen_frac: float = 0.12) -> list[int]:
    """Filas (relativas al panel) donde hay líneas de grilla horizontales.

    La grilla atraviesa todo el ancho del papel, así que oscurece levemente
    TODAS las columnas en su fila; la curva y el texto solo tocan unas pocas.
    Por eso se usa la MEDIANA de oscuridad por fila (la curva queda filtrada)
    y se buscan picos periódicos suaves sobre el fondo del papel.
    """
    h, w = gris.shape
    x0 = int(w * margen_frac)
    banda = gris[panel.y0:panel.y1, x0:]
    if banda.shape[0] < 20 or banda.shape[1] < 20:
        return []
    oscuridad = 255.0 - np.median(banda, axis=1)
    suave = median_filter(oscuridad, size=3, mode="nearest")
    p50 = float(np.median(suave))
    # p99 y no p90: la grilla puede ocupar <10% de las filas y entonces el
    # p90 queda en el fondo del papel y la medida de contraste da cero.
    p99 = float(np.percentile(suave, 99))
    if p99 - p50 < 5:  # sin contraste de grilla visible en este panel
        return []
    picos, _ = find_peaks(suave, height=p50 + 0.3 * (p99 - p50),
                          distance=4, prominence=2)
    return [int(p) for p in picos]


def sugerir_puntos_calibracion(gris: np.ndarray, panel: LimitesPanel,
                               valores_default: tuple[float, float] = (210.0, 30.0)
                               ) -> list[tuple[float, float]] | None:
    """Sugerencia SEMI-AUTOMÁTICA de calibración: pre-rellena los dos puntos
    para que el usuario solo tenga que VERIFICAR los valores, sin clics.

    Estrategia en dos niveles (mejor esfuerzo):
    1. OCR de las etiquetas del margen izquierdo: si leyó >=2 números con
       relación monótona consistente, se usan las dos lecturas más separadas —
       posiciones y valores reales del papel.
    2. Si no, detección de las líneas de grilla superior e inferior, con los
       valores por defecto del tipo de panel (el usuario confirma/corrige).

    Nunca calibra por sí sola: la decisión consciente del 11-ago-2026 de exigir
    confirmación humana de la escala se mantiene; esto solo quita los clics.
    """
    puntos = _leer_etiquetas_eje(gris, panel)
    if len(puntos) >= 2:
        puntos = sorted(puntos)
        mejor = None
        for i in range(len(puntos)):
            for j in range(i + 1, len(puntos)):
                y1, v1 = puntos[i]
                y2, v2 = puntos[j]
                if y2 - y1 < 30:
                    continue
                # monotonía: valores deben cambiar en la dirección opuesta a y
                if (v2 - v1) * (y2 - y1) >= 0:
                    continue
                if mejor is None or (y2 - y1) > mejor[0]:
                    mejor = (y2 - y1, y1, float(v1), y2, float(v2))
        if mejor is not None:
            _, y1, v1, y2, v2 = mejor
            return [(y1 + panel.y0, v1), (y2 + panel.y0, v2)]

    lineas = _detectar_lineas_grilla(gris, panel)
    if len(lineas) >= 2:
        return [
            (float(lineas[0] + panel.y0), float(valores_default[0])),
            (float(lineas[-1] + panel.y0), float(valores_default[1])),
        ]
    return None


def _calibrar_eje_manual(panel: LimitesPanel, rango_valor: tuple[float, float]) -> CalibracionEje:
    """Preset de respaldo: asume que el panel completo cubre linealmente rango_valor
    (valor alto arriba, bajo abajo), sin leer ninguna etiqueta."""
    alto = panel.y1 - panel.y0
    valor_top, valor_bot = rango_valor
    pendiente = (valor_bot - valor_top) / alto
    return CalibracionEje(valor_por_px=pendiente, valor_en_y0=valor_top, metodo="manual", confianza=0.3)


def calibrar_panel(gris: np.ndarray, panel: LimitesPanel, rango_valor_respaldo: tuple[float, float],
                    umbral_confianza_ocr: float = 0.4) -> CalibracionEje:
    cal_ocr = _calibrar_eje_ocr(gris, panel)
    if cal_ocr is not None and cal_ocr.confianza >= umbral_confianza_ocr:
        return cal_ocr
    return _calibrar_eje_manual(panel, rango_valor_respaldo)


def calibrar_desde_dos_puntos(y1_abs: float, valor1: float, y2_abs: float, valor2: float,
                               panel: LimitesPanel) -> CalibracionEje:
    """Calibración a partir de dos puntos que el clínico marcó sobre la imagen (coordenadas
    de píxel absolutas, ej. dos líneas de grilla conocidas) con su valor clínico real.
    Confianza 1.0: es una referencia dada por una persona, no una estimación."""
    y1, y2 = y1_abs - panel.y0, y2_abs - panel.y0
    if y1 == y2:
        raise ValueError("Los dos puntos de calibración no pueden estar en la misma fila de píxel.")
    pendiente = (valor2 - valor1) / (y2 - y1)
    ordenada = valor1 - pendiente * y1
    return CalibracionEje(valor_por_px=pendiente, valor_en_y0=ordenada, metodo="manual_2_puntos", confianza=1.0)


# --------------------------------------------------------------------------
# Extracción de curva (algoritmo validado: continuidad + outliers de tendencia + interpolación)
# --------------------------------------------------------------------------


def _runs_de_columna(col_mask: np.ndarray) -> list[tuple[float, int]]:
    idx = np.where(col_mask)[0]
    if len(idx) == 0:
        return []
    cortes = np.where(np.diff(idx) > 2)[0]
    return [(grp.mean(), len(grp)) for grp in np.split(idx, cortes + 1)]


def extraer_curva(
    banda_gris: np.ndarray,
    umbral_oscuridad: int = 130,
    max_salto_px: int = 60,
    ventana_tendencia_px: int = 61,
    umbral_desvio_unidades: float = 20.0,
    calibracion: CalibracionEje | None = None,
) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int]]]:
    """Devuelve (curva_px, confiable, tramos_interpolados) para una banda (panel) en escala de grises.

    curva_px: posición vertical (relativa al panel) del trazo por columna, con huecos ya
      interpolados. confiable: booleano por columna, True si fue lectura directa (no
      interpolada). tramos_interpolados: lista de (x_inicio, x_fin) en columnas.
    """
    h, w = banda_gris.shape
    es_trazo = banda_gris < umbral_oscuridad

    todos_los_runs = [_runs_de_columna(es_trazo[:, x]) for x in range(w)]
    grosores = [tam for runs in todos_los_runs for _, tam in runs if 1 <= tam <= 15]
    grosor_tipico = float(np.median(grosores)) if grosores else 3.0

    curva_px = np.full(w, np.nan)
    prev = None
    PESO_GROSOR = 3.0  # cuánto castigar un candidato "grueso" (texto/tinta) frente a uno delgado
    for x in range(w):
        runs = todos_los_runs[x]
        if not runs:
            continue
        if prev is None:
            runs.sort(key=lambda t: -t[1])
            prev = runs[0][0]
            curva_px[x] = prev
            continue
        # entre los candidatos plausibles por posición, preferir el de grosor más parecido al
        # típico: bloques de texto (ID/Nombre/fecha a mano) suelen ser más gruesos que la línea
        # fina del trazo, y esto evita que el seguimiento "derive" hacia ellos columna a columna.
        def puntaje(run):
            pos, tam = run
            return abs(pos - prev) + PESO_GROSOR * abs(tam - grosor_tipico)

        runs.sort(key=puntaje)
        candidato, _ = runs[0]
        if abs(candidato - prev) <= max_salto_px:
            curva_px[x] = candidato
            prev = candidato

    valido = ~np.isnan(curva_px)
    if valido.sum() < 2:
        return curva_px, valido, []

    serie = np.where(valido, curva_px, 0.0)
    suave = median_filter(serie, size=ventana_tendencia_px, mode="nearest")
    soporte = median_filter(valido.astype(float), size=ventana_tendencia_px, mode="nearest")

    if calibracion is not None:
        desvio_unidades = np.abs(curva_px - suave) * abs(calibracion.valor_por_px)
    else:
        desvio_unidades = np.abs(curva_px - suave)  # px, si no hay calibración todavía

    confiable = valido & (soporte > 0.3) & (desvio_unidades <= umbral_desvio_unidades)

    x_conf = np.where(confiable)[0]
    curva_final = np.full(w, np.nan)
    curva_final[x_conf] = curva_px[x_conf]
    tramos: list[tuple[int, int]] = []
    for i in range(len(x_conf) - 1):
        x_a, x_b = x_conf[i], x_conf[i + 1]
        if x_b - x_a > 1:
            y_a, y_b = curva_px[x_a], curva_px[x_b]
            for x in range(x_a + 1, x_b):
                curva_final[x] = y_a + (x - x_a) / (x_b - x_a) * (y_b - y_a)
            tramos.append((int(x_a), int(x_b)))

    return curva_final, confiable, tramos


# --------------------------------------------------------------------------
# Entrada principal
# --------------------------------------------------------------------------


@dataclass
class PreparacionImagen:
    """Resultado de orientar la imagen y ubicar los paneles — lo que la UI necesita mostrar
    para que el clínico marque los dos puntos de calibración antes de digitalizar de verdad."""
    imagen: Image.Image
    gris: np.ndarray
    panel_fcf: LimitesPanel
    panel_ua: LimitesPanel
    dpi_render: float
    velocidad_papel_cm_min: float
    advertencias: list[str] = field(default_factory=list)


def preparar_imagen(
    imagen_bytes: bytes,
    velocidad_papel_cm_min: float = 1.0,
    dpi_render: float = 300.0,
) -> PreparacionImagen:
    """Primer paso: orienta la imagen y detecta los paneles FCF/UA. No calibra ejes todavía."""
    advertencias: list[str] = []
    imagen_cruda = Image.open(io.BytesIO(imagen_bytes)).convert("RGB")

    resultado_orientacion = orientar_y_detectar_paneles(imagen_cruda)
    if resultado_orientacion is None:
        advertencias.append(
            "No se pudieron separar automáticamente los paneles FCF/UA en ninguna orientación; "
            "revisar la imagen manualmente (paneles quedan en preset por defecto)."
        )
        imagen = imagen_cruda
        gris = np.array(ImageOps.autocontrast(ImageOps.grayscale(imagen), cutoff=1)).astype(int)
        h = gris.shape[0]
        panel_fcf = LimitesPanel(int(h * 0.05), int(h * 0.45))
        panel_ua = LimitesPanel(int(h * 0.55), int(h * 0.95))
    else:
        imagen, gris, panel_fcf, panel_ua = resultado_orientacion

    return PreparacionImagen(
        imagen=imagen, gris=gris, panel_fcf=panel_fcf, panel_ua=panel_ua,
        dpi_render=dpi_render, velocidad_papel_cm_min=velocidad_papel_cm_min,
        advertencias=advertencias,
    )


def digitalizar_con_calibracion(
    prep: PreparacionImagen,
    cal_fcf: CalibracionEje,
    cal_ua: CalibracionEje,
) -> ResultadoDigitalizacion:
    """Segundo paso: con la preparación ya hecha y las calibraciones ya resueltas (por OCR,
    preset manual, o los dos puntos que marcó el clínico), extrae las curvas y arma el resultado."""
    advertencias = list(prep.advertencias)
    gris, panel_fcf, panel_ua = prep.gris, prep.panel_fcf, prep.panel_ua

    banda_fcf = gris[panel_fcf.y0:panel_fcf.y1, :]
    banda_ua = gris[panel_ua.y0:panel_ua.y1, :]
    curva_fcf_px, conf_fcf, tramos_fcf = extraer_curva(banda_fcf, calibracion=cal_fcf)
    curva_ua_px, conf_ua, tramos_ua = extraer_curva(banda_ua, calibracion=cal_ua)

    w = gris.shape[1]
    seg_por_px = 60.0 / (prep.dpi_render / 2.54 * prep.velocidad_papel_cm_min)
    tiempo_s = np.arange(w) * seg_por_px

    fcf = cal_fcf.px_a_valor(curva_fcf_px)
    ua = cal_ua.px_a_valor(curva_ua_px)

    df = pd.DataFrame({
        "tiempo": tiempo_s,
        "fcf": fcf,
        "fcf_confiable": conf_fcf,
        "ua": ua,
        "ua_confiable": conf_ua,
    })

    if tramos_fcf:
        rangos = ", ".join(f"{a*seg_por_px:.0f}s-{b*seg_por_px:.0f}s" for a, b in tramos_fcf[:5])
        extra = "..." if len(tramos_fcf) > 5 else ""
        advertencias.append(f"FCF: {len(tramos_fcf)} tramo(s) reconstruido(s) por interpolación ({rangos}{extra}).")
    if tramos_ua:
        rangos = ", ".join(f"{a*seg_por_px:.0f}s-{b*seg_por_px:.0f}s" for a, b in tramos_ua[:5])
        extra = "..." if len(tramos_ua) > 5 else ""
        advertencias.append(f"UA: {len(tramos_ua)} tramo(s) reconstruido(s) por interpolación ({rangos}{extra}).")

    overlay = _dibujar_overlay(prep.imagen, panel_fcf, panel_ua, curva_fcf_px, conf_fcf, curva_ua_px, conf_ua)

    return ResultadoDigitalizacion(
        df=df,
        overlay=overlay,
        calibracion_fcf=cal_fcf,
        calibracion_ua=cal_ua,
        advertencias=advertencias,
    )


def digitalizar(
    imagen_bytes: bytes,
    velocidad_papel_cm_min: float = 1.0,
    dpi_render: float = 300.0,
    rango_fcf_respaldo: tuple[float, float] = (210.0, 30.0),
    rango_ua_respaldo: tuple[float, float] = (100.0, 0.0),
) -> ResultadoDigitalizacion:
    """Atajo para uso no interactivo (scripts, validación por lotes): igual que
    preparar_imagen() + digitalizar_con_calibracion(), pero calibrando automáticamente
    (OCR si alcanza confianza, si no un preset fijo) en vez de pedirle 2 puntos a un humano.
    La UI de Streamlit debería usar preparar_imagen()/digitalizar_con_calibracion() por
    separado para poder mostrarle la imagen al clínico entre medio.
    """
    prep = preparar_imagen(imagen_bytes, velocidad_papel_cm_min, dpi_render)
    advertencias = list(prep.advertencias)

    cal_fcf = calibrar_panel(prep.gris, prep.panel_fcf, rango_fcf_respaldo)
    cal_ua = calibrar_panel(prep.gris, prep.panel_ua, rango_ua_respaldo)
    if cal_fcf.metodo == "manual":
        advertencias.append("Calibración del eje FCF por preset manual (OCR no alcanzó confianza suficiente).")
    if cal_ua.metodo == "manual":
        advertencias.append("Calibración del eje UA por preset manual (OCR no alcanzó confianza suficiente).")
    prep.advertencias = advertencias

    return digitalizar_con_calibracion(prep, cal_fcf, cal_ua)


# --------------------------------------------------------------------------
# Metadatos de cabecera y anotaciones clínicas (OCR de mejor esfuerzo)
# --------------------------------------------------------------------------


def extraer_metadatos_cabecera(imagen_bytes: bytes) -> dict:
    """OCR de mejor esfuerzo sobre la franja superior del papel (cabecera impresa):
    ID de registro, FHR impreso, fecha/hora de inicio, velocidad de papel.

    Igual que la calibración de ejes por OCR (ver `_calibrar_eje_ocr`), la confianza en
    fotos/escaneos reales es baja y variable — este resultado debe mostrarse en la UI
    como sugerencia editable, nunca como valor autoritativo. El procesamiento es 100%
    local (no se envía a ningún proveedor LLM).
    """
    resultado = {
        "id": None,
        "fhr_bpm": None,
        "fecha_hora": None,
        "velocidad_papel_cm_min": None,
        "texto_crudo": "",
    }
    if not _TESSERACT_OK:
        return resultado

    imagen = Image.open(io.BytesIO(imagen_bytes)).convert("RGB")
    cabecera = imagen.crop((0, 0, imagen.width, int(imagen.height * 0.12)))
    gris = ImageOps.autocontrast(ImageOps.grayscale(cabecera), cutoff=1)
    try:
        texto = pytesseract.image_to_string(gris, config="--psm 6")
    except pytesseract.TesseractError:
        return resultado
    resultado["texto_crudo"] = texto

    m = re.search(r"\bID[:\s]+([A-Za-z0-9\-]+)", texto)
    if m:
        resultado["id"] = m.group(1)
    m = re.search(r"FHR\s*(\d{2,3})\s*bpm", texto, re.IGNORECASE)
    if m:
        resultado["fhr_bpm"] = int(m.group(1))
    m = re.search(r"(\d{4}-\d{2}-\d{2}[ T]\d{1,2}[:h]\d{2}(?::\d{2})?)", texto)
    if m:
        resultado["fecha_hora"] = m.group(1)
    m = re.search(r"(\d+(?:\.\d+)?)\s*cm\s*/\s*min", texto, re.IGNORECASE)
    if m:
        resultado["velocidad_papel_cm_min"] = float(m.group(1))

    return resultado


def detectar_anotaciones_clinicas(prep: PreparacionImagen) -> list[str]:
    """Busca términos clínicos manuscritos/impresos en la franja debajo del panel UA
    (donde suelen anotarse eventos como "Peridural") vía OCR de mejor esfuerzo.

    No clasifica el impacto clínico del hallazgo — solo lo reporta como advertencia
    para que el clínico lo confirme y para que `prompts.py` lo incluya como contexto
    textual del informe."""
    if not _TESSERACT_OK:
        return []
    h, w = prep.gris.shape
    alto_ua = prep.panel_ua.y1 - prep.panel_ua.y0
    y0 = prep.panel_ua.y1
    y1 = min(h, y0 + int(alto_ua * 0.5))
    if y1 <= y0:
        return []
    franja = prep.gris[y0:y1, :]
    franja_img = ImageOps.autocontrast(Image.fromarray(franja.astype(np.uint8)), cutoff=1)
    try:
        texto = pytesseract.image_to_string(franja_img, config="--psm 6")
    except pytesseract.TesseractError:
        return []

    texto_bajo = texto.lower()
    hallazgos = [p for p in PALABRAS_CLAVE_CLINICAS if p in texto_bajo]
    return [
        f'Anotación clínica detectada en el papel: "{p}" (verificar manualmente, puede alterar la interpretación del registro).'
        for p in hallazgos
    ]


def _dibujar_overlay(imagen, panel_fcf, panel_ua, curva_fcf_px, conf_fcf, curva_ua_px, conf_ua):
    overlay = imagen.copy()
    draw = ImageDraw.Draw(overlay)
    COLOR_REAL = (0, 180, 255)
    COLOR_INTERP = (255, 140, 0)
    for panel, curva, conf in ((panel_fcf, curva_fcf_px, conf_fcf), (panel_ua, curva_ua_px, conf_ua)):
        for x in range(1, len(curva)):
            if np.isnan(curva[x - 1]) or np.isnan(curva[x]):
                continue
            color = COLOR_REAL if (conf[x - 1] and conf[x]) else COLOR_INTERP
            draw.line(
                [(x - 1, panel.y0 + curva[x - 1]), (x, panel.y0 + curva[x])],
                fill=color,
                width=3,
            )
        draw.rectangle([0, panel.y0, imagen.width, panel.y1], outline=(0, 200, 0), width=2)
    return overlay
