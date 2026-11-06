"""Prompt clínico versionado aparte de la UI (Fase 3 del plan) — importa que en
un contexto clínico se pueda saber exactamente qué prompt generó qué informe.

Desde esta fase el LLM ya NO recibe la imagen del trazado: razona en texto sobre
el dict de `clinical.py` (`extraer_features()`), anclado a los mismos umbrales
FIGO 2015 / NICE NG229 que usó el código determinístico para clasificar — se
importan directo de `clinical` para que nunca queden desincronizados.
"""

from __future__ import annotations

import clinical

VERSION_PROMPT = "v1-fase3-2026-08-13"

SYSTEM_INSTRUCTIONS = f"""# SYSTEM INSTRUCTIONS: Asesor Clínico MEFI - Hospital Dr. Gustavo Fricke ({VERSION_PROMPT})

## 1. IDENTIDAD Y ROL
**Rol:** Eres un Asistente Clínico Experto en Medicina Materno-Fetal.
**Misión:** Interpretar variables cardiotocográficas (MEFI) ya digitalizadas y
clasificadas de forma determinística, y proponer razonamiento clínico y conducta
sugerida basada en el Protocolo Institucional.

## 2. QUÉ RECIBES Y QUÉ NO
No ves la imagen del trazado. Recibes las variables FCF/UA ya extraídas por
visión clásica (no un LLM) y ya clasificadas según los umbrales FIGO 2015 /
NICE NG229 listados abajo — NO inventes ni corrijas esas cifras, tu trabajo es
interpretarlas clínicamente, no releerlas.

## 3. UMBRALES DE REFERENCIA (FIGO 2015 / NICE NG229) — usados para la clasificación que recibís
- Línea base normal: {clinical.BASAL_MIN_NORMAL}-{clinical.BASAL_MAX_NORMAL} lpm.
- Variabilidad (banda de amplitud pico-a-pico por minuto): reducida <{clinical.VARIABILIDAD_REDUCIDA_MAX} lpm,
  normal {clinical.VARIABILIDAD_REDUCIDA_MAX}-{clinical.VARIABILIDAD_NORMAL_MAX} lpm, aumentada >{clinical.VARIABILIDAD_NORMAL_MAX} lpm.
- Aceleración/desaceleración: >={clinical.UMBRAL_ACEL_DECEL} lpm respecto de la línea base,
  sostenido >={clinical.DURACION_MIN_EVENTO_S}s.
- Desaceleración "muy prolongada" (criterio patológico directo): >={clinical.DESACEL_MUY_PROLONGADA_S // 60} min.
- Patrón sinusoidal: oscilación regular {clinical.SINUSOIDAL_FRECUENCIA_MIN_CPM}-{clinical.SINUSOIDAL_FRECUENCIA_MAX_CPM}
  ciclos/min, amplitud {clinical.SINUSOIDAL_AMPLITUD_MIN}-{clinical.SINUSOIDAL_AMPLITUD_MAX} lpm.
- Contracciones (NICE NG229): <5 en 10 min es blanco; 5 o más en 10 minutos (con menor
  tiempo de reposo) es ámbar y por sí solo descalifica de Categoría I.
- Categorías FIGO 2015: I (Normal) / II (Sospechoso) / III (Patológico).

## 4. ESTRUCTURA Y RAZONAMIENTO ESPERADO (OBLIGATORIO PARA COMPARACIÓN)
Debes organizar tu respuesta en **exactamente estas 4 secciones numeradas** con encabezados `####`, para que el clínico pueda compararlas fila por fila contra el informe determinístico por plantilla:

#### 1. Parámetros Cardiotocográficos Extraídos
Sintetiza el hallazgo principal en 1-2 frases concisas integrando línea base, variabilidad, aceleraciones, desaceleraciones (y su área acumulada) y actividad uterina.

#### 2. Clasificación Normativa (FIGO 2015 / NICE NG229)
Indica la Categoría FIGO (I, II o III) y el semáforo NICE recibidos, contrastando si el conjunto de variables amerita especial vigilancia.

#### 3. Correlación Fisiopatológica (Según Patrón Observado)
Razona sobre la reserva autonómica y el **mecanismo fisiopatológico / tipo de hipoxia** más consistente con el patrón observado (precoz → compresión cefálica vagal; variable → compresión funicular; tardía repetitiva → insuficiencia uteroplacentaria) según el consenso fisiológico 2018/revisión 2024 — sin afirmar un diagnóstico definitivo.

#### 4. Conducta Sugerida según Protocolo
Propone medidas clínicas concretas y escalonadas acordes a la categoría FIGO y al semáforo NICE, cerrando con el disclaimer de que es una herramienta de apoyo que requiere validación humana.

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
        if ctx_partes:
            lineas.extend(["", "## Contexto obstétrico aportado", " · ".join(ctx_partes)])

    lineas.extend([
        "",
        f"## Línea base\n{basal:.0f} lpm.",
        "",
        f"## Variabilidad\n{variabilidad['amplitud_media_lpm']} lpm de amplitud media "
        f"({variabilidad['ventanas_evaluadas']} ventanas de 1 min evaluadas) — categoría: **{variabilidad['categoria']}**.",
        "",
        f"## Aceleraciones\n{len(aceleraciones)} detectada(s).",
    ])
    for a in aceleraciones[:10]:
        lineas.append(f"- {a['inicio_s']:.0f}s-{a['fin_s']:.0f}s, +{a['amplitud_max_lpm']:.0f} lpm.")

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
        sufijo = f" [{', '.join(marcas)}]" if marcas else ""
        lineas.append(
            f"- tipo **{d.get('tipo', 'sin clasificar')}**, {d['inicio_s']:.0f}s-{d['fin_s']:.0f}s "
            f"({d['duracion_s']:.0f}s), -{d['amplitud_max_lpm']:.0f} lpm{sufijo}."
        )

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
        lineas.append(
            f"## Contracciones uterinas\n{contr['num']} detectada(s) "
            f"({contr.get('por_10min')} por 10 minutos) — "
            + ("**tachisistolia** (criterio ámbar NICE NG229)." if contr.get("tachisistolia") else "frecuencia dentro de rango normal.")
        )
    else:
        lineas.append("## Contracciones uterinas\nSin datos de UA para evaluar frecuencia.")
    lineas.append("")
    lineas.append(
        f"## Clasificación FIGO 2015 (ya calculada determinísticamente)\n"
        f"**Categoría {figo['categoria']} — {figo['descripcion']}**\n"
        f"Razones: {'; '.join(figo['razones'])}\n"
        f"Semáforo NICE: línea base={figo['semaforo_nice']['linea_base']}, "
        f"variabilidad={figo['semaforo_nice']['variabilidad']}, "
        f"desaceleraciones={figo['semaforo_nice']['desaceleraciones']}, "
        f"contracciones={figo['semaforo_nice'].get('contracciones', 'verde')}."
    )

    return "\n".join(lineas)


def generar_informe_plantilla(features: dict, metadatos: dict | None = None) -> str:
    """Genera un informe clínico estructurado 100% determinístico a partir de
    `features` (calculado por `clinical.extraer_features()`) y los protocolos
    FIGO 2015 / NICE NG229, sin requerir conexión a ningún LLM.
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
        resumen_acel = (
            f"{len(aceleraciones)} detectada(s) (reactividad presente, "
            f"amplitud máx. +{amp_max_acel:.0f} lpm sobre la basal)."
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
            partes_prol.append(f"{n_prolongadas} prolongada(s) (≥3 min)")
        if n_muy_prolongadas:
            partes_prol.append(f"{n_muy_prolongadas} muy prolongada(s) (≥5 min)")
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
        tasa_str = f" ({por_10} cada 10 min)" if por_10 is not None else ""
        estado_ua = (
            "**taquisistolia presente** (≥5 en 10 min, criterio ámbar NICE NG229)"
            if contr.get("tachisistolia")
            else "frecuencia normal (<5 en 10 min)"
        )
        resumen_ua = f"{contr['num']} contracción(es) detectada(s){tasa_str} — {estado_ua}."
    else:
        resumen_ua = "Sin señal de actividad uterina (UA) suficiente para cuantificar dinámica."

    # --- Evaluación patrón sinusoidal ---
    if sinusoidal.get("presente"):
        resumen_sin = (
            f"**Presente** ({sinusoidal.get('frecuencia_dominante_cpm')} ciclos/min, "
            f"amplitud {sinusoidal.get('amplitud_lpm')} lpm)."
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
                "- **Desaceleración prolongada (≥3 min):** alerta de reducción aguda del flujo uteroplacentario "
                "o funicular (descartar hipotensión materna, hipertonía uterina, prolapso de cordón o descenso rápido)."
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

    # --- Conducta sugerida según categoría FIGO / NICE ---
    cat_figo = figo["categoria"]
    if cat_figo == "I":
        conducta = [
            "- **Trazado Categoría I (Normal):** alta probabilidad de bienestar fetal y equilibrio ácido-base conservado (VPN >96%).",
            "- Mantener vigilancia obstétrica habitual según etapa del trabajo de parto y protocolo institucional.",
            "- No requiere intervenciones correctivas específicas sobre el monitoreo actual.",
        ]
    elif cat_figo == "II":
        conducta = [
            "- **Trazado Categoría II (Sospechoso / Indeterminado):** requiere evaluación clínica del contexto materno-fetal completo.",
            "- **Medidas correctivas iniciales (reanimación intrauterina conservadora):**",
            "  1. lateralización materna (decúbito lateral izquierdo) para optimizar retorno venoso;",
            "  2. evaluar signos vitales maternos y corregir hipotensión o deshidratación (aporte hídrico EV);",
            "  3. si existe taquisistolia o desaceleraciones repetitivas bajo uso de oxitocina, **reducir o suspender infusión de uterotónicos**.",
            "- Mantener monitoreo continuo y **reevaluar respuesta en 20–30 minutos**; si el trazado no mejora o progresa a Categoría III, solicitar evaluación médica obstétrica para definir conducta.",
        ]
    else:
        conducta = [
            "- **Trazado Categoría III (Patológico):** **alerta de riesgo elevado de hipoxia/acidemia fetal.** Requiere evaluación médica obstétrica inmediata.",
            "- **Medidas de reanimación intrauterina urgentes:**",
            "  1. posición materna en decúbito lateral y corrección inmediata de hipotensión;",
            "  2. **suspensión inmediata de oxitocina** u otros uterotónicos (considerar tocolisis aguda si hay hipertonía/taquisistolia);",
            "  3. realizar examen obstétrico para descartar causas agudas (prolapso de cordón, desprendimiento placentario, descenso rápido).",
            "- Si el patrón patológico no revierte rápidamente tras las medidas iniciales, **preparar para interrupción expedita del embarazo** (parto instrumental o cesárea de urgencia según condiciones obstétricas).",
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
        sufijo_ctx = (" · " + " · ".join(extra_ctx)) if extra_ctx else ""
        lineas.append(
            f"**Registro:** `{id_reg}` · **Fecha/hora inicio:** `{fecha_reg}` · **Velocidad papel:** `{vel_reg} cm/min`{sufijo_ctx}"
        )
        lineas.append("")

    lineas.extend([
        "#### 1. Parámetros Cardiotocográficos Extraídos",
        f"- **Línea base FCF:** **{basal:.0f} lpm** — {estado_basal}.",
        f"- **Variabilidad:** **{variabilidad['amplitud_media_lpm']} lpm** (categoría **{variabilidad['categoria']}**, evaluada en {variabilidad['ventanas_evaluadas']} ventanas de 1 min).",
        f"- **Aceleraciones:** {resumen_acel}",
        f"- **Desaceleraciones:** {resumen_decel}",
        f"- **Actividad uterina (UA):** {resumen_ua}",
        f"- **Patrón sinusoidal:** {resumen_sin}",
        "",
        "#### 2. Clasificación Normativa (FIGO 2015 / NICE NG229)",
        f"- **Categoría FIGO 2015:** **Categoría {cat_figo} — {figo['descripcion']}**",
        f"- **Criterios determinantes:** {'; '.join(figo['razones'])}",
        "- **Semáforo por variable (NICE NG229):**",
        f"  - Línea base: {icono_color[semaforo['linea_base']]}",
        f"  - Variabilidad: {icono_color[semaforo['variabilidad']]}",
        f"  - Desaceleraciones: {icono_color[semaforo['desaceleraciones']]}",
        f"  - Contracciones: {icono_color[semaforo.get('contracciones', 'verde')]}",
        "",
        "#### 3. Correlación Fisiopatológica (Según Patrón Observado)",
        *puntos_fisio,
        "",
        "#### 4. Conducta Sugerida según Protocolo",
        *conducta,
        "",
        "---",
        "*Nota: Informe generado automáticamente mediante plantilla determinística (reglas FIGO 2015 / NICE NG229). "
        "Esta herramienta es de apoyo a la decisión clínica, no reemplaza el juicio profesional y requiere validación humana "
        "(ref. ensayo INFANT, Lancet 2017).*",
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



