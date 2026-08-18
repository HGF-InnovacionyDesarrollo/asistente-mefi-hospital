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

# --------------------------------------------------------------------------
# Umbrales clínicos (FIGO 2015 / NICE NG229)
# --------------------------------------------------------------------------

BASAL_MIN_NORMAL = 110  # lpm
BASAL_MAX_NORMAL = 160  # lpm

VARIABILIDAD_REDUCIDA_MAX = 5  # lpm (banda de amplitud pico-a-pico)
VARIABILIDAD_NORMAL_MAX = 25  # lpm

UMBRAL_ACEL_DECEL = 15  # lpm respecto de la línea base
DURACION_MIN_EVENTO_S = 15  # seg
DURACION_MAX_ACELERACION_S = 600  # 10 min

ONSET_ABRUPTO_MAX_S = 30  # <30s inicio->nadir/pico = abrupto; si no, gradual
DESACEL_PROLONGADA_MIN_S = 180  # >=3 min: "prolongada" (relevante para clasificar)
DESACEL_MUY_PROLONGADA_S = 300  # >=5 min: criterio patológico directo (FIGO)

TOLERANCIA_COINCIDENCIA_S = 20  # ventana para asociar nadir de desaceleración con pico de UA

SINUSOIDAL_DURACION_MIN_S = 600  # 10 min continuos mínimos para evaluar el patrón
SINUSOIDAL_FRECUENCIA_MIN_CPM = 3.0
SINUSOIDAL_FRECUENCIA_MAX_CPM = 5.0
SINUSOIDAL_AMPLITUD_MIN = 5.0
SINUSOIDAL_AMPLITUD_MAX = 15.0


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

    Categorías NICE NG229: <5 reducida, 5-25 normal, >25 aumentada.
    """
    sub = df.loc[df["fcf_confiable"].astype(bool)].sort_values("tiempo").copy()
    if sub.empty:
        return {"amplitud_media_lpm": 0.0, "categoria": "reducida", "ventanas_evaluadas": 0}

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
        return {"amplitud_media_lpm": 0.0, "categoria": "reducida", "ventanas_evaluadas": 0}

    bins = (sub["tiempo"] // ventana_s).astype(int)
    amplitudes = sub.groupby(bins)["fcf"].agg(lambda s: s.max() - s.min() if len(s) >= 2 else np.nan)
    amplitudes = amplitudes.dropna()

    amplitud_media = float(amplitudes.mean()) if len(amplitudes) else 0.0

    if amplitud_media < VARIABILIDAD_REDUCIDA_MAX:
        categoria = "reducida"
    elif amplitud_media <= VARIABILIDAD_NORMAL_MAX:
        categoria = "normal"
    else:
        categoria = "aumentada"

    return {
        "amplitud_media_lpm": round(amplitud_media, 1),
        "categoria": categoria,
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


def detectar_aceleraciones(df: pd.DataFrame, basal: float) -> list[dict]:
    """Aumentos >=15 lpm sobre la línea base, de 15s a 10min de duración."""
    sub = df.loc[df["fcf_confiable"].astype(bool)].sort_values("tiempo")
    if sub.empty:
        return []

    mask = sub["fcf"] >= basal + UMBRAL_ACEL_DECEL
    eventos = []
    for inicio, fin in _agrupar_en_eventos(mask, sub["tiempo"]):
        duracion = fin - inicio
        if duracion < DURACION_MIN_EVENTO_S or duracion > DURACION_MAX_ACELERACION_S:
            continue
        tramo = sub[(sub["tiempo"] >= inicio) & (sub["tiempo"] <= fin)]
        eventos.append({
            "inicio_s": float(inicio),
            "fin_s": float(fin),
            "duracion_s": float(duracion),
            "amplitud_max_lpm": float(tramo["fcf"].max() - basal),
        })
    return eventos


def _picos_contraccion(df: pd.DataFrame, prominencia: float = 10.0) -> list[float]:
    """Tiempos (s) de los picos de actividad uterina — máximos locales de `ua`
    que superan el tono de reposo (percentil 20) en al menos `prominencia`."""
    sub = df.loc[df.get("ua_confiable", pd.Series(True, index=df.index)).astype(bool)].sort_values("tiempo")
    sub = sub.dropna(subset=["ua"])
    if len(sub) < 3:
        return []

    tono_reposo = float(np.percentile(sub["ua"], 20))
    valores = sub["ua"].to_numpy()
    tiempos = sub["tiempo"].to_numpy()

    picos = []
    for i in range(1, len(valores) - 1):
        if valores[i] >= valores[i - 1] and valores[i] >= valores[i + 1]:
            if valores[i] - tono_reposo >= prominencia:
                picos.append(tiempos[i])
    return picos


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
        onset_a_nadir = t_nadir - inicio

        evento = {
            "inicio_s": float(inicio),
            "fin_s": float(fin),
            "duracion_s": float(duracion),
            "amplitud_max_lpm": float(basal - tramo["fcf"].min()),
            "prolongada": duracion >= DESACEL_PROLONGADA_MIN_S,
            "muy_prolongada": duracion >= DESACEL_MUY_PROLONGADA_S,
        }

        if incluir_subclasificacion:
            evento["tipo"] = _clasificar_tipo_desaceleracion(onset_a_nadir, t_nadir, picos_ua)

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
    5-15 lpm, sostenida al menos SINUSOIDAL_DURACION_MIN_S sobre un tramo
    continuo confiable. Se busca vía FFT sobre la señal sin tendencia (se resta
    una mediana móvil para quedarse con la oscilación, no con la línea base).
    """
    sub = df.loc[df["fcf_confiable"].astype(bool)].sort_values("tiempo")
    if len(sub) < 10:
        return {"presente": False, "motivo": "datos insuficientes"}

    duracion_total = float(sub["tiempo"].iloc[-1] - sub["tiempo"].iloc[0])
    if duracion_total < SINUSOIDAL_DURACION_MIN_S:
        return {"presente": False, "motivo": "tramo confiable menor a 10 minutos"}

    dt = float(np.median(np.diff(sub["tiempo"].to_numpy())))
    if dt <= 0:
        return {"presente": False, "motivo": "muestreo inválido"}

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
        return {"presente": False, "motivo": "sin energía espectral en banda 3-5 cpm"}

    energia_banda = espectro[banda].sum()
    proporcion_banda = float(energia_banda / espectro.sum())

    idx_pico = np.argmax(espectro * banda)
    frecuencia_dominante = float(freqs_cpm[idx_pico])
    amplitud = float(np.percentile(oscilacion, 95) - np.percentile(oscilacion, 5)) / 2

    presente = (
        proporcion_banda >= 0.4
        and SINUSOIDAL_AMPLITUD_MIN <= amplitud <= SINUSOIDAL_AMPLITUD_MAX
    )

    return {
        "presente": bool(presente),
        "frecuencia_dominante_cpm": round(frecuencia_dominante, 2),
        "amplitud_lpm": round(amplitud, 1),
        "proporcion_energia_banda": round(proporcion_banda, 2),
    }


