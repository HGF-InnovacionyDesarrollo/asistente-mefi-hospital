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


# --------------------------------------------------------------------------
# Informe determinístico por plantilla + sembrado de .env (Fase 1.1)
# --------------------------------------------------------------------------


def test_generar_informe_plantilla_categorias():
    import prompts

    # Categoría I
    tiempo = np.arange(0, 600, 1.0)
    fcf = 140.0 + 7.0 * np.sin(2 * np.pi * tiempo / 20.0)
    f_cat1 = clinical.extraer_features(_df(tiempo, fcf))
    inf1 = prompts.generar_informe_plantilla(
        f_cat1, metadatos={"id": "caso01", "fecha_hora": "2026-11-06", "velocidad_papel_cm_min": 1.0}
    )
    assert "Categoría FIGO I" in inf1
    assert "caso01" in inf1
    assert "Parámetros Cardiotocográficos Extraídos" in inf1
    assert "Correlación Fisiopatológica" in inf1
    assert "Conducta Sugerida según Protocolo" in inf1
    assert "INFANT" in inf1

    # Categoría III (sinusoidal)
    tiempo_sin = np.arange(0, 1200, 1.0)
    fcf_sin = 130.0 + 8.0 * np.sin(2 * np.pi * tiempo_sin * (4.0 / 60.0))
    f_cat3 = clinical.extraer_features(_df(tiempo_sin, fcf_sin))
    inf3 = prompts.generar_informe_plantilla(f_cat3)
    assert "Categoría FIGO III" in inf3
    assert "interrupción expedita" in inf3


def test_completar_env_sin_pisar_existentes(tmp_path):
    import rutas

    plantilla = tmp_path / "plantilla.env"
    destino = tmp_path / "destino.env"
    plantilla.write_text("OPENROUTER_API_KEY=sk-bundle-123\nHF_API_KEY=hf-bundle-456\n", encoding="utf-8")
    destino.write_text("OPENROUTER_API_KEY=sk-usuario-previa\n", encoding="utf-8")

    rutas._completar_env(plantilla, destino)
    contenido = destino.read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY=sk-usuario-previa" in contenido
    assert "HF_API_KEY=hf-bundle-456" in contenido


def test_extraer_secciones_y_pdf_consolidado():
    import fitz
    from PIL import Image
    import prompts
    import reporte_pdf

    tiempo = np.arange(0, 600, 1.0)
    fcf = 140.0 + 7.0 * np.sin(2 * np.pi * tiempo / 20.0)
    features = clinical.extraer_features(_df(tiempo, fcf))
    meta = {
        "id": "caso01",
        "fecha_hora": "2026-11-06 08:30",
        "velocidad_papel_cm_min": 1.0,
        "edad_gestacional": "39+2 sem",
        "contexto_clinico": "Trabajo de parto fase activa",
        "uso_oxitocina": "Sin oxitocina",
        "profesional": "Mat. Prueba HGF",
        "observaciones_clinicas": "Paciente en buen estado general, dinámica regular.",
    }

    inf_plantilla = prompts.generar_informe_plantilla(features, metadatos=meta)
    assert "39+2 sem" in inf_plantilla
    sec = prompts.extraer_secciones_informe(inf_plantilla)
    assert set(sec.keys()) == {"1", "2", "3", "4"}
    assert "140 lpm" in sec["1"]
    assert "Categoría I" in sec["2"]

    inf_llm_simulado = (
        "#### 1. Parámetros Cardiotocográficos Extraídos\n"
        "- Trazado reactivo con FCF basal en 140 lpm y variabilidad conservada.\n\n"
        "#### 2. Clasificación Normativa (FIGO 2015 / NICE NG229)\n"
        "- Categoría FIGO I (Normal), semáforo en verde.\n\n"
        "#### 3. Correlación Fisiopatológica (Según Patrón Observado)\n"
        "- Reserva autonómica fetal íntegra sin signos de hipoxia.\n\n"
        "#### 4. Conducta Sugerida según Protocolo\n"
        "- Mantener control obstétrico habitual. Requiere validación humana.\n"
    )
    sintesis = prompts.generar_sintesis_concordancia(features, inf_plantilla, inf_llm_simulado)
    assert sintesis["estado"] == "alta"

    overlay_dummy = Image.new("RGB", (600, 200), color=(255, 255, 255))

    pdf_bytes = reporte_pdf.generar_pdf_consolidado(
        features=features,
        informe_plantilla=inf_plantilla,
        informe_llm=inf_llm_simulado,
        metadatos=meta,
        overlay_img=overlay_dummy,
        modelo_llm="google/gemma-4-31b-it:free",
    )
    assert pdf_bytes.startswith(b"%PDF")
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    assert len(doc) >= 1
    texto_pdf = "\n".join(page.get_text() for page in doc)
    assert "HOSPITAL DR. GUSTAVO FRICKE" in texto_pdf
    assert "caso01" in texto_pdf
    assert "39+2 sem" in texto_pdf
    assert "Mat. Prueba HGF" in texto_pdf
    assert "CATEGORÍA FIGO I" in texto_pdf
    assert "Reserva autonómica fetal íntegra" in texto_pdf
    doc.close()


