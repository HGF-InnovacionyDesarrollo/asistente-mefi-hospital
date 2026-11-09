"""Prompt clínico versionado aparte de la UI (Fase 3 del plan) — importa que en
un contexto clínico se pueda saber exactamente qué prompt generó qué informe.

Desde esta fase el LLM ya NO recibe la imagen del trazado: razona en texto sobre
el dict de `clinical.py` (`extraer_features()`), anclado a los mismos umbrales
FIGO 2015 / NICE NG229 que usó el código determinístico para clasificar — se
importan directo de `clinical` para que nunca queden desincronizados.
"""

from __future__ import annotations

import clinical

VERSION_PROMPT = "v2.0-final-2026-11-09"

SYSTEM_INSTRUCTIONS = f"""# SYSTEM INSTRUCTIONS: Asesor Clínico MEFI - Hospital Dr. Gustavo Fricke ({VERSION_PROMPT})

## 1. IDENTIDAD Y ROL
**Rol:** Eres un Asistente Clínico Experto en Medicina Materno-Fetal.
**Misión:** Interpretar variables cardiotocográficas (MEFI) ya digitalizadas y
clasificadas de forma determinística, y proponer razonamiento clínico y conducta
sugerida basada en el Protocolo de Vigilancia del Bienestar Fetal Intraparto V2
(Hospital Dr. Gustavo Fricke, sept. 2025), ACOG Clinical Practice Guideline No. 10
(Obstet Gynecol 2025;146:583–599), FIGO 2015 y NICE NG229.

## 2. QUÉ RECIBES Y QUÉ NO
No ves la imagen del trazado. Recibes las variables FCF/UA ya extraídas por
visión clásica (no un LLM) y ya clasificadas según los umbrales FIGO 2015 /
NICE NG229 listados abajo — NO inventes ni corrijas esas cifras, tu trabajo es
interpretarlas clínicamente, no releerlas.

## 3. UMBRALES DE REFERENCIA (FIGO 2015 / NICE NG229 / ACOG CPG No. 10 / Protocolo V2)
- Línea base normal: {clinical.BASAL_MIN_NORMAL}-{clinical.BASAL_MAX_NORMAL} lpm.
- Variabilidad (banda de amplitud pico-a-pico por minuto): reducida <{clinical.VARIABILIDAD_REDUCIDA_MAX} lpm
  (ACOG distingue ausente <{clinical.VARIABILIDAD_AUSENTE_MAX_LPM} lpm vs mínima ≤{clinical.VARIABILIDAD_REDUCIDA_MAX} lpm),
  normal/moderada {clinical.VARIABILIDAD_REDUCIDA_MAX}-{clinical.VARIABILIDAD_NORMAL_MAX} lpm, aumentada/marcada >{clinical.VARIABILIDAD_NORMAL_MAX} lpm.
- Aceleración/desaceleración: >={clinical.UMBRAL_ACEL_DECEL} lpm respecto de la línea base,
  sostenido >={clinical.DURACION_MIN_EVENTO_S}s (en <32 semanas de EG: >=10 lpm por >=10s).
- Desaceleración "prolongada" (ACOG Tabla 1 / Protocolo V2): >={clinical.DESACEL_PROLONGADA_MIN_S // 60} min ({clinical.DESACEL_PROLONGADA_MIN_S}s).
- Desaceleración "muy prolongada" (criterio patológico directo FIGO 2015): >={clinical.DESACEL_MUY_PROLONGADA_S // 60} min ({clinical.DESACEL_MUY_PROLONGADA_S}s).
- Patrón sinusoidal: oscilación regular {clinical.SINUSOIDAL_FRECUENCIA_MIN_CPM}-{clinical.SINUSOIDAL_FRECUENCIA_MAX_CPM}
  ciclos/min, amplitud {clinical.SINUSOIDAL_AMPLITUD_MIN}-{clinical.SINUSOIDAL_AMPLITUD_MAX} lpm, sostenida
  >={clinical.SINUSOIDAL_DURACION_MIN_S // 60} min (ACOG Tabla 1; Protocolo V2 exige >30 min sin aceleraciones).
- Contracciones (NICE NG229 / ACOG CPG No. 10 / Protocolo V2): NICE NG229 define ámbar con >=5 en 10 min
  (respaldo en registros <30 min); ACOG CPG No. 10 y Protocolo V2 definen taquisistolía como >5 contracciones
  en 10 minutos promediadas en una ventana de 30 minutos. Ambos criterios se reportan explícitamente.
- Categorías FIGO 2015: I (Normal) / II (Sospechoso) / III (Patológico).

## 4. ESTRUCTURA Y RAZONAMIENTO ESPERADO (OBLIGATORIO PARA COMPARACIÓN)
Debes organizar tu respuesta en **exactamente estas 4 secciones numeradas** con encabezados `####`, para que el clínico pueda compararlas fila por fila contra el informe determinístico por plantilla:

#### 1. Parámetros Cardiotocográficos Extraídos
Sintetiza el hallazgo principal en 1-2 frases concisas integrando línea base, variabilidad, aceleraciones, desaceleraciones (y su área acumulada), actividad uterina y, si aplica, la alerta de verificación de pulso materno (ACOG CPG No. 10).

#### 2. Clasificación Normativa (FIGO 2015 / NICE NG229 / ACOG CPG No. 10)
Indica la Categoría FIGO (I, II o III), el semáforo NICE, la estratificación de riesgo Box 3 ACOG para Categoría II (alto / intermedio / con rasgos protectores) y la lectura comparativa ACOG estricta vs. MEFI cuando difieran.

#### 3. Correlación Fisiopatológica (Según Patrón Observado)
Razona sobre la reserva autonómica y el **mecanismo fisiopatológico / tipo de hipoxia** más consistente con el patrón observado (precoz → compresión cefálica vagal; variable → compresión funicular; tardía repetitiva → insuficiencia uteroplacentaria) según el consenso fisiológico 2018/revisión 2024 — sin afirmar un diagnóstico definitivo.

#### 4. Conducta Sugerida según Protocolo
Propone medidas clínicas concretas con lenguaje de «conducta sugerida» alineadas con Protocolo V2 (sept. 2025) y ACOG CPG No. 10 (2025):
- En **Categoría II**: aviso inmediato al médico/a ginecobstetra residente de turno (responsabilidad de la matrón/a según Protocolo V2); reanimación intrauterina (lateralización materna, hidratación EV/corrección de hipotensión, reducir o suspender oxitocina, amnioinfusión si hay desaceleraciones variables recurrentes, corrección de fisiopatología materna si hay taquicardia, oxígeno suplementario SOLO si hipoxia materna SatO2 < 94 % citando recomendación ACOG contra uso rutinario, y tocolisis de acción rápida —nitroglicerina/fenoterol institucional; ACOG cita terbutalina— si persiste taquisistolía con rasgos de alto riesgo); observación de ½ a 1 hora según Protocolo V2 matizada por Box 3 ACOG (explicitando que ACOG individualiza los tiempos).
- En **Categoría III**: aviso inmediato y reanimación urgente; matices ACOG por subtipo (bradicardia con sospecha de rotura uterina → parto lo antes posible; contracción tetánica/taquisistolía → suspender uterotónicos y considerar tocolisis de acción rápida antes del parto; sinusoidal > 30 min → parto expedito); conservar máximo de 10 minutos de observación del Protocolo V2 si no revierte antes de interrupción expedita.
- Cerrar siempre con el disclaimer regulador: ACOG CPG No. 10 recomienda contra depender primariamente de sistemas computarizados (fuerte, evidencia moderada) y referenciar el ensayo INFANT (Lancet 2017); requiere validación humana obligatoria.

Responde en Markdown, en español, de forma directa y concisa (con viñetas breves).
No inventes valores numéricos que no estén en los datos recibidos.
"""


