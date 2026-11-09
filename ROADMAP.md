# ROADMAP — Asesor Clínico MEFI

Plan vivo del proyecto. **Ritual:** al cerrar un bloque de trabajo, mover el
estado de la tarea aquí y registrar el qué/cómo/porqué en
[CHECKPOINT.md](CHECKPOINT.md) (que es la bitácora de decisiones).

| Fase | Objetivo | Prioridad | Estado | Criterio de "hecho" |
|---|---|---|---|---|
| **0. Higiene y privacidad** | Reorganización de carpetas, anonimización de escaneos, limpieza de duplicados, ROADMAP de seguimiento | Alta | Completado | `pytest` 25/25 + batch CTU-UHB con métricas idénticas a las de oct-2026 + cero PHI en nombres de archivo del proyecto |
| **1. Empaquetado instalable** | Bundle portable con Python embebido + instalador InnoSetup para otros PCs del hospital | Alta | Completado | `MEFI-Setup.exe` compilado (242 MB, 05-11-2026) y probado de punta a punta en otro PC (06-11-2026) |
| **1.1 / 1.2. Usabilidad en terreno, seguridad UX y PDF consolidado** | Calibrador arrastrable con mouse (`src/componente_calibrador/`), píldoras de escala en 1 clic con validador anti-error (`src/ux_helpers.py`), barra de progreso y auto-colapsado, modo práctica con trazado sintético, tabla clínica de desaceleraciones, comparación Plantilla vs. IA y Reporte PDF Consolidado (`src/reporte_pdf.py`) | Alta | Completado | `pytest` 32/32 en verde + bundle `dist/MEFI-portable` actualizado |
| **v2.0 — Fase A. Alineación normativa y de seguridad (P1, sin cambio de umbrales)** | A1: Conducta Protocolo V2 + ACOG CPG No. 10 (`src/prompts.py`); A2: Subclasificador riesgo Cat II Box 3 ACOG; A3: Alerta sospecha FCF materna; A4: Disclaimer ACOG CPG No. 10 + INFANT; A5: Comparativo ACOG estricta vs. MEFI | Alta (P1) | Completado | `pytest` en verde; sin cambio de umbrales de clasificación |
| **v2.0 — Fase B. Definiciones NICHD/ACOG (P1/P2, cambian umbrales — aprobado y validado)** | B1: Desaceleración prolongada 180→120s; B2: Sinusoidal 600→1200s; B3: Aceleraciones por EG (<32 sem: 10/10) y prolongada (2–10 min); B4: Taquisistolía ventana móvil 30 min + respaldo global; B5: Variabilidad 4 categorías NICHD; B6: Variabilidad intra-desaceleración | Alta (P1/P2) | Completado | Ejecutado un cambio a la vez con `pytest` + `validar_ctu_uhb.py --all`: sensibilidad **95.0 %** y VPN **96.6 %** publicados en `docs/VALIDACION_CTU_UHB.md` |
| **v2.0 — Fase C. Módulos informativos Protocolo V2 (P2)** | C1: Criterios «60» en desaceleraciones variables; C2: Tipificación determinística de hipoxia (aguda/subaguda/progresiva/crónica); C3: Contexto clínico estructurado (meconio, patología antenatal, MEFI previos); C4: Actualización de UI | Media-Alta (P2) | Completado | `pytest` 50/50 en verde + integración en informes, UI y PDF consolidado |
| **v2.0 — Fase D. Línea de investigación (P3)** | D1: Diseño de score continuo de riesgo (`docs/DISENO_SCORE_CONTINUO_DEEPCTG.md` + prototipo en CTU-UHB); D2: Diseño de línea de tiempo de evaluaciones del parto (`docs/DISENO_LINEA_TIEMPO_PARTO.md`) | Media (P3) | Completado (Diseño + Prototipo) | Documentos de diseño + prototipo en `scripts/pipeline/prototipo_score_continuo_ctu_uhb.py` + Matriz de conciliación en `docs/MATRIZ_CONCILIACION_MEFI_v2.0.md` |
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
