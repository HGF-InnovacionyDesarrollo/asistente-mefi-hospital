"""Tests de `src/clinical.py` sobre patrones sintéticos con ground truth conocido.

Cada test construye una señal FCF(/UA) fabricada a mano, con la propiedad clínica
que se quiere detectar ya conocida de antemano, en vez de depender de un caso real
(que no tiene ground truth verificado independientemente).
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import clinical


def _df(tiempo, fcf, ua=None, fcf_confiable=None, ua_confiable=None):
    n = len(tiempo)
    return pd.DataFrame({
        "tiempo": tiempo,
        "fcf": fcf,
        "fcf_confiable": fcf_confiable if fcf_confiable is not None else np.ones(n, dtype=bool),
        "ua": ua if ua is not None else np.full(n, np.nan),
        "ua_confiable": ua_confiable if ua_confiable is not None else np.ones(n, dtype=bool),
    })


def _trazado_plano(duracion_s=600, dt=1.0, basal=140.0, ruido=1.5, semilla=0):
    rng = np.random.default_rng(semilla)
    tiempo = np.arange(0, duracion_s, dt)
    fcf = basal + rng.normal(0, ruido, size=len(tiempo))
    return tiempo, fcf


# --------------------------------------------------------------------------
# Línea base
# --------------------------------------------------------------------------


def test_linea_base_plana():
    tiempo, fcf = _trazado_plano(basal=140.0)
    basal = clinical.calcular_linea_base(_df(tiempo, fcf))
    assert basal == 140.0


def test_linea_base_ignora_aceleracion():
    tiempo, fcf = _trazado_plano(basal=130.0, duracion_s=300)
    # aceleración fabricada de 20s a 160 lpm en medio del trazado
    fcf = fcf.copy()
    fcf[100:120] = 160.0
    basal = clinical.calcular_linea_base(_df(tiempo, fcf))
    assert basal == 130.0


# --------------------------------------------------------------------------
# Variabilidad
# --------------------------------------------------------------------------


def test_variabilidad_reducida():
    tiempo, fcf = _trazado_plano(basal=140.0, ruido=0.5)
    resultado = clinical.calcular_variabilidad(_df(tiempo, fcf), basal=140.0)
    assert resultado["categoria"] == "reducida"


def test_variabilidad_normal():
    tiempo = np.arange(0, 300, 1.0)
    # oscilación senoidal de amplitud pico-a-pico ~14 lpm alrededor de la basal
    fcf = 140.0 + 7.0 * np.sin(2 * np.pi * tiempo / 20.0)
    resultado = clinical.calcular_variabilidad(_df(tiempo, fcf), basal=140.0)
    assert resultado["categoria"] == "normal"


def test_variabilidad_aumentada():
    tiempo = np.arange(0, 300, 1.0)
    fcf = 140.0 + 20.0 * np.sin(2 * np.pi * tiempo / 20.0)
    resultado = clinical.calcular_variabilidad(_df(tiempo, fcf), basal=140.0)
    assert resultado["categoria"] == "aumentada"


# --------------------------------------------------------------------------
# Aceleraciones
# --------------------------------------------------------------------------


def test_detecta_una_aceleracion():
    tiempo, fcf = _trazado_plano(basal=130.0, duracion_s=300)
    fcf = fcf.copy()
    fcf[100:130] = 150.0  # 30s a +20 lpm: cumple 15-600s y >=15 lpm
    eventos = clinical.detectar_aceleraciones(_df(tiempo, fcf), basal=130.0)
    assert len(eventos) == 1
    assert eventos[0]["duracion_s"] >= 15
    assert eventos[0]["amplitud_max_lpm"] >= 15


def test_no_detecta_pulso_demasiado_corto():
    tiempo, fcf = _trazado_plano(basal=130.0, duracion_s=300, ruido=0.1)
    fcf = fcf.copy()
    fcf[100:103] = 150.0  # solo 3s: no cumple duración mínima de 15s
    eventos = clinical.detectar_aceleraciones(_df(tiempo, fcf), basal=130.0)
    assert len(eventos) == 0


# --------------------------------------------------------------------------
# Desaceleraciones + subclasificación
# --------------------------------------------------------------------------


def _trazado_con_desaceleracion(tipo, duracion_s=400, dt=1.0, basal=140.0):
    """Fabrica FCF + UA con una desaceleración precoz/tardía/variable conocida.

    Las rampas graduales (precoz/tardía) bajan/suben en 100s hasta -40 lpm: el
    umbral de evento (-15 lpm) se cruza recién a ~37.5s de iniciada la rampa,
    dejando >30s de margen entre el cruce de umbral (inicio detectado del
    evento) y el nadir real — así el evento se mide como "gradual" incluso
    midiendo el onset desde el cruce de umbral, no desde el inicio físico de
    la rampa (que el detector no puede conocer sin ese umbral).
    La rampa abrupta (variable) cae/sube en 3s y se mantiene 20s en el fondo,
    dejando <30s entre cruce de umbral y nadir.
    """
    tiempo = np.arange(0, duracion_s, dt)
    fcf = np.full(len(tiempo), basal)
    ua = np.full(len(tiempo), 10.0)  # tono de reposo

    t_pico_contraccion = 200
    ua[t_pico_contraccion - 30:t_pico_contraccion + 30] = np.concatenate([
        np.linspace(10, 40, 30), np.linspace(40, 10, 30)
    ])

    if tipo == "precoz":
        # descenso gradual (100s), nadir coincide con el pico de la contracción
        fcf[t_pico_contraccion - 100:t_pico_contraccion] = np.linspace(basal, basal - 40, 100)
        fcf[t_pico_contraccion:t_pico_contraccion + 100] = np.linspace(basal - 40, basal, 100)
    elif tipo == "tardia":
        # descenso gradual (100s), nadir desfasado bien después del pico de contracción
        offset = 80
        fcf[t_pico_contraccion + offset - 100:t_pico_contraccion + offset] = np.linspace(basal, basal - 40, 100)
        fcf[t_pico_contraccion + offset:t_pico_contraccion + offset + 100] = np.linspace(basal - 40, basal, 100)
    elif tipo == "variable":
        # descenso abrupto (3s), se mantiene abajo 20s, sube abrupto (3s)
        t0 = 100
        fcf[t0:t0 + 3] = np.linspace(basal, basal - 25, 3)
        fcf[t0 + 3:t0 + 23] = basal - 25
        fcf[t0 + 23:t0 + 26] = np.linspace(basal - 25, basal, 3)

    return _df(tiempo, fcf, ua=ua)


@pytest.mark.parametrize("tipo", ["precoz", "tardia", "variable"])
def test_subclasificacion_desaceleracion(tipo):
    df = _trazado_con_desaceleracion(tipo)
    eventos = clinical.detectar_desaceleraciones(df, basal=140.0)
    assert len(eventos) == 1
    assert eventos[0]["tipo"] == tipo


def test_desaceleracion_muy_prolongada_marca_bandera():
    tiempo = np.arange(0, 420, 1.0)
    fcf = np.full(len(tiempo), 140.0)
    fcf[50:361] = 120.0  # 311s por debajo de la basal, con margen sobre el umbral de 300s
    eventos = clinical.detectar_desaceleraciones(_df(tiempo, fcf), basal=140.0)
    assert len(eventos) == 1
    assert eventos[0]["muy_prolongada"] is True


# --------------------------------------------------------------------------
# Patrón sinusoidal
# --------------------------------------------------------------------------


def test_detecta_patron_sinusoidal():
    tiempo = np.arange(0, 1200, 1.0)  # 20 min
    # 4 ciclos/min, amplitud pico-a-pico 16 lpm (amplitud/2 = 8, dentro de 5-15)
    fcf = 130.0 + 8.0 * np.sin(2 * np.pi * tiempo * (4.0 / 60.0))
    resultado = clinical.detectar_patron_sinusoidal(_df(tiempo, fcf))
    assert resultado["presente"] is True
    assert 3.0 <= resultado["frecuencia_dominante_cpm"] <= 5.0


def test_trazado_normal_no_es_sinusoidal():
    tiempo, fcf = _trazado_plano(basal=140.0, duracion_s=1200, ruido=1.0)
    resultado = clinical.detectar_patron_sinusoidal(_df(tiempo, fcf))
    assert resultado["presente"] is False


def test_sinusoidal_requiere_duracion_minima():
    tiempo = np.arange(0, 300, 1.0)  # solo 5 min, menor al mínimo de 10
    fcf = 130.0 + 8.0 * np.sin(2 * np.pi * tiempo * (4.0 / 60.0))
    resultado = clinical.detectar_patron_sinusoidal(_df(tiempo, fcf))
    assert resultado["presente"] is False


# --------------------------------------------------------------------------
# Detección de contracciones (detector v2, 2026-10)
# --------------------------------------------------------------------------


def _ua_con_contracciones(tiempos_pico, duracion_s=1800, dt=0.25, tono=15.0,
                          amplitud=40.0, ruido=2.0, respiracion=3.0, semilla=7):
    """Señal TOCO sintética a 4 Hz: tono de reposo + ruido + respiración materna
    (0.3 Hz, el artefacto que el pasabajos de 0.04 Hz debe suprimir) + bumps
    gaussianos de `amplitud` centrados en `tiempos_pico` (segundos)."""
    rng = np.random.default_rng(semilla)
    tiempo = np.arange(0, duracion_s, dt)
    ua = tono + rng.normal(0, ruido, size=len(tiempo))
    ua += respiracion * np.sin(2 * np.pi * 0.3 * tiempo)
    for t_pico in tiempos_pico:
        ua += amplitud * np.exp(-0.5 * ((tiempo - t_pico) / 20.0) ** 2)
    return _df(tiempo, np.full(len(tiempo), 140.0), ua=ua)


def test_detectar_contracciones_cuenta_correcta():
    df = _ua_con_contracciones(tiempos_pico=[300, 900, 1500])
    picos = clinical.detectar_contracciones(df)
    assert len(picos) == 3
    for esperado, detectado in zip([300, 900, 1500], sorted(picos)):
        assert abs(detectado - esperado) < 20  # sin deriva de fase (filtros zero-phase)


def test_detectar_contracciones_solo_ruido_no_detecta():
    df = _ua_con_contracciones(tiempos_pico=[], amplitud=0.0, respiracion=3.0)
    assert clinical.detectar_contracciones(df) == []


def test_detectar_contracciones_respiracion_no_es_contraccion():
    """Respiración materna (0.3 Hz, ±3 unidades) no debe contarse como contracción."""
    df = _ua_con_contracciones(tiempos_pico=[], amplitud=0.0, respiracion=6.0)
    assert clinical.detectar_contracciones(df) == []


def test_frecuencia_contracciones_en_features():
    df = _ua_con_contracciones(tiempos_pico=[300, 900, 1500], duracion_s=1800)
    features = clinical.extraer_features(df)
    assert features["contracciones"]["num"] == 3
    assert features["contracciones"]["por_10min"] == 1.0  # 3 contracciones en 30 min
    assert features["contracciones"]["tachisistolia"] is False


def test_area_desaceleraciones_en_features():
    """Área total = Σ amplitud × duración: severidad cuantitativa expuesta para
    el informe (feature con mejor AUROC sobre CTU-UHB, validación 2026-10)."""
    df = _trazado_con_desaceleracion("tardia", duracion_s=400, basal=140.0)
    features = clinical.extraer_features(df)
    esperado = 200.0 * 40.0  # duración aprox. del evento × amplitud máx.
    assert features["area_desaceleraciones_lpm_s"] > 0
    assert abs(features["area_desaceleraciones_lpm_s"] - esperado) / esperado < 0.5


def test_tachisistolia_descalifica_categoria_i():
    """6 contracciones en 10 minutos con FCF completamente normal: el criterio
    ámbar de contracciones de NICE NG229 (§1.4.12) debe sacar el registro de
    Categoría I aunque la FCF sea impecable."""
    tiempo = np.arange(0, 660, 0.25)  # 11 min
    rng = np.random.default_rng(11)
    fcf = 140.0 + rng.normal(0, 4.0, size=len(tiempo))  # variabilidad normal
    ua = 15.0 + rng.normal(0, 2.0, size=len(tiempo))
    for i in range(6):
        t_pico = 120.0 + i * 100.0  # cada 100s → 6 en ~10 min
        ua += 40.0 * np.exp(-0.5 * ((tiempo - t_pico) / 20.0) ** 2)
    features = clinical.extraer_features(_df(tiempo, fcf, ua=ua))
    assert features["contracciones"]["tachisistolia"] is True
    assert features["figo"]["categoria"] == "II"
    assert any("contracciones" in r.lower() for r in features["figo"]["razones"])
    assert features["figo"]["semaforo_nice"]["contracciones"] == "amarillo"


# --------------------------------------------------------------------------
# Clasificación FIGO integrada
# --------------------------------------------------------------------------


def test_figo_categoria_i_trazado_normal():
    tiempo = np.arange(0, 600, 1.0)
    fcf = 140.0 + 7.0 * np.sin(2 * np.pi * tiempo / 20.0)
    features = clinical.extraer_features(_df(tiempo, fcf))
    assert features["figo"]["categoria"] == "I"


def test_figo_categoria_iii_variabilidad_reducida_con_desacel_tardia():
    df = _trazado_con_desaceleracion("tardia", duracion_s=400, basal=140.0)
    # aplanar el resto del trazado (fuera del evento) para forzar variabilidad reducida
    df = df.copy()
    ruido = np.random.default_rng(1).normal(0, 0.3, size=len(df))
    plano = df["fcf"] == 140.0
    df.loc[plano, "fcf"] = 140.0 + ruido[plano]
    features = clinical.extraer_features(df)
    assert features["figo"]["categoria"] == "III"


def test_figo_categoria_iii_por_sinusoidal():
    tiempo = np.arange(0, 1200, 1.0)
    fcf = 130.0 + 8.0 * np.sin(2 * np.pi * tiempo * (4.0 / 60.0))
    features = clinical.extraer_features(_df(tiempo, fcf))
    assert features["figo"]["categoria"] == "III"
    assert features["patron_sinusoidal"]["presente"] is True


def test_figo_categoria_i_desacel_tardia_aislada_no_repetitiva():
    """Una desaceleración tardía aislada, sin repetirse, no descalifica de Categoría I:
    FIGO 2015 define el criterio como "sin desaceleraciones repetitivas" (asociadas a
    más del 50% de las contracciones), no "cero desaceleraciones". Tratar cualquier
    ocurrencia aislada como descalificante resultó ser mucho más estricto que la guía
    real — validado contra CTU-UHB (552 registros intraparto reales): con el criterio
    viejo, 482/552 caían en Categoría II solo por esto, incluso registros con pH de
    cordón normal (especificidad 3.1%). Ver `_hay_desaceleraciones_repetitivas`."""
    df = _trazado_con_desaceleracion("tardia", duracion_s=400, basal=140.0)
    df = df.copy()
    ruido = np.random.default_rng(2).normal(0, 4.0, size=len(df))  # variabilidad normal
    plano = df["fcf"] == 140.0
    df.loc[plano, "fcf"] = 140.0 + ruido[plano]
    features = clinical.extraer_features(df)
    assert features["figo"]["categoria"] == "I"


def test_figo_categoria_ii_desaceleraciones_tardias_repetitivas():
    """3 desaceleraciones tardías dentro de una ventana de 20 minutos sí deben sacar
    el registro de Categoría I (son "repetitivas" en el sentido de FIGO 2015): se
    encadenan 3 tramos idénticos al de `_trazado_con_desaceleracion("tardia", ...)`,
    que ya se sabe que producen 1 desaceleración tardía detectada cada uno."""
    rng = np.random.default_rng(3)
    segmentos = []
    for i in range(3):
        seg = _trazado_con_desaceleracion("tardia", duracion_s=400, basal=140.0).copy()
        ruido = rng.normal(0, 4.0, size=len(seg))  # variabilidad normal de fondo
        plano = seg["fcf"] == 140.0
        seg.loc[plano, "fcf"] = 140.0 + ruido[plano]
        seg["tiempo"] = seg["tiempo"] + i * 400.0
        segmentos.append(seg)
    df = pd.concat(segmentos, ignore_index=True)
    features = clinical.extraer_features(df)
    assert len(features["desaceleraciones"]) == 3
    assert features["figo"]["categoria"] == "II"
