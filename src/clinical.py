"""Cálculo de variables clínicas CTG/MEFI (FIGO 2015 / NICE NG229) a partir del
DataFrame digitalizado por `digitizer.py` (columnas: tiempo, fcf, fcf_confiable,
ua, ua_confiable).

Funciones puras sobre DataFrames — sin dependencia de Streamlit ni de ningún LLM.
Esto es justo lo que se valida en la Fase 4 del plan contra el outcome real
(pH de cordón, dataset CTU-UHB): si esta lógica cambia, hay que volver a correr
esa validación.

Los umbrales usados son los de FIGO 2015 y NICE NG229 (mismos números que en el
plan: C:\\Users\\usuariohgf\\.claude\\plans\\composed-sniffing-moler.md, Fase 2).
Es una implementación simplificada para MVP — no reemplaza el juicio clínico ni
cubre cada matiz de las guías (ver disclaimer de la Fase 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.ndimage import median_filter
from scipy.signal import butter, filtfilt, find_peaks

# --------------------------------------------------------------------------
# Umbrales clínicos (FIGO 2015 / NICE NG229)
# --------------------------------------------------------------------------

BASAL_MIN_NORMAL = 110  # lpm
BASAL_MAX_NORMAL = 160  # lpm

VARIABILIDAD_REDUCIDA_MAX = 5  # lpm (banda de amplitud pico-a-pico; FIGO 2015 / NICE NG229)
VARIABILIDAD_NORMAL_MAX = 25  # lpm
# NICHD 2008 / ACOG CPG No. 10 (Obstet Gynecol 2025;146:583-599, Table 1):
# Variabilidad "ausente" = amplitud indetectable (operacionalizada como <1.0 lpm de mediana).
# En Fase A solo alimenta `clasificar_acog_estricta()` (A5) y `evaluar_riesgo_categoria_ii()` (A2);
# NO altera `clasificar_figo()`.
VARIABILIDAD_AUSENTE_MAX_LPM = 1.0
MIN_COINCIDENCIAS_FCF_MATERNA = 2  # ACOG CPG No. 10 / Protocolo V2 Supuesto 5: >=2 aceleraciones en pico de UA

UMBRAL_ACEL_DECEL = 15  # lpm respecto de la línea base (>=32 semanas)
DURACION_MIN_EVENTO_S = 15  # seg (>=32 semanas)
# ACOG CPG No. 10 (Obstet Gynecol 2025;146:583-599, Table 1) y Protocolo V2 (sept. 2025):
# Antes de las 32 semanas de gestación, una aceleración se define como >=10 lpm sobre la basal por >=10s.
# Entre 2 y 10 minutos (120-600s) se define como "aceleración prolongada" (>=10 min es cambio de línea base).
EDAD_GESTACIONAL_PRETERMINO_LIMITE_SEM = 32.0
UMBRAL_ACEL_PRETERMINO = 10  # lpm (<32 semanas; ACOG Tabla 1 / Protocolo V2)
DURACION_MIN_ACEL_PRETERMINO_S = 10  # seg (<32 semanas; ACOG Tabla 1 / Protocolo V2)
ACELERACION_PROLONGADA_MIN_S = 120  # >=2 min y <=10 min: "aceleración prolongada" (ACOG Tabla 1)
DURACION_MAX_ACELERACION_S = 600  # 10 min

ONSET_ABRUPTO_MAX_S = 30  # <30s inicio->nadir/pico = abrupto; si no, gradual
# ACOG CPG No. 10 (Obstet Gynecol 2025;146:583-599, Table 1) y Protocolo V2 (sept. 2025):
# Desaceleración prolongada = caída >=15 lpm que dura >=2 min (120s) y <10 min.
DESACEL_PROLONGADA_MIN_S = 120  # >=2 min (120s): "prolongada" (ACOG Tabla 1 / Protocolo V2)
DESACEL_MUY_PROLONGADA_S = 300  # >=5 min (300s): criterio patológico directo MEFI/FIGO 2015

TOLERANCIA_COINCIDENCIA_S = 20  # ventana para asociar nadir de desaceleración con pico de UA
TOLERANCIA_ASOCIACION_CONTRACCION_S = 90  # ventana (más laxa) para saber si una desaceleración
# ocurrió "con" una contracción, sin importar el tipo — usado para el criterio de
# "repetitivas" de FIGO (>50% de las contracciones), no para la subclasificación precoz/tardía

# ACOG CPG No. 10 (Obstet Gynecol 2025;146:583-599, Table 1): patrón sinusoidal
# requiere oscilación sinusoidal suave de 3-5 ciclos/min que persiste >=20 minutos (1200s).
# Nota: el Protocolo V2 institucional (sept. 2025) exige >30 min (1800s) con ausencia de aceleraciones.
SINUSOIDAL_DURACION_MIN_S = 1200  # 20 min continuos mínimos (ACOG Tabla 1)
SINUSOIDAL_DURACION_PROTOCOLO_V2_S = 1800  # 30 min (Protocolo V2 institucional)
SINUSOIDAL_FRECUENCIA_MIN_CPM = 3.0
SINUSOIDAL_FRECUENCIA_MAX_CPM = 5.0
SINUSOIDAL_AMPLITUD_MIN = 5.0
SINUSOIDAL_AMPLITUD_MAX = 15.0

# ACOG CPG No. 10 (Obstet Gynecol 2025;146:583-599, Table 1) y Protocolo V2 (sept. 2025):
# Taquisistolía = >5 contracciones en 10 minutos, promediadas sobre una ventana de 30 minutos (1800s).
# NICE NG229 §1.4.12: >=5 contracciones en 10 min (usado además como respaldo cuando el trazado dura <30 min).
TAQUISISTOLIA_VENTANA_ACOG_S = 1800.0
TAQUISISTOLIA_UMBRAL_ACOG_10MIN = 5.0
TAQUISISTOLIA_UMBRAL_NICE_10MIN = 5.0

# Protocolo de Vigilancia del Bienestar Fetal Intraparto V2 (sept. 2025) — Fase C:
# Criterios «60» en desaceleraciones variables: duración >60s, nadir <60 lpm, caída >60 lpm.
# Alerta de riesgo independiente si >=2 criterios se cumplen durante más de 30 minutos (1800s).
CRITERIO_60_DURACION_S = 60.0
CRITERIO_60_NADIR_LPM = 60.0
CRITERIO_60_CAIDA_LPM = 60.0
CRITERIO_60_PERSISTENCIA_S = 1800.0
HIPOXIA_CRONICA_BASAL_ALTA_LPM = 150.0  # línea base en límite alto para tipificación de hipoxia crónica


# --------------------------------------------------------------------------
# Línea base
# --------------------------------------------------------------------------


def calcular_linea_base(df: pd.DataFrame) -> float:
    """FCF basal: mediana sobre segmentos estables, excluyendo de forma iterativa
    los puntos que se apartan >=UMBRAL_ACEL_DECEL de la mediana vigente (candidatos
    a aceleración/desaceleración), hasta converger. Redondeada a los 5 lpm más
    cercanos, como es convención clínica.
    """
    fcf = df.loc[df["fcf_confiable"].astype(bool), "fcf"].dropna()
    if fcf.empty:
        raise ValueError("No hay puntos de FCF confiables para calcular la línea base.")

    basal = float(fcf.median())
    for _ in range(5):
        estables = fcf[(fcf - basal).abs() < UMBRAL_ACEL_DECEL]
        if len(estables) < max(10, len(fcf) * 0.2):
            break
        nueva = float(estables.median())
        if abs(nueva - basal) < 0.5:
            basal = nueva
            break
        basal = nueva

    return round(basal / 5) * 5


# --------------------------------------------------------------------------
# Variabilidad
# --------------------------------------------------------------------------


def calcular_variabilidad(df: pd.DataFrame, basal: float, ventana_s: float = 60.0) -> dict:
    """Banda de amplitud (máximo - mínimo) de FCF por ventana de ~1 minuto,
    excluyendo tramos de aceleración/desaceleración (se computa sobre la
    oscilación alrededor de la línea base, no sobre el evento completo).

    Categorías NICE NG229 / FIGO 2015 (`categoria`, retrocompatible):
      - <5 lpm: "reducida"
      - 5-25 lpm: "normal"
      - >25 lpm: "aumentada"

    Categorías NICHD 2008 / ACOG CPG No. 10 Tabla 1 (`categoria_nichd`, Fase B5):
      - <1.0 lpm: "ausente" (amplitud indetectable)
      - 1.0 a 5.0 lpm: "minima" (<=5 lpm detectable)
      - >5.0 a 25.0 lpm: "moderada" (6-25 lpm)
      - >25.0 lpm: "marcada" (>25 lpm)
    """
    sub = df.loc[df["fcf_confiable"].astype(bool)].sort_values("tiempo").copy()
    if sub.empty:
        return {
            "amplitud_media_lpm": 0.0,
            "categoria": "reducida",
            "categoria_nichd": "ausente",
            "subcategoria_nichd": "ausente",
            "ventanas_evaluadas": 0,
        }

    # Excluir tramos que ya son aceleración/desaceleración propiamente dicha (>=15s
    # sostenidos), no cualquier punto que exceda el umbral — una oscilación rápida
    # de baja duración es justo la variabilidad que se quiere medir, no un evento.
    # Se excluye con margen (± ventana_s) a cada lado del evento detectado: el
    # cruce de umbral que define inicio/fin del evento queda a mitad de la rampa
    # real de subida/bajada, así que sin margen la rampa "sobrante" fuera del
    # evento seguiría inflando la variabilidad de las ventanas vecinas.
    eventos = detectar_aceleraciones(df, basal) + detectar_desaceleraciones(
        df, basal, incluir_subclasificacion=False
    )
    tiempos = sub["tiempo"].to_numpy()
    mask_evento = np.zeros(len(sub), dtype=bool)
    for ev in eventos:
        mask_evento |= (tiempos >= ev["inicio_s"] - ventana_s) & (tiempos <= ev["fin_s"] + ventana_s)
    sub = sub.loc[~mask_evento]

    if sub.empty:
        return {
            "amplitud_media_lpm": 0.0,
            "categoria": "reducida",
            "categoria_nichd": "ausente",
            "subcategoria_nichd": "ausente",
            "ventanas_evaluadas": 0,
        }

    bins = (sub["tiempo"] // ventana_s).astype(int)
    amplitudes = sub.groupby(bins)["fcf"].agg(lambda s: s.max() - s.min() if len(s) >= 2 else np.nan)
    amplitudes = amplitudes.dropna()

    # Mediana, no promedio: unas pocas ventanas ruidosas (dropout de sensor no del
    # todo filtrado, artefacto puntual) inflan el promedio del trazado completo y
    # lo categorizan "aumentada" aunque la mayoría de las ventanas sean normales.
    # La mediana refleja el patrón predominante, que es lo que NICE NG229 evalúa
    # (variabilidad sostenida, no picos aislados).
    amplitud_repr = float(amplitudes.median()) if len(amplitudes) else 0.0

    if amplitud_repr < VARIABILIDAD_REDUCIDA_MAX:
        categoria = "reducida"
    elif amplitud_repr <= VARIABILIDAD_NORMAL_MAX:
        categoria = "normal"
    else:
        categoria = "aumentada"

    if amplitud_repr < VARIABILIDAD_AUSENTE_MAX_LPM:
        categoria_nichd = "ausente"
    elif amplitud_repr <= VARIABILIDAD_REDUCIDA_MAX:
        categoria_nichd = "minima"
    elif amplitud_repr <= VARIABILIDAD_NORMAL_MAX:
        categoria_nichd = "moderada"
    else:
        categoria_nichd = "marcada"

    return {
        "amplitud_media_lpm": round(amplitud_repr, 1),
        "categoria": categoria,
        "categoria_nichd": categoria_nichd,
        "subcategoria_nichd": categoria_nichd,
        "ventanas_evaluadas": int(len(amplitudes)),
    }


# --------------------------------------------------------------------------
# Eventos: aceleraciones / desaceleraciones
# --------------------------------------------------------------------------


def _agrupar_en_eventos(mask: pd.Series, tiempo: pd.Series) -> list[tuple[float, float]]:
    """Agrupa una máscara booleana (indexada como `tiempo`) en tramos contiguos
    de tiempo (inicio_s, fin_s)."""
    eventos = []
    en_evento = False
    inicio = None
    prev_t = None
    for t, activo in zip(tiempo, mask):
        if activo and not en_evento:
            en_evento = True
            inicio = t
        elif not activo and en_evento:
            en_evento = False
            eventos.append((inicio, prev_t))
        prev_t = t
    if en_evento:
        eventos.append((inicio, prev_t))
    return eventos


def _parsear_edad_gestacional_sem(valor: float | int | str | None) -> float | None:
    """Convierte una edad gestacional numérica o textual (ej. '31+4 sem', '38 semanas', 30.5)
    a semanas flotantes. Devuelve None si no es interpretable."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        v = float(valor)
        return v if 15.0 <= v <= 46.0 else None
    import re

    m = re.search(r"(\d{2})(?:[.,](\d+)|\s*\+\s*(\d))?", str(valor))
    if not m:
        return None
    sem = float(m.group(1))
    if m.group(2):
        sem += float(f"0.{m.group(2)}")
    elif m.group(3):
        sem += float(m.group(3)) / 7.0
    return sem if 15.0 <= sem <= 46.0 else None


