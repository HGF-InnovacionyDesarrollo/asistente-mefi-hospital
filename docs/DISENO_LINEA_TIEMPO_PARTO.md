# Diseño de Línea de Tiempo de Evaluaciones Intraparto — Fase D2

**Proyecto:** Asesor Clínico MEFI v2.0 — Hospital Dr. Gustavo Fricke  
**Fecha:** 09 de noviembre de 2026  
**Estado:** Documento de diseño arquitectónico (Prioridad P3 — sin compromiso de producto en el MVP actual).

---

## 1. Propósito Clínico (Flujo Longitudinal del Protocolo V2 y ACOG CPG No. 10)

Tanto el **Protocolo de Vigilancia del Bienestar Fetal Intraparto V2 (septiembre 2025)** como la guía **ACOG CPG No. 10 (2025)** enfatizan que la interpretación cardiotocográfica **no es estática**, sino que exige evaluar la **trayectoria longitudinal del feto** a lo largo del trabajo de parto:
- Detectar cambios inexplicados de la línea base (p. ej. paso gradual de $130\text{ lpm}$ a taquicardia $> 160\text{ lpm}$, rasgo de alto riesgo del Box 3 ACOG).
- Evaluar la respuesta fetal tras maniobras de reanimación intrauterina en la ventana de **30 a 60 minutos** (Categoría II) o de **10 minutos** (Categoría III).
- Identificar secuencias de **hipoxia progresiva** (pérdida de aceleraciones $\rightarrow$ desaceleraciones más anchas y profundas $\rightarrow$ ascenso de la línea base $\rightarrow$ caída de la variabilidad).

---

## 2. Modelo de Datos Propuesto (Sin PHI)

Cada evaluación sucesiva de un mismo episodio de parto se asocia a un identificador pseudonimizado de sesión (`id_episodio_anon`, nunca RUT ni nombre) y almacena únicamente el resumen estructurado de métricas determinísticas:

```json
{
  "id_episodio_anon": "ep-20261109-a8f3",
  "evaluaciones": [
    {
      "orden": 1,
      "timestamp_trazado": "2026-11-09T08:30:00",
      "etapa_parto": "Trabajo de parto fase activa",
      "uso_oxitocina": "En conducción con oxitocina",
      "meconio": "No (líquido claro)",
      "linea_base_lpm": 135.0,
      "variabilidad_lpm": 12.4,
      "categoria_nichd": "moderada",
      "num_aceleraciones": 3,
      "num_desaceleraciones": 1,
      "area_desaceleraciones_lpm_s": 420,
      "tachisistolia": false,
      "categoria_figo": "I",
      "categoria_acog_estricta": "I",
      "riesgo_cat_ii": "con rasgos protectores",
      "hipoxia_tipificada": "Sin signos de hipoxia evolutiva",
      "maniobras_registradas": []
    }
  ]
}
```

---

## 3. Reglas Determinísticas de Tendencia Entre Evaluaciones ($t_{k-1} \rightarrow t_k$)

1. **Delta de Línea Base ($\Delta \text{FCF}_{\text{basal}}$):**
   - Si $\text{basal}(t_k) - \text{basal}(t_{k-1}) \ge +15\text{ lpm}$ o cruza de rango normal ($110\text{–}160\text{ lpm}$) a taquicardia ($> 160\text{ lpm}$): activar automáticamente el rasgo de alto riesgo del Box 3 ACOG (*«cambio inexplicado de la línea base de normal a taquicardia»*).
2. **Deterioro de Variabilidad ($\Delta \text{Var}$):**
   - Si pasa de `moderada` ($6\text{–}25\text{ lpm}$) a `minima` ($\le 5\text{ lpm}$) o `ausente` ($< 1\text{ lpm}$) en dos evaluaciones consecutivas ($\ge 30\text{–}60\text{ min}$): marcar *«variabilidad mínima prolongada sin explicación»* (Box 3 ACOG) y evaluar secuencia de **Hipoxia Progresiva**.
3. **Reloj de Reevaluación Protocolo V2:**
   - Cuando una evaluación $t_{k-1}$ resulta en **Categoría II**, mostrar el tiempo transcurrido frente a la ventana institucional de **30 a 60 minutos** y verificar si el trazado revirtió a Categoría I o persiste pese a maniobras de reanimación intrauterina.

---

## 4. Diseño Visual en Interfaz (`src/app.py`) y Reporte PDF Consolidado

- **Vista en UI:** cinta horizontal compacta encima del Paso 3 mostrando los hitos `[#1 08:30 · Cat I 🟢] ──► [#2 09:15 · Cat II (Intermedio) 🟡] ──► [#3 10:00 · Cat II (Alto) 🔴]` junto con un gráfico de tendencia de 3 líneas (FCF basal, amplitud de variabilidad y área de desaceleraciones).
- **Persistencia segura:** almacenamiento local efímero en `st.session_state["linea_tiempo_parto"]` exportable e importable como archivo `.json` anonimizado o integrado en una tabla resumen al inicio del **Reporte Consolidado en PDF**.