# --------------------------------------------------------------------------
# Clasificación FIGO 2015 + semáforo NICE NG229
# --------------------------------------------------------------------------


def _hay_desaceleraciones_repetitivas(decels: list[dict], ventana_s: float = 1200.0, minimo: int = 3) -> bool:
    """Proxy de "desaceleraciones repetitivas" (FIGO 2015 define Categoría I como
    "sin desaceleraciones repetitivas", asociadas a más del 50% de las contracciones):
    3 o más desaceleraciones tardías/variables dentro de cualquier ventana de 20
    minutos. Una o dos aisladas no deberían sacar el registro de Categoría I —
    tratarlas como descalificantes por sí solas es más estricto que la guía real y
    en intraparto (donde la compresión de cordón durante contracciones es casi
    universal) arrastra prácticamente todo a "sospechoso" (confirmado: 482 de 552
    registros de CTU-UHB caían en Categoría II solo por esto antes de este fix)."""
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
    if not razones:
        razones.append("No cumple todos los criterios de categoría I ni de III.")

    return {"categoria": "II", "descripcion": "Sospechoso", "razones": razones, "semaforo_nice": semaforo}


# --------------------------------------------------------------------------
# Extracción de features (punto de entrada único)
# --------------------------------------------------------------------------


def extraer_features(df: pd.DataFrame) -> dict:
    """Corre todo el pipeline de Fase 2 sobre un DataFrame digitalizado y
    devuelve el dict que consume `clasificar_figo()` (y, en Fase 3, el prompt
    del LLM)."""
    if "fcf_confiable" not in df.columns:
        df = df.assign(fcf_confiable=True)
    if "ua" not in df.columns:
        df = df.assign(ua=np.nan, ua_confiable=True)

    basal = calcular_linea_base(df)
    variabilidad = calcular_variabilidad(df, basal)
    aceleraciones = detectar_aceleraciones(df, basal)
    desaceleraciones = detectar_desaceleraciones(df, basal)
    sinusoidal = detectar_patron_sinusoidal(df)

    features = {
        "linea_base": basal,
        "variabilidad": variabilidad,
        "aceleraciones": aceleraciones,
        "desaceleraciones": desaceleraciones,
        "patron_sinusoidal": sinusoidal,
    }
    features["figo"] = clasificar_figo(features)
    return features