def detectar_aceleraciones(
    df: pd.DataFrame,
    basal: float,
    edad_gestacional_sem: float | int | str | None = None,
    umbral_lpm: float | None = None,
    duracion_min_s: float | None = None,
) -> list[dict]:
    """Aumentos sobre la línea base de hasta 10 min de duración.
    Por defecto usa >=15 lpm por >=15s (>=32 semanas). Si `edad_gestacional_sem < 32`
    (ACOG CPG No. 10 Tabla 1 / Protocolo V2), usa >=10 lpm por >=10s.
    Etiqueta como `prolongada=True` (`etiqueta="aceleración prolongada"`) las de 2 a 10 min (120-600s).
    """
    sub = df.loc[df["fcf_confiable"].astype(bool)].sort_values("tiempo")
    if sub.empty:
        return []

    eg_num = _parsear_edad_gestacional_sem(edad_gestacional_sem)
    es_pretermino = eg_num is not None and eg_num < EDAD_GESTACIONAL_PRETERMINO_LIMITE_SEM

    umbral_ef = (
        float(umbral_lpm)
        if umbral_lpm is not None
        else float(UMBRAL_ACEL_PRETERMINO if es_pretermino else UMBRAL_ACEL_DECEL)
    )
    dur_min_ef = (
        float(duracion_min_s)
        if duracion_min_s is not None
        else float(DURACION_MIN_ACEL_PRETERMINO_S if es_pretermino else DURACION_MIN_EVENTO_S)
    )

    mask = sub["fcf"] >= basal + umbral_ef
    eventos = []
    for inicio, fin in _agrupar_en_eventos(mask, sub["tiempo"]):
        duracion = fin - inicio
        if duracion < dur_min_ef or duracion > DURACION_MAX_ACELERACION_S:
            continue
        tramo = sub[(sub["tiempo"] >= inicio) & (sub["tiempo"] <= fin)]
        es_prolongada = bool(duracion >= ACELERACION_PROLONGADA_MIN_S)
        eventos.append({
            "inicio_s": float(inicio),
            "fin_s": float(fin),
            "duracion_s": float(duracion),
            "amplitud_max_lpm": float(tramo["fcf"].max() - basal),
            "prolongada": es_prolongada,
            "etiqueta": "aceleración prolongada" if es_prolongada else "aceleración",
            "criterio_lpm_s": f"{int(umbral_ef)}x{int(dur_min_ef)}",
        })
    return eventos