def test_sugerir_puntos_calibracion_filtra_numeros_ocr_inespecificos(monkeypatch):
    import digitizer

    gris = np.full((300, 600), 240, dtype=np.uint8)
    panel = digitizer.LimitesPanel(0, 300)

    # Simular OCR con un número espurio como 58: debe ser descartado y caer a valores estándar (100 y 0)
    monkeypatch.setattr(
        digitizer,
        "_leer_etiquetas_eje",
        lambda g, p, ancho_margen_frac=0.10: [(40.0, 100), (220.0, 58)],
    )
    sug = digitizer.sugerir_puntos_calibracion(gris, panel, valores_default=(100.0, 0.0))
    assert sug is not None
    assert sug[0][1] == 100.0
    assert sug[1][1] == 0.0


def test_validar_estado_calibracion_seguridad():
    import ux_helpers

    # Caso válido: y1=50 (arriba) con valor 210, y2=250 (abajo) con valor 30
    ok = ux_helpers.validar_estado_calibracion(50.0, 210.0, 250.0, 30.0)
    assert ok["valido"] is True
    assert ok["codigo"] == "ok"

    # Error 1: valores iguales
    ig = ux_helpers.validar_estado_calibracion(50.0, 150.0, 250.0, 150.0)
    assert ig["valido"] is False
    assert ig["codigo"] == "valores_iguales"

    # Error 2: líneas demasiado juntas (<15 px)
    juntas = ux_helpers.validar_estado_calibracion(100.0, 210.0, 108.0, 30.0)
    assert juntas["valido"] is False
    assert juntas["codigo"] == "lineas_muy_juntas"

    # Error 3: escala invertida (valor menor arriba y valor mayor abajo)
    inv = ux_helpers.validar_estado_calibracion(50.0, 30.0, 250.0, 210.0)
    assert inv["valido"] is False
    assert inv["codigo"] == "escala_invertida"


def test_calcular_calidad_lectura_y_tabla_desaceleraciones():
    import ux_helpers

    tiempo = np.arange(0, 600, 1.0)
    fcf = np.full(len(tiempo), 140.0)
    confiable = np.ones(len(tiempo), dtype=bool)
    confiable[:60] = False  # 10% interpolado, 90% lectura directa
    df = _df(tiempo, fcf, fcf_confiable=confiable)

    calidad = ux_helpers.calcular_calidad_lectura(df)
    assert calidad["nivel"] == "alta"
    assert calidad["pct_fcf_directa"] == 90.0
    assert calidad["pct_interpolado"] == 10.0

    eventos = [
        {
            "t_inicio_s": 125.0,
            "t_fin_s": 170.0,
            "duracion_s": 45.0,
            "amplitud_max_lpm": 28.0,
            "tipo": "tardia",
            "muy_prolongada": False,
        }
    ]
    tabla = ux_helpers.formatear_tabla_desaceleraciones(eventos)
    assert len(tabla) == 1
    assert tabla[0]["Inicio (mm:ss)"] == "02:05"
    assert tabla[0]["Caída máx. (lpm)"] == "-28 lpm"
    assert "Tardía" in tabla[0]["Clasificación"]
    assert tabla[0]["Alerta prolongada (>3 min)"] == "🟢 No"


