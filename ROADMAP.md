# ROADMAP — Asesor Clínico MEFI

Plan vivo del proyecto. **Ritual:** al cerrar un bloque de trabajo, mover el
estado de la tarea aquí y registrar el qué/cómo/porqué en
[CHECKPOINT.md](CHECKPOINT.md) (que es la bitácora de decisiones).

| Fase | Objetivo | Prioridad | Estado | Criterio de "hecho" |
|---|---|---|---|---|
| **0. Higiene y privacidad** | Reorganización de carpetas, anonimización de escaneos, limpieza de duplicados, ROADMAP de seguimiento | Alta | En curso | `pytest` 25/25 + batch CTU-UHB con métricas idénticas a las de oct-2026 + cero PHI en nombres de archivo del proyecto |
| **1. Empaquetado instalable** | Bundle portable con Python embebido + instalador InnoSetup para otros PCs del hospital | Alta | **En curso** | `MEFI-Setup.exe` compilado y verificado localmente (242 MB, 05-11-2026); falta prueba de punta a punta en un PC limpio del hospital |
| **2. Gobernanza de datos LLM** | Decidir qué proveedor (OpenRouter / Hugging Face / Ollama) puede ver qué datos | Alta | No iniciado | Documento aprobado por el equipo; hasta entonces, datos reales solo con Ollama local |
| **3. Score continuo de riesgo** | Prototipo tipo DeepCTG sobre CTU-UHB (contexto: techo AUC ~0.75 publicado, ver `docs/ESTADO_DELARTE_2026.md`) | Media | Futuro | AUC claramente por encima del clasificador por reglas en validación local justifica integración |
| **4. Canal FCF materna** | Soporte de segundo canal si el hardware del hospital lo permite | Baja | Futuro | Detección validada con hardware real |

## Ideas sueltas (sin compromiso aún)

- Guardar CSV de métricas por corrida de validación en `docs/validaciones/` para
  trazabilidad histórica (hoy vive en el texto del CHECKPOINT).
- Tablero GitHub Projects como espejo de este ROADMAP si el equipo lo necesita
  (el `.md` local sigue siendo la fuente de verdad).
- Reintroducir `data/raw_scans/` + `data/processed_scans/` cuando la Fase 1
  implemente un pipeline de ingesta que los use de verdad.