def detectar_contracciones(df: pd.DataFrame) -> list[float]:
    """Tiempos (s) de los picos de contracciones uterinas, con preprocesamiento
    clásico de señal TOCO con respaldo en la literatura de monitoreo fetal
    computarizado:

    1. Re-muestreo a grilla uniforme en el dt mediano (filtros IIR y detección
       de picos requieren muestreo regular).
    2. Mediana corta (~7s): elimina el jitter de muestra a muestra sin deformar
       la contracción (que dura 30-90s).
    3. Filtro pasabajos Butterworth zero-phase de 0.04 Hz: suprime la respiración
       materna (0.2-0.5 Hz), el artefacto dominante del TOCO (Stony Brook
       uterine-contraction ID; algoritmo clásico Dawood-Redman/Sonicaid).
    4. Tono de reposo = mediana móvil larga (~5 min): sigue la deriva del tono
       basal, a diferencia del percentil 20 global que usaba la versión previa.
    5. find_peaks sobre la señal sin tono, con prominencia relativa a la escala
       robusta del registro (p95-p20), separación mínima de 45s y duración
       mínima de 30s al 50% de prominencia — umbrales fisiológicos, no absolutos,
       así que sirve igual para UA en % (CTU-UHB) que en mmHg (digitalizador),
       dado que el TOCO no es cuantitativo de todas formas (mide cambio de
       contorno abdominal, no presión intrauterina).

    Validado contra CTU-UHB (552 registros): mediana 17 contracciones por
    registro (~80 min) = 2.4/10 min, rango p5-p95 de 8-26 por registro —
    coherente con trabajo de parto activo. La versión previa (máximos locales
    sobre la señal cruda) daba una mediana de 90 por registro (12.6/10 min),
    incompatible con la fisiología y la razón por la que el criterio real de
    FIGO (>50% de contracciones) fracasó en el intento del 26-ago-2026.
    """
    sub = df.loc[df.get("ua_confiable", pd.Series(True, index=df.index)).astype(bool)]
    sub = sub.dropna(subset=["ua"]).sort_values("tiempo")
    if len(sub) < 20:
        return []

    tiempo = sub["tiempo"].to_numpy(float)
    valores = sub["ua"].to_numpy(float)

    dt = float(np.median(np.diff(tiempo)))
    if dt <= 0:
        return []
    t_uniforme = np.arange(tiempo[0], tiempo[-1] + dt / 2, dt)
    if len(t_uniforme) < 20:
        return []
    ua = np.interp(t_uniforme, tiempo, valores)

    n_med_corta = max(3, int(round(7.0 / dt)) | 1)
    ua = median_filter(ua, size=n_med_corta, mode="nearest")

    fs = 1.0 / dt
    if fs > 0.2:
        wn = min(0.04 / (fs / 2), 0.99)
        if wn < 0.99:
            b, a = butter(4, wn, btype="low")
            ua = filtfilt(b, a, ua)

    n_baseline = max(n_med_corta, int(round(300.0 / dt)) | 1)
    tono = median_filter(ua, size=n_baseline, mode="nearest")
    detrend = ua - tono

    escala = float(np.percentile(detrend, 95) - np.percentile(detrend, 20))
    if escala <= 0:
        return []

    # Piso anti-ruido: con UA sin contracciones reales la escala robusta se
    # achica hasta el nivel del ruido y un umbral puramente relativo admite
    # picos espurios de la deriva residual. La prominencia debe superar:
    # - el 15% de la escala robusta del registro, y
    # - ~4 sigmas del ruido de fondo, estimado con la dispersión del tramo
    #   INFERIOR de la señal sin tono (percentil 40 hacia abajo): esa porción
    #   contiene casi solo reposo aunque las contracciones ocupen hasta ~50%
    #   del registro (MAD global queda inflado por las propias contracciones
    #   cuando su duty cycle es alto — fue el bug del primer intento), y
    # - un mínimo absoluto pequeño (una contracción real de TOCO supera el
    #   tono en >=10-20 unidades, así que 3 unidades no descarta nada
    #   fisiológico en las escalas típicas % / mmHg).
    parte_baja = detrend[detrend <= np.percentile(detrend, 40)]
    sigma_ruido = float(np.std(parte_baja)) if len(parte_baja) > 10 else 0.0
    prominencia = max(0.15 * escala, 4.0 * sigma_ruido, 3.0)

    picos, _ = find_peaks(
        detrend,
        prominence=prominencia,
        distance=max(1, int(round(45.0 / dt))),
        width=max(1, int(round(30.0 / dt))),
        rel_height=0.5,
    )

    # Fusionar picos a <30s por si una meseta plana escapó al `distance` de
    # find_peaks (misma razón que la versión previa: evitar duplicar una
    # contracción real en el conteo).
    fusionados = []
    for p in picos:
        t = float(t_uniforme[p])
        if fusionados and t - fusionados[-1] < 30.0:
            continue
        fusionados.append(t)
    return fusionados


def _picos_contraccion(df: pd.DataFrame, prominencia: float = 10.0) -> list[float]:
    """Alias de compatibilidad hacia `detectar_contracciones()` — el parámetro
    `prominencia` se conserva solo en la firma para no romper llamadas viejas;
    el detector nuevo usa umbrales relativos a la escala del registro."""
    return detectar_contracciones(df)


def _calcular_taquisistolia_ventana_30m(
    picos_ua: list[float], t_min: float, t_max: float
) -> dict:
    """Evalúa taquisistolía según ACOG CPG No. 10 (Tabla 1) y Protocolo V2:
    más de 5 contracciones en 10 minutos promediadas en una ventana móvil de 30 minutos (1800s).
    Si el registro dura menos de 30 minutos, informa `evaluada_30m=False` para que opere
    el respaldo de tasa global (≥5/10 min).
    """
    duracion_s = max(0.0, float(t_max - t_min))
    if duracion_s < TAQUISISTOLIA_VENTANA_ACOG_S - 1.0:
        return {
            "evaluada_30m": False,
            "por_10min_ventana_30m": None,
            "tachisistolia_acog_30m": False,
        }
    if not picos_ua:
        return {
            "evaluada_30m": True,
            "por_10min_ventana_30m": 0.0,
            "tachisistolia_acog_30m": False,
        }

    picos_ord = sorted(float(p) for p in picos_ua)
    max_inicio = max(float(t_min), float(t_max) - TAQUISISTOLIA_VENTANA_ACOG_S)
    candidatos = {float(t_min), max_inicio}
    for p in picos_ord:
        candidatos.add(min(max(float(t_min), p), max_inicio))
        candidatos.add(min(max(float(t_min), p - TAQUISISTOLIA_VENTANA_ACOG_S), max_inicio))

    max_conteo = 0
    for w0 in sorted(candidatos):
        w1 = w0 + TAQUISISTOLIA_VENTANA_ACOG_S
        c = sum(1 for p in picos_ord if w0 - 1e-6 <= p <= w1 + 1e-6)
        if c > max_conteo:
            max_conteo = c

    tasa_10m_30m = max_conteo / 3.0
    return {
        "evaluada_30m": True,
        "por_10min_ventana_30m": round(tasa_10m_30m, 1),
        "tachisistolia_acog_30m": bool(tasa_10m_30m > TAQUISISTOLIA_UMBRAL_ACOG_10MIN),
    }