def test_generar_imagen_ctg_demo_end_to_end():
    import digitizer
    import ux_helpers

    png_bytes = ux_helpers.generar_imagen_ctg_demo()
    assert png_bytes.startswith(b"\x89PNG")
    prep = digitizer.preparar_imagen(png_bytes)
    assert prep.panel_fcf.y1 > prep.panel_fcf.y0
    assert prep.panel_ua.y1 > prep.panel_ua.y0


# --------------------------------------------------------------------------
# Fase A (MEFI v2.0): Alineación normativa Protocolo V2 + ACOG CPG No. 10
# --------------------------------------------------------------------------


def test_fase_a1_conducta_protocolo_v2_y_acog_cat_ii():
    import prompts

    # Trazado Categoría II (taquicardia moderada 170 lpm con variabilidad normal)
    tiempo = np.arange(0, 600, 1.0)
    fcf = 170.0 + 6.0 * np.sin(2 * np.pi * tiempo / 20.0)
    features = clinical.extraer_features(_df(tiempo, fcf))
    assert features["figo"]["categoria"] == "II"

    inf = prompts.generar_informe_plantilla(features)
    assert "aviso inmediato al médico/a ginecobstetra residente de turno" in inf
    assert "Amnioinfusión" in inf
    assert "SatO2 < 94 %" in inf
    assert "nitroglicerina / fenoterol" in inf
    assert "terbutalina" in inf
    assert "½ a 1 hora" in inf
    assert "Box 3 ACOG" in inf


def test_fase_a1_conducta_protocolo_v2_y_acog_cat_iii():
    import prompts

    tiempo = np.arange(0, 1200, 1.0)
    fcf = 130.0 + 8.0 * np.sin(2 * np.pi * tiempo * (4.0 / 60.0))
    features = clinical.extraer_features(_df(tiempo, fcf))
    assert features["figo"]["categoria"] == "III"

    inf = prompts.generar_informe_plantilla(features)
    assert "rotura uterina" in inf
    assert "tocolisis de acción rápida" in inf
    assert "10 minutos" in inf
    assert "interrupción expedita" in inf


def test_fase_a2_subclasificador_riesgo_cat_ii_alto():
    # Taquicardia 170 lpm -> rasgo de alto riesgo Box 3 ACOG
    tiempo = np.arange(0, 600, 1.0)
    fcf = 170.0 + 6.0 * np.sin(2 * np.pi * tiempo / 20.0)
    features = clinical.extraer_features(_df(tiempo, fcf))
    riesgo = features["riesgo_categoria_ii"]
    assert riesgo["aplicable"] is True
    assert riesgo["nivel"] == "alto"
    assert any("Taquicardia" in r for r in riesgo["rasgos_alto_riesgo"])


def test_fase_a2_subclasificador_riesgo_cat_ii_protector():
    # Categoría II solo por taquisistolia, pero con variabilidad moderada y aceleración reactiva
    tiempo = np.arange(0, 660, 0.25)
    fcf = 140.0 + 6.0 * np.sin(2 * np.pi * tiempo / 20.0)
    fcf[(tiempo >= 200) & (tiempo <= 230)] = 162.0  # 1 aceleración de 30s
    ua = np.full(len(tiempo), 15.0)
    for i in range(6):
        t_pico = 100.0 + i * 95.0
        ua += 40.0 * np.exp(-0.5 * ((tiempo - t_pico) / 20.0) ** 2)
    features = clinical.extraer_features(_df(tiempo, fcf, ua=ua))
    assert features["figo"]["categoria"] == "II"
    riesgo = features["riesgo_categoria_ii"]
    assert riesgo["nivel"] == "con rasgos protectores"
    assert len(riesgo["rasgos_protectores"]) >= 1


def test_fase_a3_sospecha_fcf_materna_positiva():
    # 2 aceleraciones cuyos centros coinciden exactamente con 2 picos de contracción
    features_mock = {
        "aceleraciones": [
            {"inicio_s": 190.0, "fin_s": 215.0, "duracion_s": 25.0, "amplitud_max_lpm": 20.0},
            {"inicio_s": 490.0, "fin_s": 515.0, "duracion_s": 25.0, "amplitud_max_lpm": 22.0},
        ],
        "picos_contracciones_s": [200.0, 500.0],
    }
    res = clinical.detectar_sospecha_fcf_materna(features_mock)
    assert res["sospecha"] is True
    assert res["coincidencias"] == 2
    assert "pulsioxímetro" in res["mensaje"]