def construir_prompt_usuario(features: dict, metadatos: dict | None = None) -> str:
    """Renderiza el dict de `clinical.extraer_features()` como texto estructurado
    para el LLM — nunca se manda la imagen ni datos filiatorios (PHI)."""
    basal = features["linea_base"]
    variabilidad = features["variabilidad"]
    aceleraciones = features["aceleraciones"]
    desaceleraciones = features["desaceleraciones"]
    sinusoidal = features["patron_sinusoidal"]
    figo = features["figo"]
    riesgo_cat2 = features.get("riesgo_categoria_ii") or clinical.evaluar_riesgo_categoria_ii(features)
    sospecha_mat = features.get("sospecha_fcf_materna") or clinical.detectar_sospecha_fcf_materna(features)
    acog_estricta = features.get("acog_estricta") or clinical.clasificar_acog_estricta(features)
    criterios_60 = features.get("criterios_60") or clinical.evaluar_criterios_60(desaceleraciones)
    hipoxia_tip = features.get("hipoxia_tipificada") or clinical.tipificar_hipoxia(features)

    lineas = [
        "Interpreta el siguiente registro CTG ya digitalizado y clasificado. "
        "Las cifras no fueron leídas por ti ni por ningún modelo de visión.",
    ]
    if metadatos:
        ctx_partes = []
        if metadatos.get("edad_gestacional"):
            ctx_partes.append(f"Edad gestacional: {metadatos['edad_gestacional']}")
        if metadatos.get("contexto_clinico") and metadatos["contexto_clinico"] != "No especificado":
            ctx_partes.append(f"Etapa/contexto: {metadatos['contexto_clinico']}")
        if metadatos.get("uso_oxitocina") and metadatos["uso_oxitocina"] != "No especificado":
            ctx_partes.append(f"Dinámica farmacológica: {metadatos['uso_oxitocina']}")
        if metadatos.get("meconio") and metadatos["meconio"] != "No especificado":
            ctx_partes.append(f"Meconio en líquido amniótico: {metadatos['meconio']}")
        if metadatos.get("patologia_antenatal"):
            ctx_partes.append(f"Patología antenatal: {metadatos['patologia_antenatal']}")
        if metadatos.get("comparacion_mefi_previos"):
            ctx_partes.append(f"Comparación con MEFI previos: {metadatos['comparacion_mefi_previos']}")
        if ctx_partes:
            lineas.extend(["", "## Contexto obstétrico aportado", " · ".join(ctx_partes)])

    lineas.extend([
        "",
        f"## Línea base\n{basal:.0f} lpm.",
        "",
        f"## Variabilidad\n{variabilidad['amplitud_media_lpm']} lpm de amplitud media "
        f"({variabilidad['ventanas_evaluadas']} ventanas de 1 min evaluadas) — "
        f"categoría FIGO/NICE: **{variabilidad['categoria']}** "
        f"(NICHD/ACOG: **{variabilidad.get('categoria_nichd', variabilidad['categoria'])}**).",
        "",
        f"## Aceleraciones\n{len(aceleraciones)} detectada(s).",
    ])
    for a in aceleraciones[:10]:
        etiq_ac = " [aceleración prolongada]" if a.get("prolongada") else ""
        lineas.append(f"- {a['inicio_s']:.0f}s-{a['fin_s']:.0f}s ({a['duracion_s']:.0f}s), +{a['amplitud_max_lpm']:.0f} lpm{etiq_ac}.")
    if sospecha_mat.get("sospecha"):
        lineas.append(f"- {sospecha_mat['mensaje']}")

    lineas.append("")
    area_total = features.get("area_desaceleraciones_lpm_s")
    lineas.append(
        f"## Desaceleraciones\n{len(desaceleraciones)} detectada(s)"
        + (f" — área total bajo la curva: {area_total} lpm·s "
           f"(severidad cuantitativa acumulada: a mayor área, mayor carga hipóxica "
           f"transitoria sufrida)." if area_total is not None else ".")
    )
    for d in desaceleraciones[:10]:
        marcas = []
        if d.get("prolongada"):
            marcas.append("prolongada")
        if d.get("muy_prolongada"):
            marcas.append("muy prolongada")
        if d.get("variabilidad_reducida_intra_evento"):
            marcas.append(f"variabilidad intra-evento reducida ({d.get('variabilidad_intra_lpm')} lpm <5 lpm)")
        if d.get("criterios_60_cumplidos"):
            marcas.append(f"criterios «60»: {', '.join(d['criterios_60_cumplidos'])}")
        sufijo = f" [{', '.join(marcas)}]" if marcas else ""
        lineas.append(
            f"- tipo **{d.get('tipo', 'sin clasificar')}**, {d['inicio_s']:.0f}s-{d['fin_s']:.0f}s "
            f"({d['duracion_s']:.0f}s), nadir {d.get('nadir_lpm', basal - d['amplitud_max_lpm']):.0f} lpm "
            f"(-{d['amplitud_max_lpm']:.0f} lpm){sufijo}."
        )
    if criterios_60.get("num_eventos_dos_o_mas_criterios", 0) > 0:
        lineas.append(f"- {criterios_60['resumen']}")

    lineas.append("")
    if sinusoidal.get("presente"):
        lineas.append(
            f"## Patrón sinusoidal\nPresente — {sinusoidal['frecuencia_dominante_cpm']} ciclos/min, "
            f"amplitud {sinusoidal['amplitud_lpm']} lpm."
        )
    else:
        lineas.append(f"## Patrón sinusoidal\nNo detectado ({sinusoidal.get('motivo', 'sin hallazgos')}).")

    lineas.append("")
    contr = features.get("contracciones") or {}
    if contr.get("num") is not None:
        tasa_30m = contr.get("por_10min_ventana_30m")
        acog_30m = contr.get("tachisistolia_acog_30m", False)
        txt_30m = (
            f"; promedio móvil máx. en ventana de 30 min: {tasa_30m}/10 min "
            f"({'taquisistolía ACOG >5/10 min' if acog_30m else 'sin taquisistolía ACOG 30 min'})"
            if tasa_30m is not None
            else "; registro <30 min (se usa tasa global como respaldo)"
        )
        lineas.append(
            f"## Contracciones uterinas\n{contr['num']} detectada(s) "
            f"(tasa global: {contr.get('por_10min')} por 10 minutos{txt_30m}) — "
            + ("**tachisistolia presente** (criterio ámbar NICE NG229 / ACOG)." if contr.get("tachisistolia") else "frecuencia dentro de rango normal.")
        )
    else:
        lineas.append("## Contracciones uterinas\nSin datos de UA para evaluar frecuencia.")
    lineas.append("")
    lineas.append(
        f"## Clasificación FIGO 2015 / NICE NG229 y Comparativo ACOG CPG No. 10\n"
        f"**Categoría MEFI (FIGO/NICE): Categoría {figo['categoria']} — {figo['descripcion']}**\n"
        f"Razones: {'; '.join(figo['razones'])}\n"
        f"Semáforo NICE: línea base={figo['semaforo_nice']['linea_base']}, "
        f"variabilidad={figo['semaforo_nice']['variabilidad']}, "
        f"desaceleraciones={figo['semaforo_nice']['desaceleraciones']}, "
        f"contracciones={figo['semaforo_nice'].get('contracciones', 'verde')}.\n"
        f"Estratificación Box 3 ACOG (Categoría II): nivel **{riesgo_cat2['nivel']}** ({'; '.join(riesgo_cat2['razones'])}).\n"
        f"Comparativo ACOG CPG No. 10 estricta: {acog_estricta['nota_comparativa']}\n"
        f"Tipificación determinística de hipoxia (Protocolo V2): {hipoxia_tip['resumen']}"
    )

    return "\n".join(lineas)


