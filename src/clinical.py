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

VARIABILIDAD_REDUCIDA_MAX = 5  # lpm (banda de amplitud pico-a-pico)
VARIABILIDAD_NORMAL_MAX = 25  # lpm

UMBRAL_ACEL_DECEL = 15  # lpm respecto de la línea base
DURACION_MIN_EVENTO_S = 15  # seg
DURACION_MAX_ACELERACION_S = 600  # 10 min

ONSET_ABRUPTO_MAX_S = 30  # <30s inicio->nadir/pico = abrupto; si no, gradual
DESACEL_PROLONGADA_MIN_S = 180  # >=3 min: "prolongada" (relevante para clasificar)
DESACEL_MUY_PROLONGADA_S = 300  # >=5 min: criterio patológico directo (FIGO)

TOLERANCIA_COINCIDENCIA_S = 20  # ventana para asociar nadir de desaceleración con pico de UA
TOLERANCIA_ASOCIACION_CONTRACCION_S = 90  # ventana (más laxa) para saber si una desaceleración
# ocurrió "con" una contracción, sin importar el tipo — usado para el criterio de
# "repetitivas" de FIGO (>50% de las contracciones), no para la subclasificación precoz/tardía

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

    return {
        "amplitud_media_lpm": round(amplitud_repr, 1),
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
            if picos_ua:
                pico_cercano = min(picos_ua, key=lambda p: abs(p - t_nadir))
                evento["pico_ua_asociado_s"] = (
                    float(pico_cercano)
                    if abs(t_nadir - pico_cercano) <= TOLERANCIA_ASOCIACION_CONTRACCION_S
                    else None
                )
            else:
                evento["pico_ua_asociado_s"] = None

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
        razones.append(
            f"Frecuencia de contracciones elevada ({por_10min:.1f} en 10 minutos, "
            f"criterio ámbar NICE NG229: 5 o más)."
        )
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
    hay_ua = "ua" in df.columns and df["ua"].notna().any()
    num_contracciones = len(detectar_contracciones(df)) if hay_ua else None
    duracion_min = float((df["tiempo"].max() - df["tiempo"].min()) / 60.0) if len(df) else 0.0
    por_10min = (num_contracciones / (duracion_min / 10.0)) if (num_contracciones and duracion_min > 0) else None

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
        "area_desaceleraciones_lpm_s": round(area_desaceleraciones),
        "contracciones": {
            "num": num_contracciones,
            "por_10min": round(por_10min, 1) if por_10min is not None else None,
            # NICE NG229 §1.4.12: 5 o más contracciones en 10 minutos con menor
            # tiempo de reposo = variable "ámbar" por sí sola.
            "tachisistolia": bool(por_10min is not None and por_10min >= 5.0),
        },
    }
    features["figo"] = clasificar_figo(features)
    return features