def test_fase_a3_sospecha_fcf_materna_negativa():
    features_mock = {
        "aceleraciones": [
            {"inicio_s": 100.0, "fin_s": 120.0, "duracion_s": 20.0, "amplitud_max_lpm": 18.0},
        ],
        "picos_contracciones_s": [350.0, 650.0],
    }
    res = clinical.detectar_sospecha_fcf_materna(features_mock)
    assert res["sospecha"] is False
    assert res["mensaje"] is None


def test_fase_a4_disclaimer_regulador_acog_infant():
    import prompts

    assert "v2.0" in prompts.VERSION_PROMPT
    assert "ACOG CPG No. 10" in prompts.SYSTEM_INSTRUCTIONS
    assert "INFANT" in prompts.SYSTEM_INSTRUCTIONS

    tiempo = np.arange(0, 600, 1.0)
    fcf = 140.0 + 7.0 * np.sin(2 * np.pi * tiempo / 20.0)
    features = clinical.extraer_features(_df(tiempo, fcf))
    inf = prompts.generar_informe_plantilla(features)
    assert "ACOG CPG No. 10 recomienda en contra de depender primariamente de sistemas computarizados" in inf
    assert "INFANT" in inf


def test_fase_a5_acog_estricta_difiere_de_mefi_en_prolongada_aislada():
    # Desaceleración muy prolongada (>=5 min) pero con variabilidad moderada conservada (no sinusoidal):
    # MEFI = Cat III (por desacel >=5 min); ACOG estricta = Cat II (porque variabilidad no es ausente ni hay sinusoidal)
    tiempo, fcf = _trazado_plano(duracion_s=900, basal=140.0, ruido=3.5, semilla=10)
    fcf = fcf.copy()
    fcf[100:420] = 115.0  # 320s (>5 min) a -25 lpm
    features = clinical.extraer_features(_df(tiempo, fcf))
    assert features["patron_sinusoidal"]["presente"] is False
    assert features["figo"]["categoria"] == "III"
    acog = features["acog_estricta"]
    assert acog["categoria"] == "II"
    assert acog["difiere_de_mefi"] is True
    assert "MEFI clasifica en Categoría III" in acog["nota_comparativa"]


def test_fase_a5_acog_estricta_concordante_en_sinusoidal_y_variabilidad_ausente():
    # Sinusoidal -> ambos clasifican en Categoría III
    tiempo = np.arange(0, 1200, 1.0)
    fcf = 130.0 + 8.0 * np.sin(2 * np.pi * tiempo * (4.0 / 60.0))
    features = clinical.extraer_features(_df(tiempo, fcf))
    assert features["figo"]["categoria"] == "III"
    assert features["acog_estricta"]["categoria"] == "III"
    assert features["acog_estricta"]["difiere_de_mefi"] is False


# --------------------------------------------------------------------------
# Fase B (MEFI v2.0): Definiciones NICHD/ACOG y validación de umbrales
# --------------------------------------------------------------------------


def test_fase_b1_desaceleracion_prolongada_120s():
    # Desaceleración de 135s (>=120s y <180s): debe marcar prolongada=True y muy_prolongada=False
    tiempo = np.arange(0, 360, 1.0)
    fcf = np.full(len(tiempo), 140.0)
    fcf[60:196] = 115.0  # 135s de duración
    eventos = clinical.detectar_desaceleraciones(_df(tiempo, fcf), basal=140.0)
    assert len(eventos) == 1
    assert eventos[0]["prolongada"] is True
    assert eventos[0]["muy_prolongada"] is False


def test_fase_b2_patron_sinusoidal_20_min():
    # 12 min (720s) no alcanza los 20 min (1200s) exigidos por ACOG Tabla 1
    t_12m = np.arange(0, 720, 1.0)
    fcf_12m = 130.0 + 8.0 * np.sin(2 * np.pi * t_12m * (4.0 / 60.0))
    res_12m = clinical.detectar_patron_sinusoidal(_df(t_12m, fcf_12m))
    assert res_12m["presente"] is False
    assert "20 minutos" in res_12m["motivo"]

    # 20 min (1200s) sí alcanza el umbral ACOG y expone duración + nota Protocolo V2 (>30 min)
    t_20m = np.arange(0, 1200, 1.0)
    fcf_20m = 130.0 + 8.0 * np.sin(2 * np.pi * t_20m * (4.0 / 60.0))
    res_20m = clinical.detectar_patron_sinusoidal(_df(t_20m, fcf_20m))
    assert res_20m["presente"] is True
    assert res_20m["duracion_evaluada_min"] == 20.0
    assert res_20m["cumple_30min_protocolo_v2"] is False
    assert "30 min" in res_20m["nota_protocolo_v2"]