def generar_informe_plantilla(features: dict, metadatos: dict | None = None) -> str:
    """Genera un informe clínico estructurado 100% determinístico a partir de
    `features` (calculado por `clinical.extraer_features()`) y los protocolos
    FIGO 2015 / NICE NG229 / ACOG CPG No. 10 (2025) / Protocolo Institucional V2
    (sept. 2025), sin requerir conexión a ningún LLM.
    """
    basal = features["linea_base"]
    variabilidad = features["variabilidad"]
    aceleraciones = features["aceleraciones"]
    desaceleraciones = features["desaceleraciones"]
    sinusoidal = features["patron_sinusoidal"]
    contr = features.get("contracciones") or {}
    area_total = features.get("area_desaceleraciones_lpm_s")
    figo = features["figo"]
    semaforo = figo["semaforo_nice"]
    riesgo_cat2 = features.get("riesgo_categoria_ii") or clinical.evaluar_riesgo_categoria_ii(features)
    sospecha_mat = features.get("sospecha_fcf_materna") or clinical.detectar_sospecha_fcf_materna(features)
    acog_estricta = features.get("acog_estricta") or clinical.clasificar_acog_estricta(features)
    criterios_60 = features.get("criterios_60") or clinical.evaluar_criterios_60(desaceleraciones)
    hipoxia_tip = features.get("hipoxia_tipificada") or clinical.tipificar_hipoxia(features)

    icono_color = {"verde": "🟢 Normal (Blanco/Verde)", "amarillo": "🟡 Sospechoso (Ámbar)", "rojo": "🔴 Patológico (Rojo)"}

    # --- Evaluación línea base ---
    if basal < clinical.BASAL_MIN_NORMAL:
        estado_basal = f"bradicardia (<{clinical.BASAL_MIN_NORMAL} lpm)"
    elif basal > clinical.BASAL_MAX_NORMAL:
        estado_basal = f"taquicardia (>{clinical.BASAL_MAX_NORMAL} lpm)"
    else:
        estado_basal = f"normocardia ({clinical.BASAL_MIN_NORMAL}–{clinical.BASAL_MAX_NORMAL} lpm)"

    # --- Evaluación aceleraciones ---
    if aceleraciones:
        amp_max_acel = max(a["amplitud_max_lpm"] for a in aceleraciones)
        n_acel_prol = sum(1 for a in aceleraciones if a.get("prolongada"))
        txt_acel_prol = f", incluyendo {n_acel_prol} aceleración(es) prolongada(s) (2–10 min)" if n_acel_prol else ""
        resumen_acel = (
            f"{len(aceleraciones)} detectada(s) (reactividad presente, "
            f"amplitud máx. +{amp_max_acel:.0f} lpm sobre la basal{txt_acel_prol})."
        )
    else:
        resumen_acel = "No se detectaron aceleraciones en el segmento analizado."

    # --- Evaluación desaceleraciones ---
    conteo_tipos: dict[str, int] = {}
    for d in desaceleraciones:
        t = d.get("tipo", "indeterminada")
        conteo_tipos[t] = conteo_tipos.get(t, 0) + 1
    n_prolongadas = sum(1 for d in desaceleraciones if d.get("prolongada") and not d.get("muy_prolongada"))
    n_muy_prolongadas = sum(1 for d in desaceleraciones if d.get("muy_prolongada"))

    if desaceleraciones:
        etiquetas_tipo = {
            "precoz": "precoz/precoces",
            "tardia": "tardía(s)",
            "variable": "variable(s)",
            "indeterminada": "indeterminada(s)",
        }
        desglose = ", ".join(
            f"{cant} {etiquetas_tipo.get(tipo, tipo)}" for tipo, cant in conteo_tipos.items()
        )
        partes_prol = []
        if n_prolongadas:
            partes_prol.append(f"{n_prolongadas} prolongada(s) (≥{clinical.DESACEL_PROLONGADA_MIN_S // 60} min)")
        if n_muy_prolongadas:
            partes_prol.append(f"{n_muy_prolongadas} muy prolongada(s) (≥{clinical.DESACEL_MUY_PROLONGADA_S // 60} min)")
        texto_prol = f" [{'; '.join(partes_prol)}]" if partes_prol else ""
        texto_area = (
            f" — área acumulada bajo desaceleraciones: **{area_total:,} lpm·s**".replace(",", ".")
            if area_total is not None
            else ""
        )
        resumen_decel = f"{len(desaceleraciones)} detectada(s) ({desglose}){texto_prol}{texto_area}."
    else:
        resumen_decel = "No se detectaron desaceleraciones significativas (≥15 lpm por ≥15 s)."

    # --- Evaluación contracciones ---
    if contr.get("num") is not None:
        por_10 = contr.get("por_10min")
        por_30m = contr.get("por_10min_ventana_30m")
        acog_30m = contr.get("tachisistolia_acog_30m", False)
        tasa_str = f" (tasa global: {por_10} cada 10 min" if por_10 is not None else " ("
        if por_30m is not None:
            tasa_str += f"; promedio móvil 30 min: {por_30m} cada 10 min [{'ACOG >5: positivo' if acog_30m else 'ACOG >5: negativo'}])"
        else:
            tasa_str += "; registro <30 min, aplica respaldo de tasa global)"
        estado_ua = (
            "**taquisistolia presente** (criterio ámbar NICE NG229 ≥5/10 min y/o ACOG >5/10 min en 30 min)"
            if contr.get("tachisistolia")
            else "frecuencia normal (<5 en 10 min global y en ventana de 30 min)"
        )
        resumen_ua = f"{contr['num']} contracción(es) detectada(s){tasa_str} — {estado_ua}."
    else:
        resumen_ua = "Sin señal de actividad uterina (UA) suficiente para cuantificar dinámica."

    # --- Evaluación patrón sinusoidal ---
    if sinusoidal.get("presente"):
        dur_sin_min = sinusoidal.get("duracion_evaluada_min")
        dur_txt = f", duración efectiva {dur_sin_min} min" if dur_sin_min is not None else ""
        resumen_sin = (
            f"**Presente** ({sinusoidal.get('frecuencia_dominante_cpm')} ciclos/min, "
            f"amplitud {sinusoidal.get('amplitud_lpm')} lpm{dur_txt}; "
            f"nota normativa: ACOG exige ≥20 min y Protocolo V2 exige >30 min con ausencia de aceleraciones)."
        )
    else:
        resumen_sin = f"No detectado ({sinusoidal.get('motivo', 'sin hallazgos')})."

    # --- Correlación fisiopatológica por reglas ---
    puntos_fisio = []
    cat_var = variabilidad["categoria"]
    if cat_var == "normal":
        puntos_fisio.append(
            "- **Reserva autonómica conservada:** la variabilidad moderada/normal (5–25 lpm) sugiere "
            "integridad y adecuada oxigenación actual del sistema nervioso autónomo fetal."
        )
    elif cat_var == "reducida":
        puntos_fisio.append(
            "- **Variabilidad reducida (<5 lpm):** puede reflejar ciclo de sueño fetal fisiológico "
            "(habitualmente <40 min), efecto de fármacos depresores del SNC o hipoxia/acidemia en evolución "
            "si se asocia a desaceleraciones."
        )
    else:
        puntos_fisio.append(
            "- **Variabilidad aumentada / patrón saltatorio (>25 lpm):** sugiere respuesta autonómica "
            "adrenérgica compensatoria ante estrés hipóxico agudo o compresión funicular."
        )

    if desaceleraciones:
        if conteo_tipos.get("precoz"):
            puntos_fisio.append(
                "- **Desaceleraciones precoces:** compatibles con reflejo vagal por compresión cefálica "
                "durante la contracción; hallazgo habitualmente benigno cuando la variabilidad es normal."
            )
        if conteo_tipos.get("variable"):
            puntos_fisio.append(
                "- **Desaceleraciones variables:** patrón abrupto mediado por barorreceptores/quimiorreceptores, "
                "típicamente asociado a compresión transitoria del cordón umbilical."
            )
        if conteo_tipos.get("tardia") or conteo_tipos.get("indeterminada"):
            puntos_fisio.append(
                "- **Desaceleraciones tardías / no clasificadas por UA:** sugieren caída transitoria de la "
                "presión parcial de oxígeno en el espacio intervelloso (insuficiencia uteroplacentaria relativa "
                "durante la contracción) con activación de quimiorreceptores."
            )
        if n_prolongadas or n_muy_prolongadas:
            puntos_fisio.append(
                f"- **Desaceleración prolongada (≥{clinical.DESACEL_PROLONGADA_MIN_S // 60} min, ACOG Tabla 1 / Protocolo V2):** "
                "alerta de reducción aguda del flujo uteroplacentario o funicular (descartar hipotensión materna, "
                "hipertonía uterina, prolapso de cordón o descenso rápido)."
            )
    else:
        puntos_fisio.append(
            "- **Sin desaceleraciones periódicas ni episódicas:** no se observan caídas de FCF sugestivas "
            "de compresión funicular ni de insuficiencia uteroplacentaria aguda en este segmento."
        )

    if contr.get("tachisistolia"):
        puntos_fisio.append(
            "- **Dinámica uterina acelerada (taquisistolia):** la presencia de ≥5 contracciones en 10 minutos "
            "acorta el tiempo de reposo intercontráctil necesario para la reperfusión del espacio intervelloso."
        )

    if sinusoidal.get("presente"):
        puntos_fisio.append(
            "- **Patrón sinusoidal:** oscilación regular de alta prioridad clínica asociada a anemia fetal "
            "severa, hipoxia fetal grave o administración materna de opioides/analgésicos."
        )

    # --- Conducta sugerida según categoría FIGO / NICE / Protocolo V2 / ACOG CPG No. 10 (Fase A1) ---
    cat_figo = figo["categoria"]
    if cat_figo == "I":
        conducta = [
            "- **Trazado Categoría I (Normal):** alta probabilidad de bienestar fetal y equilibrio ácido-base conservado (VPN >96%).",
            "- **Conducta sugerida:** mantener vigilancia obstétrica habitual según etapa del trabajo de parto y Protocolo de Vigilancia del Bienestar Fetal Intraparto V2.",
            "- No requiere intervenciones correctivas específicas sobre el monitoreo actual.",
        ]
    elif cat_figo == "II":
        conducta = [
            "- **Trazado Categoría II (Sospechoso / Indeterminado):** **conducta sugerida — aviso inmediato al médico/a ginecobstetra residente de turno** (responsabilidad de la matrón/a según Protocolo V2, sept. 2025) y evaluación integral del contexto materno-fetal.",
            f"- **Estratificación de riesgo Box 3 ACOG CPG No. 10:** nivel **{riesgo_cat2['nivel'].upper()}** ({'; '.join(riesgo_cat2['razones'])}).",
            "- **Maniobras sugeridas de reanimación intrauterina (Protocolo V2 / ACOG CPG No. 10):**",
            "  1. **Lateralización materna** (decúbito lateral izquierdo o derecho) para optimizar el retorno venoso y la perfusión uteroplacentaria;",
            "  2. **Corrección de hipotensión materna e hidratación EV** (bolo de cristaloides y control de signos vitales);",
            "  3. **Reducción o suspensión de agentes de inducción/aceleración (oxitocina)**, especialmente ante desaceleraciones recurrentes o dinámica acelerada;",
            "  4. **Amnioinfusión:** considerar como opción terapéutica ante **desaceleraciones variables recurrentes** por sospecha de compresión funicular (ACOG CPG No. 10 / Protocolo V2);",
            "  5. **Corrección de fisiopatología materna:** si existe taquicardia fetal, evaluar y tratar causas maternas subyacentes (fiebre/corioamnionitis, deshidratación, dolor o fármacos);",
            "  6. **Oxígeno suplementario SOLO si existe hipoxia materna documentada (SatO2 < 94 %):** ACOG CPG No. 10 recomienda en contra de la hiperoxigenación materna rutinaria con saturación materna normal;",
            "  7. **Tocolisis de acción rápida:** si existe taquisistolía asociada a Categoría II con rasgos de alto riesgo que persiste pese a pausar la oxitocina, sugerir agente uterorrelajante de acción rápida (institucional Protocolo V2: **nitroglicerina / fenoterol**; ACOG CPG No. 10 cita **terbutalina**).",
            "- **Ventana de observación y reevaluación:** si el patrón Categoría II persiste pese a las maniobras de reanimación intrauterina, mantener observación estrecha de **½ a 1 hora (30 a 60 minutos)** según Protocolo V2, matizada por los rasgos del **Box 3 ACOG** (ACOG individualiza el tiempo de observación según la presencia de rasgos de alto riesgo vs. rasgos protectores y la evolución clínica).",
        ]
    else:
        conducta = [
            "- **Trazado Categoría III (Patológico):** **alerta de riesgo elevado de hipoxia/acidemia fetal.** **Conducta sugerida: aviso inmediato al médico/a ginecobstetra residente de turno y reanimación intrauterina urgente.**",
            "- **Maniobras urgentes de reanimación intrauterina (Protocolo V2 / ACOG CPG No. 10):**",
            "  1. Lateralización materna inmediata, hidratación EV y corrección de hipotensión materna;",
            "  2. **Suspensión inmediata de oxitocina** u otros uterotónicos;",
            "  3. **Oxígeno suplementario solo ante hipoxia materna (SatO2 < 94 %)** (según ACOG CPG No. 10);",
            "  4. Evaluación obstétrica inmediata para descartar eventos centinela (prolapso de cordón, desprendimiento prematuro de placenta normoinserta, rotura uterina o descenso rápido).",
            "- **Conducta sugerida por subtipo etiológico (ACOG CPG No. 10 / Protocolo V2):**",
            "  - *Bradicardia con sospecha de rotura uterina, desprendimiento o prolapso funicular:* proceder al **parto lo antes posible**;",
            "  - *Contracción tetánica o taquisistolía asociada a Categoría III:* suspender uterotónicos y considerar **tocolisis de acción rápida** (institucional: **nitroglicerina / fenoterol**; ACOG cita **terbutalina**) **antes** del parto;",
            "  - *Patrón sinusoidal persistente (> 30 min según Protocolo V2):* sin beneficio de manejo expectante intraparto, preparar **parto expedito**.",
            "- **Plazo máximo de observación:** si el trazado Categoría III no revierte con las maniobras iniciales en un máximo de **10 minutos** (Protocolo V2), proceder a la **interrupción expedita del embarazo** (parto instrumental o cesárea de urgencia según condiciones obstétricas).",
        ]

    # --- Armado del documento ---
    lineas = [
        f"### Informe Clínico Estructurado por Protocolo (Categoría FIGO {cat_figo})",
    ]
    if metadatos:
        id_reg = metadatos.get("id") or "No especificado"
        fecha_reg = metadatos.get("fecha_hora") or "No especificada"
        vel_reg = metadatos.get("velocidad_papel_cm_min") or 1.0
        extra_ctx = []
        if metadatos.get("edad_gestacional"):
            extra_ctx.append(f"**EG:** `{metadatos['edad_gestacional']}`")
        if metadatos.get("contexto_clinico") and metadatos["contexto_clinico"] != "No especificado":
            extra_ctx.append(f"**Contexto:** `{metadatos['contexto_clinico']}`")
        if metadatos.get("uso_oxitocina") and metadatos["uso_oxitocina"] != "No especificado":
            extra_ctx.append(f"**Oxitocina:** `{metadatos['uso_oxitocina']}`")
        if metadatos.get("meconio") and metadatos["meconio"] != "No especificado":
            extra_ctx.append(f"**Meconio:** `{metadatos['meconio']}`")
        if metadatos.get("patologia_antenatal"):
            extra_ctx.append(f"**Patología antenatal:** `{metadatos['patologia_antenatal']}`")
        if metadatos.get("comparacion_mefi_previos"):
            extra_ctx.append(f"**Comparación MEFI previos:** `{metadatos['comparacion_mefi_previos']}`")
        else:
            extra_ctx.append("**Comparación MEFI previos:** *Pendiente revisar trazados anteriores del caso (Protocolo V2)*")
        sufijo_ctx = (" · " + " · ".join(extra_ctx)) if extra_ctx else ""
        lineas.append(
            f"**Registro:** `{id_reg}` · **Fecha/hora inicio:** `{fecha_reg}` · **Velocidad papel:** `{vel_reg} cm/min`{sufijo_ctx}"
        )
        lineas.append("")

    lineas.extend([
        "#### 1. Parámetros Cardiotocográficos Extraídos",
        f"- **Línea base FCF:** **{basal:.0f} lpm** — {estado_basal}.",
        f"- **Variabilidad:** **{variabilidad['amplitud_media_lpm']} lpm** (categoría FIGO/NICE: **{variabilidad['categoria']}** · NICHD/ACOG: **{variabilidad.get('categoria_nichd', variabilidad['categoria'])}**, evaluada en {variabilidad['ventanas_evaluadas']} ventanas de 1 min).",
        f"- **Aceleraciones:** {resumen_acel}",
        f"- **Desaceleraciones:** {resumen_decel}",
        f"- **Actividad uterina (UA):** {resumen_ua}",
        f"- **Patrón sinusoidal:** {resumen_sin}",
    ])
    if sospecha_mat.get("sospecha"):
        lineas.append(f"- {sospecha_mat['mensaje']}")
    if criterios_60.get("num_eventos_dos_o_mas_criterios", 0) > 0:
        lineas.append(f"- **Criterios «60» en desaceleraciones variables (Protocolo V2):** {criterios_60['resumen']}")

    lineas.extend([
        "",
        "#### 2. Clasificación Normativa (FIGO 2015 / NICE NG229)",
        f"- **Categoría FIGO 2015:** **Categoría {cat_figo} — {figo['descripcion']}**",
        f"- **Criterios determinantes:** {'; '.join(figo['razones'])}",
        f"- **Subclasificador de riesgo Box 3 ACOG (Categoría II):** Nivel **{riesgo_cat2['nivel'].upper()}** ({'; '.join(riesgo_cat2['razones'])}).",
        f"- **Comparativo ACOG CPG No. 10 estricta vs. MEFI:** {acog_estricta['nota_comparativa']}",
        "- **Semáforo por variable (NICE NG229):**",
        f"  - Línea base: {icono_color[semaforo['linea_base']]}",
        f"  - Variabilidad: {icono_color[semaforo['variabilidad']]}",
        f"  - Desaceleraciones: {icono_color[semaforo['desaceleraciones']]}",
        f"  - Contracciones: {icono_color[semaforo.get('contracciones', 'verde')]}",
        "",
        "#### 3. Correlación Fisiopatológica (Según Patrón Observado)",
        f"- {hipoxia_tip['resumen']}",
        *puntos_fisio,
        "",
        "#### 4. Conducta Sugerida según Protocolo",
        *conducta,
        "",
        "---",
        "*Nota reguladora: Informe de conducta sugerida generado mediante plantilla determinística "
        "(Protocolo Institucional V2 sept. 2025 / ACOG CPG No. 10 2025 / FIGO 2015 / NICE NG229). "
        "ACOG CPG No. 10 recomienda en contra de depender primariamente de sistemas computarizados para "
        "interpretar y manejar la FCF (recomendación fuerte, evidencia de calidad moderada; ref. ensayo "
        "INFANT, Lancet 2017). Esta herramienta es de apoyo a la decisión clínica y requiere validación humana obligatoria.*",
    ])

    return "\n".join(lineas)


