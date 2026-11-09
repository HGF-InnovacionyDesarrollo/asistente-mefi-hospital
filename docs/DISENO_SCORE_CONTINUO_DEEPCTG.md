# Diseño de Score Continuo de Riesgo Hipóxico (Marco de 5 Niveles / Tipo DeepCTG) — Fase D1

**Proyecto:** Asesor Clínico MEFI v2.0 — Hospital Dr. Gustavo Fricke  
**Fecha:** 09 de noviembre de 2026  
**Estado:** Documento de diseño y prototipo experimental sobre CTU-UHB (`scripts/pipeline/prototipo_score_continuo_ctu_uhb.py`) — **Sin compromiso de producto clínico hasta validación prospectiva local**.

---

## 1. Motivación y Problema Clínico

Las clasificaciones por reglas de tres niveles (FIGO 2015, NICE NG229, NICHD/ACOG CPG No. 10) están diseñadas como herramientas de **alta sensibilidad** ($\ge 95\,\%$) y **alto valor predictivo negativo** ($\text{VPN} \ge 96,6\,\%$), pero agrupan más del $75\text{–}80\,\%$ de los trazados intraparto en una **Categoría II heterogénea** con especificidad cercana al $11\,\%$.

En la validación de este proyecto sobre los **552 registros de CTU-UHB** ([`docs/VALIDACION_CTU_UHB.md`](VALIDACION_CTU_UHB.md) y [`docs/ESTADO_DELARTE_2026.md`](ESTADO_DELARTE_2026.md)):
- El clasificador determinístico por categorías alcanza **Sensibilidad 95,0 %** y **VPN 96,6 %**.
- Sin embargo, la variable continua con mayor poder discriminativo individual frente a acidemia neonatal ($\text{pH} < 7,05$) es el **área acumulada bajo las desaceleraciones (`area_desaceleraciones_lpm_s`)**, con **$\text{AUROC} = 0,710$**, acercándose al techo de la literatura internacional publicada sobre CTU-UHB ($\text{AUROC } 0,68\text{–}0,75$, ej. *DeepCTG®*).

---

## 2. Arquitectura del Score Continuo Propuesto (`0–100`)

El prototipo combina **features fisiológicas interpretables** ya extraídas de forma determinística por [`src/clinical.py`](../src/clinical.py) en un modelo logístico regularizado (transparente y auditable, sin cajas negras opacas):

### 2.1. Variables de Entrada (Vector $\mathbf{x}$)
1. **`log1p_area_decels`:** $\ln(1 + \text{área acumulada de desaceleraciones en lpm}\cdot\text{s})$ — captura la carga hipóxica total acumulada.
2. **`n_decels_tv`:** número de desaceleraciones tardías, variables o indeterminadas en el segmento.
3. **`variabilidad_reducida_flag`:** indicador de variabilidad $< 5\text{ lpm}$ (o ausente $< 1\text{ lpm}$).
4. **`desviacion_basal_lpm`:** $\max(0, \text{basal} - 155) + \max(0, 110 - \text{basal})$ — penaliza taquicardia y bradicardia.
5. **`sin_aceleraciones_flag`:** ausencia de reactividad ($0$ aceleraciones en el segmento).
6. **`criterios_60_eventos`:** conteo de desaceleraciones variables con $\ge 2$ criterios «60» del Protocolo V2.

### 2.2. Mapeo a Marco de 5 Niveles (Inspirado en Parer & Ikeda / Marco de 5 Colores)

| Nivel | Rango de Score (`0–100`) | Color Sugerido | Correlación con Categorías Actuales | Conducta Orientativa (Investigación) |
|---|---|---|---|---|
| **Nivel 1 — Verde** | `0 – 19` | 🟢 Verde | Categoría I / Categoría II con rasgos protectores | Vigilancia habitual |
| **Nivel 2 — Azul** | `20 – 39` | 🔵 Azul | Categoría II de bajo riesgo | Observación activa y corrección de factores reversibles |
| **Nivel 3 — Amarillo** | `40 – 59` | 🟡 Amarillo | Categoría II de riesgo intermedio | Reanimación intrauterina y reevaluación en 30 min |
| **Nivel 4 — Naranja** | `60 – 79` | 🟠 Naranja | Categoría II con rasgos de alto riesgo (Box 3 ACOG) / Hipoxia progresiva o subaguda | Evaluación médica presencial inmediata y preparación obstétrica |
| **Nivel 5 — Rojo** | `80 – 100` | 🔴 Rojo | Categoría III / Hipoxia aguda | Reanimación urgente y parto expedito ($\le 10\text{ min}$) |

---

## 3. Regla de Seguridad de Integración Futura

1. **Nunca reemplazar el piso de sensibilidad:** cualquier integración futura en la UI debe mostrarse como un **índice continuo complementario dentro de la Categoría II**, sin degradar un trazado Categoría III ni bajar la sensibilidad global por debajo de $95,0\,\%$.
2. **Validación cruzada estratificada:** el script [`scripts/pipeline/prototipo_score_continuo_ctu_uhb.py`](../scripts/pipeline/prototipo_score_continuo_ctu_uhb.py) evalúa el score sobre los 552 registros de CTU-UHB mediante validación cruzada estratificada ($5$-fold CV) midiendo $\text{AUROC}$, sensibilidad al punto de corte de no inferioridad y especificidad ganada.