def test_fase_b3_aceleraciones_por_edad_gestacional_y_prolongada():
    tiempo = np.arange(0, 400, 1.0)
    fcf = np.full(len(tiempo), 135.0)
    # Evento 1: +12 lpm durante 12s (cumple 10x10 de <32 sem, pero NO cumple 15x15 a término)
    fcf[40:53] = 147.0
    # Evento 2: +20 lpm durante 150s (2.5 min -> aceleración prolongada en ambas edades)
    fcf[120:271] = 155.0
    df = _df(tiempo, fcf)

    ac_termino = clinical.detectar_aceleraciones(df, basal=135.0, edad_gestacional_sem="39+2 sem")
    assert len(ac_termino) == 1
    assert ac_termino[0]["prolongada"] is True
    assert ac_termino[0]["etiqueta"] == "aceleración prolongada"

    ac_pret = clinical.detectar_aceleraciones(df, basal=135.0, edad_gestacional_sem="30+4 sem")
    assert len(ac_pret) == 2
    assert ac_pret[0]["prolongada"] is False
    assert ac_pret[0]["criterio_lpm_s"] == "10x10"
    assert ac_pret[1]["prolongada"] is True


def test_fase_b4_taquisistolia_ventana_30m_y_respaldo():
    # Caso 1: registro de 60 min (3600s) donde los primeros 30 min tienen 16 contracciones (5.3/10 min > 5)
    # y los últimos 30 min tienen 0 contracciones (tasa global = 16/6 = 2.7/10 min < 5, pero ventana 30m = 5.3 > 5)
    picos_30m = [100.0 + i * 105.0 for i in range(16)]
    res_30m = clinical._calcular_taquisistolia_ventana_30m(picos_30m, 0.0, 3600.0)
    assert res_30m["evaluada_30m"] is True
    assert res_30m["por_10min_ventana_30m"] == 5.3
    assert res_30m["tachisistolia_acog_30m"] is True

    # Caso 2: registro corto (<30 min, 660s) -> evaluada_30m es False, opera respaldo global
    res_corto = clinical._calcular_taquisistolia_ventana_30m([100.0, 200.0, 300.0], 0.0, 660.0)
    assert res_corto["evaluada_30m"] is False
    assert res_corto["por_10min_ventana_30m"] is None


def test_fase_b5_variabilidad_4_categorias_nichd():
    tiempo = np.arange(0, 300, 1.0)

    # 1. Ausente (<1.0 lpm)
    v_aus = clinical.calcular_variabilidad(_df(tiempo, np.full(len(tiempo), 140.0)), basal=140.0)
    assert v_aus["categoria"] == "reducida"
    assert v_aus["categoria_nichd"] == "ausente"

    # 2. Mínima (1.0 a 5.0 lpm -> oscilación pico-a-pico ~3.0 lpm)
    fcf_min = 140.0 + 1.5 * np.sin(2 * np.pi * tiempo / 20.0)
    v_min = clinical.calcular_variabilidad(_df(tiempo, fcf_min), basal=140.0)
    assert v_min["categoria"] == "reducida"
    assert v_min["categoria_nichd"] == "minima"

    # 3. Moderada (6 a 25 lpm -> oscilación pico-a-pico ~12 lpm)
    fcf_mod = 140.0 + 6.0 * np.sin(2 * np.pi * tiempo / 20.0)
    v_mod = clinical.calcular_variabilidad(_df(tiempo, fcf_mod), basal=140.0)
    assert v_mod["categoria"] == "normal"
    assert v_mod["categoria_nichd"] == "moderada"

    # 4. Marcada (>25 lpm -> oscilación pico-a-pico ~36 lpm)
    fcf_marc = 140.0 + 18.0 * np.sin(2 * np.pi * tiempo / 20.0)
    v_marc = clinical.calcular_variabilidad(_df(tiempo, fcf_marc), basal=140.0)
    assert v_marc["categoria"] == "aumentada"
    assert v_marc["categoria_nichd"] == "marcada"


