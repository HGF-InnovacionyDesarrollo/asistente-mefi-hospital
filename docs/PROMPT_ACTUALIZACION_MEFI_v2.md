# PROMPT DE IMPLEMENTACIÓN — Asesor Clínico MEFI v2.0

**Proyecto:** `C:\MVP - MEFI` — Hospital Dr. Gustavo Fricke, Unidad de Parto Integral (SAIP)
**Fecha:** noviembre de 2026
**Base normativa:** Protocolo de Vigilancia del Bienestar Fetal Intraparto V2 (septiembre 2025) + ACOG Clinical Practice Guideline No. 10, *Intrapartum Fetal Heart Rate Monitoring: Interpretation and Management* (Obstet Gynecol 2025;146:583–599) + FIGO 2015 + NICE NG229.
**Documento madre:** `docs/PROPUESTA_ACTUALIZACION_MEFI_v2.0.docx` (matriz de conciliación y prioridades P1/P2/P3).

> Instrucción de uso: pegar este prompt completo en la herramienta de desarrollo (agente de código). Antes de ejecutar cada fase, la jefatura clínica debe aprobar los cambios de umbral marcados como DECISIÓN.

---

## CONTEXTO OBLIGATORIO

1. Lee primero `CLAUDE.md` y `CHECKPOINT.md`. El historial de decisiones manda; no contradigas una regla dura sin proponer su cambio explícito.
2. Arquitectura: ningún LLM ve la imagen ni la señal cruda. Núcleo determinístico en `src/clinical.py` (funciones puras, sin Streamlit ni LLM). `src/prompts.py` importa los umbrales **desde `clinical`** — nunca duplicar constantes. UI en `src/app.py`, ayudas puras en `src/ux_helpers.py`.
3. Umbrales clínicos viven en `src/clinical.py` con comentario de su fundamento normativo (FIGO 2015 / NICE NG229 / ACOG CPG No. 10 / Protocolo V2). Al agregar o cambiar uno, citar la fuente y la sección en el comentario.

## REGLAS DURAS (NO NEGOCIABLES)

- **Nunca bajar la sensibilidad para ganar especificidad.** Criterio de no inferioridad: sensibilidad ≥ 95,0 % y VPN ≥ 96,6 % tras cualquier cambio de umbral.
- Ante **cualquier cambio de umbral clínico**: correr `python -m pytest tests/ -q` **y** `python scripts/pipeline/validar_ctu_uhb.py --all`, y reportar sensibilidad, especificidad, PPV, NPV y AUROC **antes y después**. Si un cambio cae por debajo del criterio de no inferioridad, revertir ese cambio y dejar el parámetro configurable y documentado (precedente: criterio «>50 % de contracciones», agosto 2026).
- Ningún dato de paciente (PHI) en nombres de archivo, commits ni código. No commitear `casos_hospital/`, `fixtures/`, `data/ctu_uhb/`, `data/extracted/`.
- Con datos reales solo Ollama local o plantilla determinística (gobernanza LLM pendiente).
- Al cerrar cada fase: actualizar `CHECKPOINT.md` (bitácora), `ROADMAP.md` (estado), subir `VERSION_PROMPT` en `src/prompts.py`, y anotar el estado del componente en la propuesta.
- Trabajar con los casos redactados (`fixtures/casos_redactados/`) y el trazado sintético; nunca con los originales.

---

## FASE A — Alineación normativa y de seguridad (P1; SIN cambio de umbrales de clasificación)

### A1. Actualización de la conducta de los informes (`src/prompts.py`: `generar_informe_plantilla` y `SYSTEM_INSTRUCTIONS`)
- **Categoría II:** aviso **inmediato** al médico/a ginecobstetra residente de turno (responsabilidad de la matrón/a según Protocolo V2). Maniobras de reanimación intrauterina: lateralización materna, corrección de hipotensión/hidratación EV, reducción o suspensión de agentes de inducción/aceleración (oxitocina). Agregar: **amnioinfusión** como opción ante desaceleraciones variables recurrentes por compresión de cordón; **corrección de fisiopatología materna** como causa de taquicardia (infección, deshidratación, etc.); **oxígeno suplementario solo si hipoxia materna (SatO2 < 94 %)** — citar recomendación ACOG contra el uso rutinario. Tiempos: si el patrón persiste pese a maniobras, observación de **½ a 1 hora** según Protocolo V2, matizada por los rasgos de riesgo del Box 3 ACOG y explicitando que ACOG individualiza los tiempos según el escenario.
- **Categoría III:** aviso inmediato y reanimación urgente. Agregar matices por subtipo (ACOG): bradicardia con sospecha de rotura uterina → parto lo antes posible; contracción tetánica/taquisistolía → suspender uterotónicos y considerar tocolisis de acción rápida **antes** del parto; sinusoidal > 30 min → sin beneficio intraparto, parto expedito. Conservar el máximo de **10 minutos** de observación del Protocolo V2 si el trazado no revierte.
- **Tocolisis:** si la taquisistolía asociada a categoría II con rasgos de alto riesgo o III persiste pese a pausar la oxitocina, sugerir agente uterorelizante de acción rápida (institucional: nitroglicerina/fenoterol; ACOG cita terbutalina).
- Todo con lenguaje de «conducta sugerida» y cierre con disclaimer (apoyo, no diagnóstico; validación humana obligatoria).