def detectar_desaceleraciones(df: pd.DataFrame, basal: float, incluir_subclasificacion: bool = True) -> list[dict]:
    """Descensos >=15 lpm bajo la línea base, >=15s de duración, subclasificados
    (precoz/tardía/variable/indeterminada) correlacionando el nadir contra los
    picos de actividad uterina cuando hay columna `ua` disponible.
    """
    sub = df.loc[df["fcf_confiable"].astype(bool)].sort_values("tiempo")
    if sub.empty:
        return []

    mask = sub["fcf"] <= basal - UMBRAL_ACEL_DECEL
    hay_ua = "ua" in df.columns and df["ua"].notna().any()
    picos_ua = _picos_contraccion(df) if (incluir_subclasificacion and hay_ua) else []

    eventos = []
    for inicio, fin in _agrupar_en_eventos(mask, sub["tiempo"]):
        duracion = fin - inicio
        if duracion < DURACION_MIN_EVENTO_S:
            continue
        tramo = sub[(sub["tiempo"] >= inicio) & (sub["tiempo"] <= fin)]
        idx_nadir = tramo["fcf"].idxmin()
        t_nadir = float(tramo.loc[idx_nadir, "tiempo"])
        nadir_lpm = float(tramo["fcf"].min())
        onset_a_nadir = t_nadir - inicio
        es_prolongada = bool(duracion >= DESACEL_PROLONGADA_MIN_S)

        # Fase B6 (Protocolo V2 / ACOG CPG No. 10): para cada desaceleración >=2 min (120s),
        # medir la amplitud pico-a-pico dentro del evento (quitando la tendencia de rampa con
        # mediana móvil de ~20s para medir la oscilación real intra-evento) y marcar
        # `variabilidad_reducida_intra_evento` si es <5 lpm.
        var_intra_lpm: float | None = None
        var_reducida_intra = False
        if es_prolongada and len(tramo) >= 3:
            vals_tramo = tramo["fcf"].to_numpy(float)
            t_tramo = tramo["tiempo"].to_numpy(float)
            dt_tramo = float(np.median(np.diff(t_tramo))) if len(t_tramo) >= 2 else 1.0
            dt_tramo = dt_tramo if dt_tramo > 0 else 1.0
            win_med = max(3, int(round(20.0 / dt_tramo)) | 1)
            tend_tramo = median_filter(vals_tramo, size=win_med, mode="nearest")
            osc_tramo = vals_tramo - tend_tramo
            rango_bruto = float(vals_tramo.max() - vals_tramo.min())
            rango_detrend = float(osc_tramo.max() - osc_tramo.min())
            var_intra_lpm = round(min(rango_bruto, rango_detrend), 1)
            var_reducida_intra = bool(var_intra_lpm < VARIABILIDAD_REDUCIDA_MAX)

        evento = {
            "inicio_s": float(inicio),
            "fin_s": float(fin),
            "duracion_s": float(duracion),
            "nadir_lpm": round(nadir_lpm, 1),
            "amplitud_max_lpm": float(basal - nadir_lpm),
            "prolongada": es_prolongada,
            "muy_prolongada": bool(duracion >= DESACEL_MUY_PROLONGADA_S),
            "variabilidad_intra_lpm": var_intra_lpm,
            "variabilidad_reducida_intra_evento": var_reducida_intra,
        }

        if incluir_subclasificacion:
            evento["tipo"] = _clasificar_tipo_desaceleracion(onset_a_nadir, t_nadir, picos_ua)
            if picos_ua:
                pico_cercano = min(picos_ua, key=lambda p: abs(p - t_nadir))
                evento["pico_ua_asociado_s"] = (
                    float(pico_cercano)
                    if abs(t_nadir - pico_cercano) <= TOLERANCIA_ASOCIACION_CONTRACCION_S
                    else None
                )
            else:
                evento["pico_ua_asociado_s"] = None

            # Fase C1 (Protocolo V2): Criterios «60» para desaceleraciones variables
            if evento["tipo"] == "variable":
                crit_60: list[str] = []
                if float(duracion) > CRITERIO_60_DURACION_S:
                    crit_60.append("duración >60s")
                if float(nadir_lpm) < CRITERIO_60_NADIR_LPM:
                    crit_60.append("nadir <60 lpm")
                if float(basal - nadir_lpm) > CRITERIO_60_CAIDA_LPM:
                    crit_60.append("caída >60 lpm")
                evento["criterios_60_cumplidos"] = crit_60
                evento["num_criterios_60"] = len(crit_60)
                evento["cumple_dos_criterios_60"] = len(crit_60) >= 2
            else:
                evento["criterios_60_cumplidos"] = []
                evento["num_criterios_60"] = 0
                evento["cumple_dos_criterios_60"] = False

        eventos.append(evento)
    return eventos


def _clasificar_tipo_desaceleracion(onset_a_nadir: float, t_nadir: float, picos_ua: list[float]) -> str:
    abrupta = onset_a_nadir < ONSET_ABRUPTO_MAX_S

    if not picos_ua:
        return "variable" if abrupta else "indeterminada"

    pico_mas_cercano = min(picos_ua, key=lambda p: abs(p - t_nadir))
    desfase = t_nadir - pico_mas_cercano

    if abrupta:
        return "variable"
    if abs(desfase) <= TOLERANCIA_COINCIDENCIA_S:
        return "precoz"
    if desfase > TOLERANCIA_COINCIDENCIA_S:
        return "tardia"
    return "variable"


# --------------------------------------------------------------------------
# Patrón sinusoidal
# --------------------------------------------------------------------------


def detectar_patron_sinusoidal(df: pd.DataFrame) -> dict:
    """Heurística simplificada: oscilación regular de 3-5 ciclos/min y amplitud
    5-15 lpm, sostenida al menos SINUSOIDAL_DURACION_MIN_S (20 min, ACOG CPG No. 10)
    sobre un tramo continuo confiable. Se busca vía FFT sobre la señal sin tendencia
    (se resta una mediana móvil para quedarse con la oscilación, no con la línea base).
    """
    sub = df.loc[df["fcf_confiable"].astype(bool)].sort_values("tiempo")
    if len(sub) < 10:
        return {"presente": False, "motivo": "datos insuficientes", "duracion_evaluada_s": 0.0}

    dt = float(np.median(np.diff(sub["tiempo"].to_numpy())))
    if dt <= 0:
        return {"presente": False, "motivo": "muestreo inválido", "duracion_evaluada_s": 0.0}

    duracion_total = float(sub["tiempo"].iloc[-1] - sub["tiempo"].iloc[0]) + dt
    if duracion_total < SINUSOIDAL_DURACION_MIN_S - 1e-6:
        return {
            "presente": False,
            "motivo": f"tramo confiable menor a {SINUSOIDAL_DURACION_MIN_S // 60} minutos",
            "duracion_evaluada_s": round(duracion_total, 1),
            "duracion_evaluada_min": round(duracion_total / 60.0, 1),
        }

    valores = sub["fcf"].to_numpy()
    ventana_tendencia = max(3, int(round(20.0 / dt)) | 1)  # ~20s, impar para mediana centrada
    tendencia = pd.Series(valores).rolling(ventana_tendencia, center=True, min_periods=1).median().to_numpy()
    oscilacion = valores - tendencia

    n = len(oscilacion)
    freqs_hz = np.fft.rfftfreq(n, d=dt)
    espectro = np.abs(np.fft.rfft(oscilacion - oscilacion.mean()))
    freqs_cpm = freqs_hz * 60.0

    banda = (freqs_cpm >= SINUSOIDAL_FRECUENCIA_MIN_CPM) & (freqs_cpm <= SINUSOIDAL_FRECUENCIA_MAX_CPM)
    if not banda.any() or espectro.sum() == 0:
        return {
            "presente": False,
            "motivo": "sin energía espectral en banda 3-5 cpm",
            "duracion_evaluada_s": round(duracion_total, 1),
            "duracion_evaluada_min": round(duracion_total / 60.0, 1),
        }

    energia_banda = espectro[banda].sum()
    proporcion_banda = float(energia_banda / espectro.sum())

    idx_pico = np.argmax(espectro * banda)
    frecuencia_dominante = float(freqs_cpm[idx_pico])
    amplitud = float(np.percentile(oscilacion, 95) - np.percentile(oscilacion, 5)) / 2

    presente = (
        proporcion_banda >= 0.4
        and SINUSOIDAL_AMPLITUD_MIN <= amplitud <= SINUSOIDAL_AMPLITUD_MAX
    )

    nota_protocolo_v2 = (
        f"Duración efectiva evaluada: {duracion_total / 60.0:.1f} min "
        "(ACOG CPG No. 10 exige ≥20 min; Protocolo V2 institucional exige >30 min con ausencia de aceleraciones)."
    )

    return {
        "presente": bool(presente),
        "frecuencia_dominante_cpm": round(frecuencia_dominante, 2),
        "amplitud_lpm": round(amplitud, 1),
        "proporcion_energia_banda": round(proporcion_banda, 2),
        "duracion_evaluada_s": round(duracion_total, 1),
        "duracion_evaluada_min": round(duracion_total / 60.0, 1),
        "cumple_30min_protocolo_v2": bool(presente and duracion_total >= SINUSOIDAL_DURACION_PROTOCOLO_V2_S),
        "nota_protocolo_v2": nota_protocolo_v2,
    }