def test_fase_b6_variabilidad_intra_desaceleracion():
    tiempo = np.arange(0, 400, 1.0)
    fcf_plana = np.full(len(tiempo), 140.0)
    # Desaceleración prolongada (150s >= 120s) con fondo casi plano (<5 lpm)
    fcf_plana[80:231] = 100.0 + 0.5 * np.sin(2 * np.pi * tiempo[80:231] / 10.0)
    ev_plana = clinical.detectar_desaceleraciones(_df(tiempo, fcf_plana), basal=140.0)
    assert len(ev_plana) == 1
    assert ev_plana[0]["prolongada"] is True
    assert ev_plana[0]["variabilidad_reducida_intra_evento"] is True
    assert ev_plana[0]["variabilidad_intra_lpm"] < 5.0

    # Desaceleración prolongada (150s >= 120s) con variabilidad conservada intra-evento (~12 lpm pico-a-pico)
    fcf_osc = np.full(len(tiempo), 140.0)
    fcf_osc[80:231] = 100.0 + 6.0 * np.sin(2 * np.pi * tiempo[80:231] / 8.0)
    ev_osc = clinical.detectar_desaceleraciones(_df(tiempo, fcf_osc), basal=140.0)
    assert len(ev_osc) == 1
    assert ev_osc[0]["prolongada"] is True
    assert ev_osc[0]["variabilidad_reducida_intra_evento"] is False
    assert ev_osc[0]["variabilidad_intra_lpm"] >= 5.0


# --------------------------------------------------------------------------
# Fase C (MEFI v2.0): Criterios «60», Tipificación de Hipoxia, Contexto y Tabla UI
# --------------------------------------------------------------------------


def test_fase_c1_criterios_60_desaceleraciones_variables():
    # Dos desaceleraciones variables con >=2 criterios «60» (duración >60s, nadir <60 lpm, caída >60 lpm)
    # separadas por >30 min (1800s) -> alerta_activa = True
    eventos = [
        {
            "inicio_s": 100.0,
            "fin_s": 175.0,
            "duracion_s": 75.0,  # >60s (1)
            "nadir_lpm": 55.0,   # <60 lpm (2)
            "amplitud_max_lpm": 85.0,  # >60 lpm (3)
            "tipo": "variable",
        },
        {
            "inicio_s": 2000.0,
            "fin_s": 2070.0,
            "duracion_s": 70.0,  # >60s (1)
            "nadir_lpm": 68.0,
            "amplitud_max_lpm": 72.0,  # >60 lpm (2)
            "tipo": "variable",
        },
    ]
    res = clinical.evaluar_criterios_60(eventos)
    assert res["alerta_activa"] is True
    assert res["num_eventos_dos_o_mas_criterios"] == 2
    assert res["lapso_persistencia_min"] > 30.0
    assert "ACTIVO" in res["resumen"]