DIMENSIONES_COMPARACION = [
    ("1", "1. Parámetros y Hallazgo Principal"),
    ("2", "2. Clasificación Normativa (FIGO / NICE)"),
    ("3", "3. Correlación Fisiopatológica"),
    ("4", "4. Conducta Clínica Sugerida"),
]


def extraer_secciones_informe(texto_md: str | None) -> dict[str, str]:
    """Divide un informe (de plantilla o generado por LLM) en las 4 dimensiones
    clínicas numeradas ('1', '2', '3', '4') para mostrarlas alineadas lado a lado.
    Si un modelo libre no numeró sus encabezados exactamente igual, hace fallback
    por palabras clave o agrupa el contenido para no perder texto."""
    import re

    if not texto_md or not texto_md.strip():
        return {k: "*Sin contenido generado aún.*" for k, _ in DIMENSIONES_COMPARACION}

    secciones: dict[str, list[str]] = {"1": [], "2": [], "3": [], "4": []}
    actual: str | None = None

    for linea in texto_md.splitlines():
        s = linea.strip()
        if s.startswith("---"):
            break
        if s.startswith("### ") and "Informe Clínico" in s:
            continue
        if s.startswith("**Registro:**"):
            continue

        # Detectar encabezados tipo "## 1.", "#### 1.", "**1.", etc.
        m_num = re.match(r"^(?:#{1,5}|\*\*)\s*([1-4])[\.\)\-\s]", s)
        if m_num:
            actual = m_num.group(1)
            continue

        # Fallback por palabras clave en encabezados sin número
        if s.startswith("#"):
            low = s.lower()
            if any(w in low for w in ("parámetro", "parametro", "hallazgo", "resumen", "síntesis")):
                actual = "1"
                continue
            if any(w in low for w in ("clasificaci", "figo", "semáforo", "semaforo", "categor")):
                actual = "2"
                continue
            if any(w in low for w in ("fisiopatol", "hipoxia", "mecanismo", "razonamiento")):
                actual = "3"
                continue
            if any(w in low for w in ("conducta", "manejo", "recomendaci", "sugerid", "acci")):
                actual = "4"
                continue

        if actual in secciones:
            secciones[actual].append(linea)
        else:
            secciones["1"].append(linea)

    resultado = {}
    for k, _ in DIMENSIONES_COMPARACION:
        bloque = "\n".join(secciones[k]).strip()
        resultado[k] = bloque if bloque else "*Consolidado en las secciones anteriores.*"
    return resultado