### A2. Subclasificador determinístico de riesgo de Categoría II (Box 3 ACOG)
- Nuevo módulo en `src/clinical.py` (p. ej. `evaluar_riesgo_categoria_ii(features) -> dict`), calculado con variables ya existentes:
  - Rasgos de **alto riesgo**: variabilidad ausente (una vez implementada en Fase B; en Fase A usar «reducida» como aproximación documentada); variabilidad mínima prolongada sin explicación; cambio inexplicado de la línea base de normal a taquicardia; desaceleraciones tardías/variables recurrentes (proxy ≥ 3 en 20 min ya calculado); más de una desaceleración prolongada.
  - Rasgos **protectores**: variabilidad moderada; presencia de aceleraciones.
- Salida: nivel (`alto` / `intermedio` / `con rasgos protectores`) + lista de razones. **No altera `clasificar_figo()`**; se muestra como KPI/tarjeta en `src/app.py` y en ambos informes.

### A3. Alerta de sospecha de FCF materna
- Heurística informativa (en `clinical.py` o `ux_helpers.py`): si se detectan **aceleraciones repetidas coincidentes con picos de contracciones** (patrón descrito por ACOG como indicio de registro de la frecuencia materna), emitir recordatorio de verificar el pulso materno con pulsioxímetro, reforzando el supuesto 5 (segunda fase, obesidad). Solo informativa; nunca bloquea el análisis.

### A4. Refuerzo del disclaimer regulador
- En `src/app.py` y `src/prompts.py`: citar que ACOG CPG No. 10 recomienda **contra depender primariamente de sistemas computarizados** para interpretar y manejar la FCF (fuerte, evidencia moderada) y referenciar el ensayo INFANT (Lancet 2017). Refuerza el posicionamiento del sistema como apoyo con confirmación humana.

### A5. Reporte comparativo «ACOG estricta vs. MEFI»
- Nueva función `clasificar_acog_estricta(features)` en `src/clinical.py`: Categoría III estricta = variabilidad ausente + (desaceleraciones tardías o variables recurrentes, o bradicardia < 110) **o** patrón sinusoidal (definición NICHD/ACOG).
- Mostrar como línea informativa en el informe y en KPIs cuando difiera de la categoría MEFI de alta sensibilidad, con fundamento normativo citado. Transparencia ante auditorías.

**Tests Fase A:** nuevo test por componente en `tests/test_clinical.py` / `tests/test_ux_helpers.py`. Meta: batería completa en verde (32 actuales + nuevos, apuntar a ≥ 40).

---

## FASE B — Definiciones NICHD/ACOG (P1/P2; CAMBIAN UMBRALES → requieren validación completa y aprobación clínica)

> Ejecutar **un cambio a la vez**, con `pytest` + `validar_ctu_uhb.py --all` después de cada uno, y métricas antes/después publicadas en `docs/VALIDACION_CTU_UHB.md`. Cualquiera que baje la sensibilidad bajo el criterio de no inferioridad se revierte y queda configurable.

### B1. Desaceleración prolongada a 2 minutos — DECISIÓN CLÍNICA
`DESACEL_PROLONGADA_MIN_S`: 180 → **120** (ACOG Tabla 1 y Protocolo V2). Conservar `DESACEL_MUY_PROLONGADA_S = 300`. Revisar el uso de `prolongada` en clasificación e informes.

### B2. Patrón sinusoidal a 20 minutos — DECISIÓN CLÍNICA
`SINUSOIDAL_DURACION_MIN_S`: 600 → **1200** (ACOG: ≥ 20 min). Reportar la duración efectiva del patrón y una nota de que el Protocolo V2 exige > 30 min con ausencia de aceleraciones.