# --------------------------------------------------------------------------
# Clasificación FIGO 2015 + semáforo NICE NG229
# --------------------------------------------------------------------------


def _hay_desaceleraciones_repetitivas(decels: list[dict], ventana_s: float = 1200.0, minimo: int = 3) -> bool:
    """Proxy de "desaceleraciones repetitivas" (FIGO 2015 define Categoría I como
    "sin desaceleraciones repetitivas", asociadas a más del 50% de las contracciones):
    3 o más desaceleraciones tardías/variables dentro de cualquier ventana de 20
    minutos. Una o dos aisladas no deberían sacar el registro de Categoría I.

    Se intentó reemplazar este proxy por la proporción real de contracciones
    asociadas (usando `pico_ua_asociado_s` / `num_contracciones`, ambos ya
    calculados): subió la especificidad de 12.5% a 78.9% contra los 552 registros
    de CTU-UHB, pero a costa de la sensibilidad (95%→67.5%, falsos negativos de
    2→13) — el detector de picos de UA no es lo bastante confiable sobre señales
    reales/ruidosas como para usarlo de criterio excluyente. Para una herramienta
    de apoyo a decisión clínica, perder casos reales de hipoxia es mucho peor que
    una falsa alarma de más, así que se descartó ese enfoque (se puede revisar en
    `git log` si se mejora la detección de contracciones). `features["num_contracciones"]`
    y `evento["pico_ua_asociado_s"]` (en cada desaceleración) quedan calculados y
    disponibles como diagnóstico, pero no se usan en la clasificación."""
    if len(decels) < minimo:
        return False
    inicios = sorted(d["inicio_s"] for d in decels)
    for i in range(len(inicios) - minimo + 1):
        if inicios[i + minimo - 1] - inicios[i] <= ventana_s:
            return True
    return False


def clasificar_figo(features: dict) -> dict:
    """Combina línea base, variabilidad, aceleraciones, desaceleraciones y patrón
    sinusoidal en una categoría FIGO 2015 (I/II/III) + semáforo NICE NG229 por
    variable. `features` es el dict devuelto por `extraer_features()`.

    Simplificación de MVP: cubre los criterios más frecuentes de cada categoría,
    no cada matiz de la guía (ver disclaimer clínico de la Fase 5 del plan).
    """
    basal = features["linea_base"]
    variabilidad = features["variabilidad"]["categoria"]
    desaceleraciones = features["desaceleraciones"]
    sinusoidal = features["patron_sinusoidal"]["presente"]
    contracciones = features.get("contracciones") or {}
    por_10min = contracciones.get("por_10min")
    tachisistolia = contracciones.get("tachisistolia", False)

    # "indeterminada" no es una categoría benigna aparte: es una desaceleración real que
    # _clasificar_tipo_desaceleracion() no pudo correlacionar con picos de UA (típicamente
    # porque el panel UA quedó mal digitalizado/sin picos detectables, no porque el evento
    # en sí sea leve). Tratarla como invisible para la clasificación dejaba pasar
    # desaceleraciones grandes y prolongadas como "Normal" solo por falta de dato de UA
    # (caso real: -59 lpm / 230s sin contar para nada). Se la trata igual que
    # tardía/variable — no darle el beneficio de la duda a un evento sin clasificar.
    tardias_o_variables = [d for d in desaceleraciones if d.get("tipo") in ("tardia", "variable", "indeterminada")]
    hay_desacel_muy_prolongada = any(d["muy_prolongada"] for d in desaceleraciones)

    razones = []
    semaforo = {
        "linea_base": "verde" if BASAL_MIN_NORMAL <= basal <= BASAL_MAX_NORMAL else "amarillo",
        "variabilidad": {"normal": "verde", "aumentada": "amarillo", "reducida": "rojo"}[variabilidad],
        "desaceleraciones": "verde",
        # NICE NG229 §1.4.12 evalúa contracciones como una de las 4 variables
        # (white <5 en 10 min / amber >=5 en 10 min o hipertono). Sin datos de UA
        # no se puede evaluar: se reporta "verde" pero con por_10min=None.
        "contracciones": ("amarillo" if tachisistolia else "verde"),
    }

    # --- Categoría III (patológico): criterios que por sí solos bastan ---
    es_patologico = False
    if sinusoidal:
        es_patologico = True
        razones.append("Patrón sinusoidal presente.")
    if hay_desacel_muy_prolongada:
        es_patologico = True
        razones.append("Desaceleración prolongada >=5 minutos.")
    if variabilidad == "reducida" and basal < 100:
        es_patologico = True
        razones.append("Línea base <100 lpm con variabilidad reducida.")
    if variabilidad == "reducida" and len(tardias_o_variables) >= 1:
        es_patologico = True
        razones.append("Variabilidad reducida junto a desaceleraciones tardías/variables.")

    if es_patologico:
        semaforo["desaceleraciones"] = "rojo"
        return {"categoria": "III", "descripcion": "Patológico", "razones": razones, "semaforo_nice": semaforo}

    # --- Categoría I (normal): todos los criterios deben cumplirse ---
    repetitivas = _hay_desaceleraciones_repetitivas(tardias_o_variables)
    es_normal = (
        BASAL_MIN_NORMAL <= basal <= BASAL_MAX_NORMAL
        and variabilidad == "normal"
        and not repetitivas
        and not tachisistolia
    )
    if es_normal:
        razones_normal = ["Sin hallazgos anormales."]
        if tardias_o_variables:
            razones_normal = [
                f"{len(tardias_o_variables)} desaceleración(es) tardía(s)/variable(s) aislada(s), no repetitivas."
            ]
        return {"categoria": "I", "descripcion": "Normal", "razones": razones_normal, "semaforo_nice": semaforo}

    # --- Categoría II (sospechoso): todo lo que no cae en I ni III ---
    if tardias_o_variables:
        semaforo["desaceleraciones"] = "amarillo"
        etiqueta = "repetitiva(s)" if repetitivas else "sin cumplir criterio patológico"
        razones.append(f"{len(tardias_o_variables)} desaceleración(es) tardía(s)/variable(s) {etiqueta}.")
    if basal < BASAL_MIN_NORMAL or basal > BASAL_MAX_NORMAL:
        razones.append(f"Línea base fuera de rango normal ({basal:.0f} lpm).")
    if variabilidad != "normal":
        razones.append(f"Variabilidad {variabilidad}.")
    if tachisistolia:
        tasa_30m = contracciones.get("por_10min_ventana_30m")
        acog_30m = contracciones.get("tachisistolia_acog_30m", False)
        detalle_30m = (
            f"; promedio móvil máx. en 30 min: {tasa_30m:.1f}/10 min "
            f"({'cumple' if acog_30m else 'no alcanza'} criterio ACOG >5/10 min)"
            if tasa_30m is not None
            else " (registro <30 min: evaluado por tasa global de respaldo)"
        )
        tasa_global_txt = f"{por_10min:.1f}" if por_10min is not None else "N/A"
        razones.append(
            f"Frecuencia de contracciones elevada (tasa global {tasa_global_txt} en 10 minutos, "
            f"criterio ámbar NICE NG229 ≥5{detalle_30m})."
        )
    if not razones:
        razones.append("No cumple todos los criterios de categoría I ni de III.")

    return {"categoria": "II", "descripcion": "Sospechoso", "razones": razones, "semaforo_nice": semaforo}


