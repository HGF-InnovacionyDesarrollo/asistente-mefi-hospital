"""Funciones puras y verificables de soporte UX, seguridad de calibración,
formateo clínico de eventos y generación de trazado sintético de entrenamiento.

Separar esta lógica de `src/app.py` permite probarla unitariamente con pytest
sin depender del runtime interactivo de Streamlit.
"""

from __future__ import annotations

import io
import math
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw


# Valores rápidos estándar impresos en papel de monitoreo fetal (FCF y UA)
PRESETS_LINEA_1_FCF: tuple[int, ...] = (210, 180, 150, 120)
PRESETS_LINEA_2_FCF: tuple[int, ...] = (90, 60, 50, 30)
PRESETS_LINEA_1_UA: tuple[int, ...] = (100, 80, 60, 50)
PRESETS_LINEA_2_UA: tuple[int, ...] = (40, 25, 20, 0)


def validar_estado_calibracion(
    y1_abs: float,
    valor1: float,
    y2_abs: float,
    valor2: float,
    min_separacion_px: float = 15.0,
) -> dict[str, Any]:
    """Valida que las dos líneas de calibración sean físicamente coherentes antes
    de digitalizar el trazado.

    Reglas de seguridad clínica:
    1. `valor1` y `valor2` no pueden ser iguales (división por cero en la escala).
    2. Las dos líneas deben tener al menos `min_separacion_px` píxeles de distancia
       vertical para que un pequeño error de pulso no distorsione toda la curva.
    3. En todo papel CTG estándar, los valores mayores están ARRIBA (menor `y`) y
       los valores menores están ABAJO (mayor `y`). Si el usuario cruzó las líneas
       o invirtió los números (`(y2 - y1) * (valor1 - valor2) <= 0`), se bloquea
       la calibración y se informa cómo corregirlo con 1 clic.
    """
    if math.isclose(valor1, valor2, abs_tol=1e-6):
        return {
            "valido": False,
            "codigo": "valores_iguales",
            "mensaje": (
                "Ambas líneas tienen el mismo número asignado. "
                "Selecciona dos líneas con números distintos en el papel (ej. 210 arriba y 30 abajo)."
            ),
        }

    sep_px = abs(y2_abs - y1_abs)
    if sep_px < min_separacion_px:
        return {
            "valido": False,
            "codigo": "lineas_muy_juntas",
            "mensaje": (
                f"Las líneas Azul y Roja están demasiado juntas ({sep_px:.0f} px). "
                "Arrástralas hacia dos líneas más separadas del papel para asegurar precisión."
            ),
        }

    # En coordenadas de imagen, y crece hacia abajo:
    # Si y2 > y1 (Línea 2 está más abajo que Línea 1), entonces valor1 debe ser > valor2.
    if (y2_abs - y1_abs) * (valor1 - valor2) <= 0:
        return {
            "valido": False,
            "codigo": "escala_invertida",
            "mensaje": (
                "La escala está invertida: en el papel de monitoreo el número mayor siempre va "
                "arriba y el número menor va abajo. Intercambia las posiciones de las líneas o "
                "usa el botón «🔄 Intercambiar valores Azul ↔ Roja»."
            ),
        }

    return {
        "valido": True,
        "codigo": "ok",
        "mensaje": "Escala coherente y validada.",
    }


def calcular_calidad_lectura(df: pd.DataFrame) -> dict[str, Any]:
    """Calcula indicadores legibles de calidad de lectura sobre el DataFrame digitalizado.

    Devuelve porcentaje de lectura directa en FCF y UA, duración total en minutos
    y nivel de confianza ('alta', 'media', 'baja') para mostrar al clínico en la
    sección de auditoría de la curva.
    """
    if df is None or df.empty:
        return {
            "pct_fcf_directa": 0.0,
            "pct_interpolado": 100.0,
            "duracion_min": 0.0,
            "nivel": "baja",
            "resumen": "Sin datos digitalizados.",
        }

    if "fcf_confiable" in df.columns and len(df) > 0:
        pct_directa = float(np.mean(df["fcf_confiable"].astype(bool)) * 100.0)
    else:
        pct_directa = 100.0
    pct_interp = max(0.0, 100.0 - pct_directa)

    if "tiempo" in df.columns and len(df) >= 2:
        duracion_s = float(df["tiempo"].iloc[-1] - df["tiempo"].iloc[0])
    else:
        duracion_s = 0.0
    duracion_min = duracion_s / 60.0

    if pct_directa >= 85.0:
        nivel = "alta"
        etiqueta = "🟢 Lectura nítida del trazado"
    elif pct_directa >= 65.0:
        nivel = "media"
        etiqueta = "🟡 Lectura aceptable con tramos interpolados"
    else:
        nivel = "baja"
        etiqueta = "🔴 Lectura con alta proporción interpolada — verifique calibración o nitidez"

    resumen = (
        f"{etiqueta}: **{pct_directa:.1f}%** lectura directa · "
        f"**{pct_interp:.1f}%** reconstruido por interpolación · "
        f"Duración analizada: **{duracion_min:.1f} min**."
    )
    return {
        "pct_fcf_directa": round(pct_directa, 1),
        "pct_interpolado": round(pct_interp, 1),
        "duracion_min": round(duracion_min, 1),
        "nivel": nivel,
        "resumen": resumen,
    }