def test_fase_c2_tipificacion_hipoxia_cuatro_subtipos():
    # 1. Aguda: desaceleración >3 min (200s) con variabilidad reducida intra-evento
    f_aguda = {
        "linea_base": 140.0,
        "variabilidad": {"categoria": "normal", "amplitud_media_lpm": 10.0},
        "aceleraciones": [],
        "desaceleraciones": [
            {
                "inicio_s": 50.0,
                "fin_s": 250.0,
                "duracion_s": 200.0,
                "muy_prolongada": False,
                "variabilidad_reducida_intra_evento": True,
                "tipo": "variable",
            }
        ],
    }
    res_ag = clinical.tipificar_hipoxia(f_aguda)
    assert res_ag["tipo"] == "Aguda"
    assert res_ag["activa"] is True

    # 2. Subaguda: >50% del tiempo total desacelerando (360s de 600s)
    f_sub = {
        "linea_base": 140.0,
        "variabilidad": {"categoria": "normal", "amplitud_media_lpm": 10.0},
        "aceleraciones": [],
        "desaceleraciones": [
            {"inicio_s": 20.0, "fin_s": 140.0, "duracion_s": 120.0, "tipo": "variable"},
            {"inicio_s": 200.0, "fin_s": 320.0, "duracion_s": 120.0, "tipo": "variable"},
            {"inicio_s": 380.0, "fin_s": 500.0, "duracion_s": 120.0, "tipo": "variable"},
        ],
    }
    res_sub = clinical.tipificar_hipoxia(f_sub)
    assert res_sub["tipo"] == "Subaguda"
    assert res_sub["activa"] is True

    # 3. Progresiva: sin aceleraciones + desaceleraciones repetitivas + taquicardia (165 lpm)
    f_prog = {
        "linea_base": 165.0,
        "variabilidad": {"categoria": "normal", "amplitud_media_lpm": 8.0},
        "aceleraciones": [],
        "desaceleraciones": [
            {"inicio_s": 100.0, "fin_s": 145.0, "duracion_s": 45.0, "tipo": "tardia"},
            {"inicio_s": 300.0, "fin_s": 345.0, "duracion_s": 45.0, "tipo": "tardia"},
            {"inicio_s": 500.0, "fin_s": 545.0, "duracion_s": 45.0, "tipo": "tardia"},
        ],
    }
    res_prog = clinical.tipificar_hipoxia(f_prog)
    assert res_prog["tipo"] == "Progresiva"
    assert res_prog["activa"] is True

    # 4. Crónica: línea base en límite alto (155 lpm) + variabilidad reducida + sin aceleraciones
    f_cron = {
        "linea_base": 155.0,
        "variabilidad": {"categoria": "reducida", "amplitud_media_lpm": 3.0},
        "aceleraciones": [],
        "desaceleraciones": [],
    }
    res_cron = clinical.tipificar_hipoxia(f_cron)
    assert res_cron["tipo"] == "Crónica"
    assert res_cron["activa"] is True


def test_fase_c3_c4_contexto_estructurado_y_tabla_ui():
    import fitz
    import prompts
    import reporte_pdf
    import ux_helpers

    tiempo = np.arange(0, 600, 1.0)
    fcf = 140.0 + 7.0 * np.sin(2 * np.pi * tiempo / 20.0)
    features = clinical.extraer_features(_df(tiempo, fcf), edad_gestacional_sem="39+1 sem")
    meta = {
        "id": "caso_c3",
        "fecha_hora": "2026-11-09 10:00",
        "velocidad_papel_cm_min": 1.0,
        "edad_gestacional": "39+1 sem",
        "contexto_clinico": "Trabajo de parto fase activa",
        "uso_oxitocina": "En conducción con oxitocina",
        "meconio": "Sí (meconio presente)",
        "patologia_antenatal": "RCIU estadio I",
        "comparacion_mefi_previos": "Descenso de variabilidad respecto a MEFI de hace 2h",
    }

    prompt_usr = prompts.construir_prompt_usuario(features, metadatos=meta)
    assert "Sí (meconio presente)" in prompt_usr
    assert "RCIU estadio I" in prompt_usr
    assert "Descenso de variabilidad respecto a MEFI de hace 2h" in prompt_usr

    inf_plantilla = prompts.generar_informe_plantilla(features, metadatos=meta)
    assert "Sí (meconio presente)" in inf_plantilla
    assert "RCIU estadio I" in inf_plantilla
    assert "Descenso de variabilidad respecto a MEFI de hace 2h" in inf_plantilla

    pdf_bytes = reporte_pdf.generar_pdf_consolidado(
        features=features,
        informe_plantilla=inf_plantilla,
        metadatos=meta,
    )
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    texto_pdf = "\n".join(page.get_text() for page in doc)
    doc.close()
    assert "RCIU estadio I" in texto_pdf
    assert "meconio presente" in texto_pdf

    # Verificar columnas C4 en tabla de desaceleraciones
    filas = ux_helpers.formatear_tabla_desaceleraciones([
        {
            "inicio_s": 60.0,
            "fin_s": 195.0,
            "duracion_s": 135.0,
            "nadir_lpm": 55.0,
            "amplitud_max_lpm": 80.0,
            "tipo": "variable",
            "prolongada": True,
            "muy_prolongada": False,
            "variabilidad_intra_lpm": 2.4,
            "variabilidad_reducida_intra_evento": True,
        }
    ])
    assert len(filas) == 1
    assert "3/3" in filas[0]["Criterios «60» (Variables)"]
    assert "Reducida" in filas[0]["Variabilidad intra-evento (≥2 min)"]
    assert "Prolongada (≥2 min)" in filas[0]["Alerta prolongada (≥2 min)"]