# --------------------------------------------------------------------------
# Fase A (v2.0): Subclasificador Box 3 ACOG, sospecha FCF materna y ACOG estricta
# (Informativos: NO alteran clasificar_figo() ni los umbrales de sensibilidad)
# --------------------------------------------------------------------------


def evaluar_riesgo_categoria_ii(features: dict) -> dict:
    """Subclasificador determinístico de riesgo dentro de Categoría II según
    ACOG Clinical Practice Guideline No. 10 (Obstet Gynecol 2025;146:583-599, Box 3)
    y el Protocolo de Vigilancia del Bienestar Fetal Intraparto V2 (sept. 2025).

    No altera `clasificar_figo()`; estratifica el riesgo para orientar la ventana
    de observación (30-60 min en Protocolo V2, individualizada según Box 3 ACOG).
    """
    basal = float(features.get("linea_base", 140.0))
    var_dict = features.get("variabilidad") or {}
    cat_var = var_dict.get("categoria", "normal")
    amp_var = float(var_dict.get("amplitud_media_lpm", 10.0))
    aceleraciones = features.get("aceleraciones") or []
    desaceleraciones = features.get("desaceleraciones") or []
    figo_cat = (features.get("figo") or {}).get("categoria", "II")

    tardias_o_variables = [
        d for d in desaceleraciones if d.get("tipo") in ("tardia", "variable", "indeterminada")
    ]
    repetitivas = _hay_desaceleraciones_repetitivas(tardias_o_variables)
    n_prolongadas = sum(
        1 for d in desaceleraciones if d.get("prolongada") or d.get("muy_prolongada")
    )

    rasgos_alto_riesgo: list[str] = []
    cat_nichd = var_dict.get("categoria_nichd") or (
        "ausente" if amp_var < VARIABILIDAD_AUSENTE_MAX_LPM else ("minima" if amp_var <= VARIABILIDAD_REDUCIDA_MAX else "moderada")
    )
    if cat_nichd == "ausente":
        rasgos_alto_riesgo.append("Variabilidad ausente (<1 lpm, NICHD/ACOG Box 3).")
    elif cat_var == "reducida" or cat_nichd == "minima":
        rasgos_alto_riesgo.append("Variabilidad mínima/reducida (≤5 lpm, NICHD/ACOG Box 3).")
    if basal > BASAL_MAX_NORMAL:
        rasgos_alto_riesgo.append(f"Taquicardia fetal ({basal:.0f} lpm > {BASAL_MAX_NORMAL} lpm).")
    if repetitivas:
        rasgos_alto_riesgo.append("Desaceleraciones tardías o variables recurrentes (≥3 en 20 min).")
    if n_prolongadas > 1:
        rasgos_alto_riesgo.append(f"Más de una desaceleración prolongada ({n_prolongadas} eventos).")

    rasgos_protectores: list[str] = []
    if cat_var in ("normal", "moderada") and VARIABILIDAD_REDUCIDA_MAX <= amp_var <= VARIABILIDAD_NORMAL_MAX:
        rasgos_protectores.append("Variabilidad moderada conservada (5–25 lpm).")
    if len(aceleraciones) >= 1:
        rasgos_protectores.append(f"Presencia de aceleraciones ({len(aceleraciones)} evento(s)).")

    if rasgos_alto_riesgo:
        nivel = "alto"
    elif rasgos_protectores:
        nivel = "con rasgos protectores"
    else:
        nivel = "intermedio"

    razones = list(rasgos_alto_riesgo) + [f"Protector: {r}" for r in rasgos_protectores]
    if not razones:
        razones.append("Sin rasgos de alto riesgo del Box 3 ACOG ni rasgos protectores documentados.")

    return {
        "aplicable": figo_cat == "II",
        "nivel": nivel,
        "rasgos_alto_riesgo": rasgos_alto_riesgo,
        "rasgos_protectores": rasgos_protectores,
        "razones": razones,
    }


def detectar_sospecha_fcf_materna(
    features: dict, picos_ua: list[float] | None = None
) -> dict:
    """Heurística informativa (ACOG CPG No. 10 / Protocolo V2 Supuesto 5):
    detecta si existen aceleraciones repetidas (>=2) cuyo punto medio o ventana
    coincide temporalmente con picos de contracciones uterinas, patrón clásico de
    captación inadvertida de la frecuencia cardíaca materna (especialmente en
    segunda fase del parto u obesidad materna). Solo informativa; nunca bloquea.
    """
    aceleraciones = features.get("aceleraciones") or []
    picos = picos_ua if picos_ua is not None else (features.get("picos_contracciones_s") or [])
    if not aceleraciones or not picos:
        return {"sospecha": False, "coincidencias": 0, "mensaje": None}

    coincidencias = 0
    for ac in aceleraciones:
        t_ini = float(ac.get("inicio_s", 0.0))
        t_fin = float(ac.get("fin_s", t_ini))
        t_med = 0.5 * (t_ini + t_fin)
        # Coincidencia si un pico de contracción cae dentro de la aceleración (±tolerancia)
        if any(
            (t_ini - TOLERANCIA_COINCIDENCIA_S) <= float(p) <= (t_fin + TOLERANCIA_COINCIDENCIA_S)
            or abs(float(p) - t_med) <= TOLERANCIA_COINCIDENCIA_S
            for p in picos
        ):
            coincidencias += 1

    sospecha = coincidencias >= MIN_COINCIDENCIAS_FCF_MATERNA
    mensaje = (
        f"⚠️ Sospecha de registro de FCF materna (ACOG CPG No. 10 / Protocolo V2 Supuesto 5): "
        f"se detectaron {coincidencias} aceleraciones coincidentes con picos de contracciones uterinas. "
        f"Verifique simultáneamente el pulso materno con pulsioxímetro (especialmente en expulsivo u obesidad materna)."
        if sospecha
        else None
    )
    return {
        "sospecha": bool(sospecha),
        "coincidencias": int(coincidencias),
        "mensaje": mensaje,
    }


def clasificar_acog_estricta(features: dict) -> dict:
    """Clasificación comparativa según definición estricta NICHD 2008 / ACOG CPG No. 10
    (Obstet Gynecol 2025;146:583-599, Table 1 & Box 1).

    Diferencia clave frente a `clasificar_figo()` (MEFI de alta sensibilidad):
    - ACOG estricta exige variabilidad **ausente** (indetectable, <1.0 lpm) junto a
      desaceleraciones tardías/variables recurrentes o bradicardia (<110 lpm), o bien
      patrón sinusoidal, para clasificar en Categoría III.
    - MEFI (`clasificar_figo`) usa variabilidad reducida (<5 lpm) + >=1 desaceleración
      tardía/variable o desaceleración >=5 min para garantizar sensibilidad >=95.0%
      y VPN >=96.6% (validado en CTU-UHB).
    """
    basal = float(features.get("linea_base", 140.0))
    var_dict = features.get("variabilidad") or {}
    cat_var = var_dict.get("categoria", "normal")
    amp_var = float(var_dict.get("amplitud_media_lpm", 10.0))
    variabilidad_ausente = (
        var_dict.get("categoria_nichd") == "ausente"
        or var_dict.get("subcategoria_nichd") == "ausente"
        or amp_var < VARIABILIDAD_AUSENTE_MAX_LPM
    )
    variabilidad_moderada = (
        cat_var in ("normal", "moderada")
        and VARIABILIDAD_REDUCIDA_MAX <= amp_var <= VARIABILIDAD_NORMAL_MAX
    )

    desaceleraciones = features.get("desaceleraciones") or []
    tardias_o_variables = [
        d for d in desaceleraciones if d.get("tipo") in ("tardia", "variable", "indeterminada")
    ]
    repetitivas = _hay_desaceleraciones_repetitivas(tardias_o_variables)
    sinusoidal = bool((features.get("patron_sinusoidal") or {}).get("presente", False))
    mefi_cat = (features.get("figo") or {}).get("categoria", "I")

    razones: list[str] = []
    if sinusoidal:
        cat_acog = "III"
        razones.append("Patrón sinusoidal presente (criterio Categoría III NICHD/ACOG).")
    elif variabilidad_ausente and (repetitivas or basal < BASAL_MIN_NORMAL):
        cat_acog = "III"
        if repetitivas:
            razones.append("Variabilidad ausente (<1 lpm) con desaceleraciones tardías/variables recurrentes.")
        if basal < BASAL_MIN_NORMAL:
            razones.append(f"Variabilidad ausente (<1 lpm) con bradicardia ({basal:.0f} < {BASAL_MIN_NORMAL} lpm).")
    elif BASAL_MIN_NORMAL <= basal <= BASAL_MAX_NORMAL and variabilidad_moderada and not tardias_o_variables:
        cat_acog = "I"
        razones.append("Línea base 110–160 lpm, variabilidad moderada y ausencia de desaceleraciones tardías/variables.")
    else:
        cat_acog = "II"
        razones.append("Trazado indeterminado según definición estricta NICHD/ACOG (no cumple Categoría I ni variabilidad ausente/sinusoidal de Categoría III).")

    difiere = cat_acog != mefi_cat
    if difiere:
        nota = (
            f"Lectura comparativa: **MEFI clasifica en Categoría {mefi_cat}** (criterio FIGO 2015 / NICE NG229 "
            f"de alta sensibilidad ≥95 %) mientras que **ACOG CPG No. 10 estricta ubica en Categoría {cat_acog}** "
            f"({'; '.join(razones)})."
        )
    else:
        nota = f"Concordancia normativa completa: Categoría {cat_acog} tanto en MEFI (FIGO/NICE) como en ACOG CPG No. 10 estricta."

    return {
        "categoria": cat_acog,
        "difiere_de_mefi": difiere,
        "nota_comparativa": nota,
        "razones": razones,
    }


