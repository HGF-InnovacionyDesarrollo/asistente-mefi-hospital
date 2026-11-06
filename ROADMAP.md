# ROADMAP — Asesor Clínico MEFI

Plan vivo del proyecto. **Ritual:** al cerrar un bloque de trabajo, mover el
estado de la tarea aquí y registrar el qué/cómo/porqué en
[CHECKPOINT.md](CHECKPOINT.md) (que es la bitácora de decisiones).

| Fase | Objetivo | Prioridad | Estado | Criterio de "hecho" |
|---|---|---|---|---|
| **0. Higiene y privacidad** | Reorganización de carpetas, anonimización de escaneos, limpieza de duplicados, ROADMAP de seguimiento | Alta | Completado | `pytest` 25/25 + batch CTU-UHB con métricas idénticas a las de oct-2026 + cero PHI en nombres de archivo del proyecto |
| **1. Empaquetado instalable** | Bundle portable con Python embebido + instalador InnoSetup para otros PCs del hospital | Alta | Completado | `MEFI-Setup.exe` compilado (242 MB, 05-11-2026) y probado de punta a punta en otro PC (06-11-2026) |
| **1.1. Usabilidad de calibración, comparación ordenada e informe PDF consolidado** | (a) Guía paso a paso, trazado visual de las 2 líneas de calibración y barras deslizantes para arrastrar cada línea verticalmente (con fix `on_click` de `session_state`); (b) Vista ancha con tarjetas ejecutivas de KPIs y comparación fila por fila de las 4 dimensiones clínicas (Plantilla vs. IA); (c) Exportación de Reporte Consolidado en `.pdf` (`src/reporte_pdf.py`) + API key preconfigurada en el instalador | Alta | Completado | `pytest` 28/28 en verde; usuario puede arrastrar las líneas 1 y 2 verticalmente, comparar ambos informes dimensión por dimensión y descargar el PDF consolidado A4 |
| **2. Gobernanza de datos LLM** | Decidir qué proveedor (OpenRouter / Hugging Face / Ollama) puede ver qué datos | Alta | En revisión | Propuesta formal redactada en `docs/GOBERNANZA_DATOS_LLM.md`; pendiente validación final del equipo (datos reales en producción con Ollama local o plantilla determinística) |
| **3. Score continuo de riesgo** | Prototipo tipo DeepCTG sobre CTU-UHB (contexto: techo AUC ~0.75 publicado, ver `docs/ESTADO_DELARTE_2026.md`) | Media | Futuro | AUC claramente por encima del clasificador por reglas en validación local justifica integración |
| **4. Canal FCF materna** | Soporte de segundo canal si el hardware del hospital lo permite | Baja | Futuro | Detección validada con hardware real |

## Ideas sueltas (sin compromiso aún)

- Guardar CSV de métricas por corrida de validación en `docs/validaciones/` para
  trazabilidad histórica (hoy vive en el texto del CHECKPOINT).
- Tablero GitHub Projects como espejo de este ROADMAP si el equipo lo necesita
  (el `.md` local sigue siendo la fuente de verdad).
- Reintroducir `data/raw_scans/` + `data/processed_scans/` cuando la Fase 1
  implemente un pipeline de ingesta que los use de verdad.