### B3. Aceleraciones por edad gestacional
En `detectar_aceleraciones`, aceptar umbrales por parámetro: si `edad_gestacional < 32 semanas` (desde los metadatos ya registrados en la UI), usar **10 lpm / 10 s** (ACOG/Protocolo V2); por defecto 15/15. Etiquetar como **«aceleración prolongada»** las de 2 a 10 minutos (120–600 s). Revalidar (CTU-UHB es a término: el efecto esperado es nulo — verificarlo).

### B4. Taquisistolía por promedio móvil de 30 minutos
`features["contracciones"]`: tachisistolia ACOG = más de 5 contracciones en 10 minutos **promediadas en una ventana de 30 minutos**; conservar la tasa global ≥ 5/10 min como respaldo cuando el registro dure menos de 30 minutos. Actualizar semáforo e informes con ambos criterios visibles.

### B5. Variabilidad en 4 categorías NICHD
`calcular_variabilidad`: distinguir **ausente** (amplitud indetectable, p. ej. amplitud mediana < 1 lpm o ventanas con rango ~0), **mínima** (≤ 5 lpm), **moderada** (6–25) y **marcada** (> 25). Mantener nombres retrocompatibles hacia `prompts.py` y la clasificación (ausente/mínima se tratan como «reducida» para la clasificación FIGO hasta decisión clínica; la categoría III ACOG estricta usará «ausente»).

### B6. Variabilidad intra-desaceleración
Para cada desaceleración ≥ 2 minutos: medir la amplitud pico a pico dentro del evento y marcar `variabilidad_reducida_intra_evento` si < 5 lpm. Alimenta criterios «60», tipificación de hipoxia y la definición de sinusoidal del Protocolo V2.

---

## FASE C — Módulos informativos del Protocolo V2 (P2)

### C1. Criterios «60» (marcador de riesgo independiente)
Para desaceleraciones **variables**: evaluar duración > 60 s, frecuencia en el nadir < 60 lpm y caída > 60 lpm. Si se cumplen **≥ 2 criterios durante más de 30 minutos**, activar marcador de riesgo visible en la tabla clínica de desaceleraciones y en los informes. No cambia la categoría FIGO por sí solo.

### C2. Tipificación determinística de la hipoxia (informativa)
Nuevo módulo que propone el tipo de hipoxia según el Protocolo V2, sin alterar la categoría:
- **Aguda:** desaceleración aguda > 5 min, o > 3 min con variabilidad reducida intra-evento.
- **Subaguda:** el feto pasa más tiempo desacelerando que en línea basal (tiempo bajo la línea base > tiempo en basal).
- **Progresiva:** secuencia observable (pérdida de aceleraciones → desaceleraciones más anchas/profundas → ascenso de la línea base → caída de la variabilidad → descenso escalonado terminal).
- **Crónica:** línea base en límite alto + variabilidad reducida + ausencia de aceleraciones.
Se presenta como razonamiento determinístico en la sección 3 de los informes (complementa, no reemplaza, al Informe IA).

### C3. Contexto clínico estructurado (`src/app.py` + metadatos)
Agregar campos opcionales: **meconio** (sí/no), **patología antenatal** (texto breve) y nota de **comparación con MEFI previos** (recordatorio de revisar registros anteriores del mismo caso, según el flujo de interpretación del Protocolo V2). Integrar al prompt de usuario, a la plantilla y al PDF consolidado.

### C4. Actualización de la UI
Tabla clínica de desaceleraciones y tarjetas KPI: incorporar criterios «60», variabilidad intra-evento, nivel de riesgo de categoría II (A2) y lectura ACOG estricta (A5).

---

## FASE D — Línea de investigación (P3; sin compromiso de producto)

- **D1.** Diseño de score continuo de riesgo (marco de cinco niveles / DeepCTG, ROADMAP Fase 3): solo documento de diseño y prototipo sobre CTU-UHB.
- **D2.** Diseño de línea de tiempo de evaluaciones del parto (registro sucesivo de valoraciones): solo documento de diseño.

---

## CRITERIOS DE ACEPTACIÓN (versión final v2.0)

1. Batería de pruebas unitarias en verde (≥ 40 tests).
2. Validación CTU-UHB sin inferioridad tras Fase B: sensibilidad ≥ 95,0 % y VPN ≥ 96,6 %; métricas antes/después en `docs/VALIDACION_CTU_UHB.md`.
3. Matriz de conciliación del Manual del Proyecto (capítulo 7) actualizada: cada elemento del Protocolo V2 y de ACOG CPG No. 10 con estado cubierto/parcial/fuera de alcance y su fundamento.
4. Redacción de conducta aprobada por la jefatura clínica.
5. `CHECKPOINT.md`, `ROADMAP.md`, `VERSION_PROMPT` y propuesta actualizados con el estado por componente.