# --------------------------------------------------------------------------
# Fase C (v2.0): Criterios «60» y Tipificación determinística de la hipoxia
# (Informativos según Protocolo V2 sept. 2025: NO alteran clasificar_figo())
# --------------------------------------------------------------------------


def evaluar_criterios_60(desaceleraciones: list[dict]) -> dict:
    """Evalúa los Criterios «60» del Protocolo V2 (sept. 2025) sobre desaceleraciones
    variables: duración >60s, frecuencia en el nadir <60 lpm y caída >60 lpm.
    Si se cumplen >=2 criterios durante más de 30 minutos (>1800s de lapso entre el
    primer y último evento afectado, o en un evento), activa el marcador de riesgo
    independiente sin cambiar la categoría FIGO por sí solo.
    """
    variables = [d for d in (desaceleraciones or []) if d.get("tipo") == "variable"]
    afectadas = []
    for d in variables:
        crit = d.get("criterios_60_cumplidos")
        if crit is None:
            crit = []
            if float(d.get("duracion_s", 0.0)) > CRITERIO_60_DURACION_S:
                crit.append("duración >60s")
            if float(d.get("nadir_lpm", 140.0)) < CRITERIO_60_NADIR_LPM:
                crit.append("nadir <60 lpm")
            if float(d.get("amplitud_max_lpm", 0.0)) > CRITERIO_60_CAIDA_LPM:
                crit.append("caída >60 lpm")
        if len(crit) >= 2:
            afectadas.append((d, crit))

    if not afectadas:
        return {
            "alerta_activa": False,
            "num_eventos_dos_o_mas_criterios": 0,
            "lapso_persistencia_s": 0.0,
            "lapso_persistencia_min": 0.0,
            "resumen": "Sin desaceleraciones variables con ≥2 criterios «60».",
        }

    t_ini_min = min(float(d.get("inicio_s", 0.0)) for d, _ in afectadas)
    t_fin_max = max(float(d.get("fin_s", 0.0)) for d, _ in afectadas)
    lapso_s = max(0.0, t_fin_max - t_ini_min)
    alerta_activa = bool(lapso_s > CRITERIO_60_PERSISTENCIA_S)

    if alerta_activa:
        resumen = (
            f"⚠️ Marcador de riesgo Criterios «60» ACTIVO (Protocolo V2): "
            f"{len(afectadas)} desaceleración(es) variable(s) cumplen ≥2 criterios «60» "
            f"(>60s, nadir <60 lpm, caída >60 lpm) persistiendo por {lapso_s / 60.0:.1f} min (>30 min)."
        )
    else:
        resumen = (
            f"Se observaron {len(afectadas)} desaceleración(es) variable(s) con ≥2 criterios «60» "
            f"(lapso observado: {lapso_s / 60.0:.1f} min, sin superar aún los 30 min de persistencia)."
        )

    return {
        "alerta_activa": alerta_activa,
        "num_eventos_dos_o_mas_criterios": len(afectadas),
        "lapso_persistencia_s": round(lapso_s, 1),
        "lapso_persistencia_min": round(lapso_s / 60.0, 1),
        "resumen": resumen,
    }