def generar_sintesis_concordancia(
    features: dict,
    informe_plantilla: str,
    informe_llm: str | None = None,
) -> dict:
    """Compara el Informe Determinístico por Plantilla con el Informe IA (LLM) y
    devuelve un dict con `estado` ('alta' | 'parcial' | 'pendiente'), `titulo` y
    `puntos` (lista de conclusiones comparativas para mostrar en UI y PDF)."""
    import re

    cat_figo = features["figo"]["categoria"]
    desc_figo = features["figo"]["descripcion"]
    var_cat = features["variabilidad"]["categoria"]
    n_decel = len(features["desaceleraciones"])

    if not informe_llm or not informe_llm.strip():
        return {
            "estado": "pendiente",
            "titulo": f"Informe Determinístico listo (Categoría FIGO {cat_figo} — {desc_figo}) · Contraste IA pendiente",
            "puntos": [
                f"**Reglas determinísticas (Plantilla):** clasifican el trazado en **Categoría FIGO {cat_figo} ({desc_figo})** con línea base {features['linea_base']:.0f} lpm, variabilidad {var_cat} y {n_decel} desaceleración(es).",
                "**Contraste con IA (LLM):** aún no se ha ejecutado o está en espera de conexión; el reporte puede emitirse con la plantilla protocolizada o actualizarse con IA.",
            ],
        }

    texto_llm_low = informe_llm.lower()
    cat_low = cat_figo.lower()
    # Buscar mención explícita de la categoría FIGO en el texto del LLM
    mencion_cat_exacta = bool(
        re.search(rf"categor[íi]a\s*(?:figo\s*)?{cat_low}\b", texto_llm_low)
        or re.search(rf"figo\s*{cat_low}\b", texto_llm_low)
    )
    if cat_figo == "I":
        mencion_cat_exacta = mencion_cat_exacta or (
            bool(re.search(r"\bnormal\b", texto_llm_low))
            and not bool(re.search(r"\bpatol[óo]gic", texto_llm_low))
        )
    elif cat_figo == "II":
        mencion_cat_exacta = mencion_cat_exacta or bool(
            re.search(r"\b(sospechos|indeterminad)", texto_llm_low)
        )
    elif cat_figo == "III":
        mencion_cat_exacta = mencion_cat_exacta or bool(
            re.search(r"\bpatol[óo]gic", texto_llm_low)
        )

    sec_llm = extraer_secciones_informe(informe_llm)
    cuatro_secciones_completas = all(
        "Consolidado en las secciones" not in sec_llm[k] and "Sin contenido" not in sec_llm[k]
        for k in ("1", "2", "3", "4")
    )

    puntos = [
        (
            f"**Clasificación normativa:** ambos informes **convergen en Categoría FIGO {cat_figo} ({desc_figo})** "
            f"sobre los mismos parámetros cuantificados (FCF basal {features['linea_base']:.0f} lpm, variabilidad {var_cat})."
            if mencion_cat_exacta
            else f"**Clasificación normativa:** la plantilla determinística fija **Categoría FIGO {cat_figo} ({desc_figo})**; "
                 f"revisar el matiz interpretativo del modelo IA en la dimensión 2."
        ),
        (
            "**Aporte diferencial de cada informe:** la **Plantilla (Columna A)** asegura el checklist normativo estricto "
            "FIGO 2015 / NICE NG229 sin omisiones, mientras que el **Informe IA (Columna B)** integra la narrativa "
            "fisiopatológica sobre los eventos detectados."
        ),
    ]
    if cuatro_secciones_completas:
        puntos.append(
            "**Estructura comparativa:** los 4 bloques clínicos (Parámetros, Clasificación, Fisiopatología y Conducta) "
            "quedaron homologados y alineados fila por fila."
        )

    return {
        "estado": "alta" if mencion_cat_exacta else "parcial",
        "titulo": (
            f"Concordancia Alta entre Plantilla Determinística e IA — Categoría FIGO {cat_figo} ({desc_figo})"
            if mencion_cat_exacta
            else f"Comparación generada — Revisar matices entre Plantilla (FIGO {cat_figo}) e IA"
        ),
        "puntos": puntos,
    }



