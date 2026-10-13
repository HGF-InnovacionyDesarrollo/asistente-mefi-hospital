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

## 4. RAZONAMIENTO ESPERADO
1. Resume el hallazgo principal en una frase.
2. Si hay desaceleraciones, razona sobre el **tipo de hipoxia** más consistente
   con el patrón observado (precoz → compresión de cabeza fetal, benigno;
   variable → compresión de cordón; tardía repetitiva → insuficiencia
   uteroplacentaria) según el consenso fisiológico 2018/revisión 2024 — sin
   afirmar un diagnóstico definitivo, solo el razonamiento fisiopatológico.
3. Contrasta la categoría FIGO recibida contra el cuadro clínico completo y
   propone conducta sugerida acorde al semáforo NICE.
4. Cierra siempre con el disclaimer: esta es una herramienta de apoyo a la
   decisión, no reemplaza el juicio clínico y requiere validación humana.

Responde en Markdown, en español, con estructura clara (encabezados cortos).
No inventes valores numéricos que no estén en los datos recibidos.
"""


def construir_prompt_usuario(features: dict) -> str:
    """Renderiza el dict de `clinical.extraer_features()` como texto estructurado
    para el LLM — nunca se manda la imagen."""
    basal = features["linea_base"]
    variabilidad = features["variabilidad"]
    aceleraciones = features["aceleraciones"]
    desaceleraciones = features["desaceleraciones"]
    sinusoidal = features["patron_sinusoidal"]
    figo = features["figo"]

    lineas = [
        "Interpreta el siguiente registro CTG ya digitalizado y clasificado. "
        "Las cifras no fueron leídas por ti ni por ningún modelo de visión.",
        "",
        f"## Línea base\n{basal:.0f} lpm.",
        "",
        f"## Variabilidad\n{variabilidad['amplitud_media_lpm']} lpm de amplitud media "
        f"({variabilidad['ventanas_evaluadas']} ventanas de 1 min evaluadas) — categoría: **{variabilidad['categoria']}**.",
        "",
        f"## Aceleraciones\n{len(aceleraciones)} detectada(s).",
    ]
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