def tipificar_hipoxia(features: dict, df: pd.DataFrame | None = None) -> dict:
    """Tipificación determinística e informativa de la hipoxia intraparto según el
    Protocolo de Vigilancia del Bienestar Fetal Intraparto V2 (sept. 2025) y el
    consenso fisiológico (2018 / rev. 2024). No altera `clasificar_figo()`.

    Subtipos evaluados:
    - **Aguda:** desaceleración >5 min (300s), o >3 min (180s) con variabilidad reducida intra-evento.
    - **Subaguda:** el feto pasa más tiempo desacelerando que en línea basal (>50% del tiempo total).
    - **Progresiva:** secuencia observable (ausencia de aceleraciones + desaceleraciones repetitivas
      tardías/variables + ascenso de línea base/taquicardia o caída de variabilidad).
    - **Crónica:** línea base en límite alto (≥150 lpm) + variabilidad reducida + ausencia de aceleraciones.
    """
    basal = float(features.get("linea_base", 140.0))
    var_dict = features.get("variabilidad") or {}
    cat_var = var_dict.get("categoria", "normal")
    aceleraciones = features.get("aceleraciones") or []
    desaceleraciones = features.get("desaceleraciones") or []

    # Duración total del trazado
    if df is not None and not df.empty and "tiempo" in df.columns:
        dur_total_s = max(1.0, float(df["tiempo"].max() - df["tiempo"].min()))
    else:
        max_fin = max(
            [float(e.get("fin_s", 0.0)) for e in desaceleraciones + aceleraciones] + [600.0]
        )
        dur_total_s = max(600.0, max_fin)

    tiempo_desacel_s = float(sum(float(d.get("duracion_s", 0.0)) for d in desaceleraciones))
    prop_desacel = tiempo_desacel_s / dur_total_s if dur_total_s > 0 else 0.0

    # 1. Hipoxia Aguda
    hay_mayor_5m = any(float(d.get("duracion_s", 0.0)) >= DESACEL_MUY_PROLONGADA_S or d.get("muy_prolongada") for d in desaceleraciones)
    hay_mayor_3m_var_red = any(
        float(d.get("duracion_s", 0.0)) >= 180.0 and bool(d.get("variabilidad_reducida_intra_evento"))
        for d in desaceleraciones
    )
    if hay_mayor_5m or hay_mayor_3m_var_red:
        criterios = []
        if hay_mayor_5m:
            criterios.append("desaceleración prolongada ≥5 min")
        if hay_mayor_3m_var_red:
            criterios.append("desaceleración ≥3 min con variabilidad intra-evento reducida (<5 lpm)")
        return {
            "tipo": "Aguda",
            "activa": True,
            "criterios_observados": criterios,
            "proporcion_tiempo_desacelerando": round(prop_desacel, 2),
            "resumen": (
                f"**Hipoxia Aguda (Protocolo V2):** compatible con evento agudo ({'; '.join(criterios)}). "
                "Descartar accidente funicular (prolapso), hipertonía uterina, hipotensión materna o desprendimiento/rotura uterina."
            ),
        }

    # 2. Hipoxia Subaguda
    if prop_desacel > 0.50:
        criterios = [
            f"tiempo desacelerando ({tiempo_desacel_s:.0f}s, {prop_desacel * 100:.0f}%) mayor que el tiempo en línea basal"
        ]
        return {
            "tipo": "Subaguda",
            "activa": True,
            "criterios_observados": criterios,
            "proporcion_tiempo_desacelerando": round(prop_desacel, 2),
            "resumen": (
                f"**Hipoxia Subaguda (Protocolo V2):** el feto permanece más tiempo desacelerando "
                f"({prop_desacel * 100:.0f}% del trazado) que en su línea basal, reduciendo el tiempo de reoxigenación intercontráctil."
            ),
        }

    # Evaluar ascenso progresivo de la línea base si hay df disponible
    ascenso_basal = False
    if df is not None and not df.empty and "tiempo" in df.columns and "fcf" in df.columns:
        sub_conf = df.loc[df["fcf_confiable"].astype(bool)].sort_values("tiempo")
        if len(sub_conf) >= 40:
            mitad = len(sub_conf) // 2
            try:
                b1 = calcular_linea_base(sub_conf.iloc[:mitad])
                b2 = calcular_linea_base(sub_conf.iloc[mitad:])
                if b2 - b1 >= 10.0:
                    ascenso_basal = True
            except ValueError:
                pass

    tardias_o_variables = [
        d for d in desaceleraciones if d.get("tipo") in ("tardia", "variable", "indeterminada")
    ]
    repetitivas = _hay_desaceleraciones_repetitivas(tardias_o_variables)

    # 3. Hipoxia Progresiva (gradualmente evolutiva)
    if (
        len(aceleraciones) == 0
        and (repetitivas or len(tardias_o_variables) >= 2)
        and (basal > BASAL_MAX_NORMAL or ascenso_basal or cat_var == "reducida")
    ):
        criterios = [
            "ausencia de aceleraciones",
            f"{len(tardias_o_variables)} desaceleraciones tardías/variables",
        ]
        if basal > BASAL_MAX_NORMAL or ascenso_basal:
            criterios.append(f"ascenso de línea base / taquicardia ({basal:.0f} lpm)")
        if cat_var == "reducida":
            criterios.append("caída de la variabilidad (<5 lpm)")
        return {
            "tipo": "Progresiva",
            "activa": True,
            "criterios_observados": criterios,
            "proporcion_tiempo_desacelerando": round(prop_desacel, 2),
            "resumen": (
                f"**Hipoxia Progresiva / Gradualmente Evolutiva (Protocolo V2):** secuencia compatible con "
                f"descompensación gradual ({'; '.join(criterios)})."
            ),
        }

    # 4. Hipoxia Crónica
    if basal >= HIPOXIA_CRONICA_BASAL_ALTA_LPM and cat_var == "reducida" and len(aceleraciones) == 0:
        criterios = [
            f"línea base en límite alto ({basal:.0f} lpm ≥ {HIPOXIA_CRONICA_BASAL_ALTA_LPM:.0f} lpm)",
            "variabilidad reducida (<5 lpm)",
            "ausencia de aceleraciones",
        ]
        return {
            "tipo": "Crónica",
            "activa": True,
            "criterios_observados": criterios,
            "proporcion_tiempo_desacelerando": round(prop_desacel, 2),
            "resumen": (
                f"**Hipoxia Crónica / Preexistente (Protocolo V2):** patrón de línea base en límite alto "
                f"({basal:.0f} lpm) con variabilidad reducida y ausencia de aceleraciones; correlacionar con reserva placentaria antenatal."
            ),
        }

    return {
        "tipo": "Sin signos de hipoxia evolutiva",
        "activa": False,
        "criterios_observados": [],
        "proporcion_tiempo_desacelerando": round(prop_desacel, 2),
        "resumen": (
            "**Tipificación determinística de hipoxia (Protocolo V2):** sin criterios para hipoxia aguda, "
            "subaguda, progresiva ni crónica en el segmento evaluado."
        ),
    }


# --------------------------------------------------------------------------
# Extracción de features (punto de entrada único)
# --------------------------------------------------------------------------


def extraer_features(
    df: pd.DataFrame,
    edad_gestacional_sem: float | int | str | None = None,
) -> dict:
    """Corre todo el pipeline de Fase 2 sobre un DataFrame digitalizado y
    devuelve el dict que consume `clasificar_figo()` (y, en Fase 3, el prompt
    del LLM)."""
    if "fcf_confiable" not in df.columns:
        df = df.assign(fcf_confiable=True)
    if "ua" not in df.columns:
        df = df.assign(ua=np.nan, ua_confiable=True)

    basal = calcular_linea_base(df)
    variabilidad = calcular_variabilidad(df, basal)
    aceleraciones = detectar_aceleraciones(df, basal, edad_gestacional_sem=edad_gestacional_sem)
    desaceleraciones = detectar_desaceleraciones(df, basal)
    sinusoidal = detectar_patron_sinusoidal(df)
    hay_ua = "ua" in df.columns and df["ua"].notna().any()
    picos_ua = detectar_contracciones(df) if hay_ua else []
    num_contracciones = len(picos_ua) if hay_ua else None
    t_min_df = float(df["tiempo"].min()) if len(df) else 0.0
    t_max_df = float(df["tiempo"].max()) if len(df) else 0.0
    duracion_min = float((t_max_df - t_min_df) / 60.0) if len(df) else 0.0
    por_10min = (num_contracciones / (duracion_min / 10.0)) if (num_contracciones is not None and duracion_min > 0) else None
    info_30m = (
        _calcular_taquisistolia_ventana_30m(picos_ua, t_min_df, t_max_df)
        if hay_ua
        else {"evaluada_30m": False, "por_10min_ventana_30m": None, "tachisistolia_acog_30m": False}
    )
    tachisistolia_global_nice = bool(por_10min is not None and por_10min >= TAQUISISTOLIA_UMBRAL_NICE_10MIN)
    tachisistolia_acog_30m = bool(info_30m["tachisistolia_acog_30m"])

    # Área total bajo las desaceleraciones (Σ amplitud × duración, lpm·s):
    # la variable continua con mejor discriminación de hipoxia en CTU-UHB
    # (AUROC 0.71, validación 2026-10) y la feature principal de modelos
    # publicados (DeepCTG®: dec_area). Se expone como severidad cuantitativa
    # para el informe; NO entra en la clasificación por categorías.
    area_desaceleraciones = float(sum(
        d["duracion_s"] * d["amplitud_max_lpm"] for d in desaceleraciones
    ))

    features = {
        "linea_base": basal,
        "variabilidad": variabilidad,
        "aceleraciones": aceleraciones,
        "desaceleraciones": desaceleraciones,
        "patron_sinusoidal": sinusoidal,
        "num_contracciones": num_contracciones,
        "picos_contracciones_s": picos_ua,
        "area_desaceleraciones_lpm_s": round(area_desaceleraciones),
        "contracciones": {
            "num": num_contracciones,
            "por_10min": round(por_10min, 1) if por_10min is not None else None,
            "por_10min_ventana_30m": info_30m["por_10min_ventana_30m"],
            "evaluada_ventana_30m": info_30m["evaluada_30m"],
            "tachisistolia_global_nice": tachisistolia_global_nice,
            "tachisistolia_acog_30m": tachisistolia_acog_30m,
            # NICE NG229 §1.4.12 (≥5 en 10 min global / respaldo <30 min) + ACOG CPG No. 10 (>5 en 10 min en ventana 30 min):
            "tachisistolia": bool(tachisistolia_global_nice or tachisistolia_acog_30m),
        },
    }
    features["figo"] = clasificar_figo(features)
    features["riesgo_categoria_ii"] = evaluar_riesgo_categoria_ii(features)
    features["sospecha_fcf_materna"] = detectar_sospecha_fcf_materna(features, picos_ua=picos_ua)
    features["acog_estricta"] = clasificar_acog_estricta(features)
    features["criterios_60"] = evaluar_criterios_60(desaceleraciones)
    features["hipoxia_tipificada"] = tipificar_hipoxia(features, df=df)
    return features