def _formatear_mm_ss(segundos: float) -> str:
    """Convierte segundos a formato clínico legible `MM:SS min`."""
    seg_tot = max(0, int(round(segundos)))
    minutos = seg_tot // 60
    seg = seg_tot % 60
    return f"{minutos:02d}:{seg:02d}"


def formatear_tabla_desaceleraciones(desaceleraciones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Transforma la lista técnica de desaceleraciones de `clinical.py` en filas
    legibles para profesionales clínicos (sin claves crudas de programación),
    incluyendo en MEFI v2.0 los Criterios «60» (para desaceleraciones variables)
    y la variabilidad intra-evento (en desaceleraciones prolongadas ≥2 min).
    """
    if not desaceleraciones:
        return []

    mapa_tipo = {
        "precoz": "Precoz (simétrica/cefálica)",
        "tardia": "Tardía (desfasada/uteroplacentaria)",
        "variable": "Variable (abrupta/cordón)",
        "indeterminada": "Indeterminada",
    }
    filas: list[dict[str, Any]] = []
    for idx, ev in enumerate(desaceleraciones, start=1):
        t_ini = float(ev.get("inicio_s", ev.get("t_inicio_s", 0.0)))
        t_fin = float(ev.get("fin_s", ev.get("t_fin_s", t_ini)))
        dur = float(ev.get("duracion_s", max(0.0, t_fin - t_ini)))
        amp = float(ev.get("amplitud_max_lpm", 0.0))
        nadir = ev.get("nadir_lpm")
        tipo_raw = str(ev.get("tipo", "indeterminada")).lower()
        es_prol = bool(ev.get("prolongada", False)) or dur >= 120.0
        muy_prol = bool(ev.get("muy_prolongada", False)) or dur >= 300.0

        # Criterios «60» (Protocolo V2) para desaceleraciones variables
        if tipo_raw == "variable":
            crit_60 = ev.get("criterios_60_cumplidos")
            if crit_60 is None:
                crit_60 = []
                if dur > 60.0:
                    crit_60.append("duración >60s")
                if nadir is not None and float(nadir) < 60.0:
                    crit_60.append("nadir <60 lpm")
                if amp > 60.0:
                    crit_60.append("caída >60 lpm")
            if len(crit_60) >= 2:
                txt_c60 = f"🔴 {len(crit_60)}/3 ({', '.join(crit_60)})"
            elif len(crit_60) == 1:
                txt_c60 = f"🟡 1/3 ({crit_60[0]})"
            else:
                txt_c60 = "🟢 0/3"
        else:
            txt_c60 = "— (No variable)"

        # Variabilidad intra-evento (Fase B6: eventos >=2 min)
        var_intra = ev.get("variabilidad_intra_lpm")
        var_red_intra = bool(ev.get("variabilidad_reducida_intra_evento", False))
        if es_prol and var_intra is not None:
            txt_var_intra = (
                f"🔴 Reducida ({var_intra:.1f} lpm <5)"
                if var_red_intra
                else f"🟢 Conservada ({var_intra:.1f} lpm)"
            )
        elif es_prol:
            txt_var_intra = "🔴 Reducida (<5 lpm)" if var_red_intra else "🟢 Conservada"
        else:
            txt_var_intra = "— (<2 min)"

        if muy_prol:
            txt_prol = "🔴 Muy prolongada (≥5 min)"
        elif es_prol:
            txt_prol = "🟡 Prolongada (≥2 min)"
        else:
            txt_prol = "🟢 No"

        filas.append({
            "N°": idx,
            "Inicio (mm:ss)": _formatear_mm_ss(t_ini),
            "Fin (mm:ss)": _formatear_mm_ss(t_fin),
            "Duración (s)": f"{dur:.0f} s",
            "Caída máx. (lpm)": f"-{amp:.0f} lpm",
            "Clasificación": mapa_tipo.get(tipo_raw, tipo_raw.capitalize()),
            "Criterios «60» (Variables)": txt_c60,
            "Variabilidad intra-evento (≥2 min)": txt_var_intra,
            "Alerta prolongada (≥2 min)": txt_prol,
            "Alerta prolongada (>3 min)": "🔴 Sí (>3 min)" if muy_prol else "🟢 No",
        })
    return filas


def generar_imagen_ctg_demo(ancho: int = 1600, alto: int = 760) -> bytes:
    """Genera en memoria una imagen PNG de un trazado CTG sintético 100% libre de
    datos de pacientes reales, con cuadrícula hospitalaria impresa, etiquetas de
    escala claras (FCF: 210..30 lpm; UA: 100..0), línea base ~140 lpm con
    variabilidad fisiológica, aceleraciones reactivas y contracciones uterinas.

    Diseñada para el botón «🧪 Cargar trazado de ejemplo para practicar» (Bloque C).
    """
    img = Image.new("RGB", (ancho, alto), color=(252, 250, 247))
    draw = ImageDraw.Draw(img)

    # Geometría de los dos paneles separados por una franja blanca (para que
    # `_detectar_paneles_por_perfil` en `digitizer.py` los separe con precisión).
    y_fcf_0, y_fcf_1 = 45, 365
    y_ua_0, y_ua_1 = 435, 715

    color_grilla_fina = (244, 214, 214)
    color_grilla_gruesa = (228, 175, 175)
    color_texto = (140, 60, 60)

    # Cuadrícula vertical (tiempo)
    for x in range(0, ancho, 20):
        es_gruesa = (x % 100) == 0
        c = color_grilla_gruesa if es_gruesa else color_grilla_fina
        draw.line([(x, y_fcf_0), (x, y_fcf_1)], fill=c, width=1)
        draw.line([(x, y_ua_0), (x, y_ua_1)], fill=c, width=1)

    # Cuadrícula horizontal Panel FCF (210 a 30 lpm)
    valores_fcf = [210, 180, 150, 120, 90, 60, 30]
    for v in range(210, 29, -10):
        frac = (210.0 - v) / (210.0 - 30.0)
        y = int(round(y_fcf_0 + 20 + frac * (y_fcf_1 - y_fcf_0 - 40)))
        es_etiqueta = v in valores_fcf
        c = color_grilla_gruesa if es_etiqueta else color_grilla_fina
        draw.line([(0, y), (ancho, y)], fill=c, width=2 if es_etiqueta else 1)
        if es_etiqueta:
            for x_lbl in (18, 420, 820, 1220):
                draw.text((x_lbl, y - 11), str(v), fill=color_texto)

    # Cuadrícula horizontal Panel UA (100 a 0 mmHg/%)
    valores_ua = [100, 80, 60, 40, 20, 0]
    for v in range(100, -1, -10):
        frac = (100.0 - v) / 100.0
        y = int(round(y_ua_0 + 20 + frac * (y_ua_1 - y_ua_0 - 40)))
        es_etiqueta = v in valores_ua
        c = color_grilla_gruesa if es_etiqueta else color_grilla_fina
        draw.line([(0, y), (ancho, y)], fill=c, width=2 if es_etiqueta else 1)
        if es_etiqueta:
            for x_lbl in (18, 420, 820, 1220):
                draw.text((x_lbl, y - 11), str(v), fill=color_texto)

    # Cabecera sintética de demostración
    draw.text((20, 12), "REGISTRO DEMO SINTETICO - ID: demo-practica   2026-11-09 09:00   1cm/min", fill=(60, 60, 60))

    # Trazo sintético negro de FCF (basal 140 lpm + variabilidad normal + 2 aceleraciones)
    rng = np.random.default_rng(42)
    xs = np.arange(60, ancho - 20)
    t = (xs - 60) / float(ancho - 80) * 1200.0  # ~20 min
    fcf = (
        140.0
        + 5.5 * np.sin(2 * np.pi * t / 24.0)
        + 2.5 * np.sin(2 * np.pi * t / 9.0)
        + rng.normal(0, 1.2, size=len(t))
    )
    # Dos aceleraciones reactivas (+20 lpm durante ~35 s)
    for t_acc in (320.0, 820.0):
        fcf += 22.0 * np.exp(-0.5 * ((t - t_acc) / 16.0) ** 2)

    pts_fcf = []
    for x_px, val_fcf in zip(xs, fcf):
        frac = (210.0 - float(val_fcf)) / (210.0 - 30.0)
        y_px = int(round(y_fcf_0 + 20 + frac * (y_fcf_1 - y_fcf_0 - 40)))
        pts_fcf.append((int(x_px), y_px))
    draw.line(pts_fcf, fill=(20, 20, 25), width=3)

    # Trazo sintético negro de UA (tono basal 12 + 3 contracciones regulares)
    ua = 12.0 + 1.5 * np.sin(2 * np.pi * t / 18.0)
    for t_c in (260.0, 640.0, 1020.0):
        ua += 55.0 * np.exp(-0.5 * ((t - t_c) / 28.0) ** 2)

    pts_ua = []
    for x_px, val_ua in zip(xs, ua):
        frac = (100.0 - float(val_ua)) / 100.0
        y_px = int(round(y_ua_0 + 20 + frac * (y_ua_1 - y_ua_0 - 40)))
        pts_ua.append((int(x_px), y_px))
    draw.line(pts_ua, fill=(20, 20, 25), width=3)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

