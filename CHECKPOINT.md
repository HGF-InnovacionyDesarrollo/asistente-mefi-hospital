# CHECKPOINT: Asesor Clínico MEFI

**Fecha última actualización:** 16 de octubre de 2026  
**Estado general:** Fases 1-4 completas y verificadas; Fase 5 (disclaimer clínico) visible en UI. Pendiente declarado: empaquetado instalable para otros computadores del hospital.

**Validación actual (CTU-UHB, 552 registros):** sensibilidad 95.0 % / especificidad 11.1 % / PPV 7.7 % / NPV 96.6 % / exactitud balanceada 53.1 %. AUROC área-desaceleraciones 0.710. La especificidad baja es una propiedad conocida del problema, no un bug del implementación (ver [ESTADO_DELARTE_2026.md](ESTADO_DELARTE_2026.md)).

**Nota:** el plan técnico original en `C:\Users\usuariohgf\.claude\plans\composed-sniffing-moler.md` ya no existe; este checkpoint y [CLAUDE.md](CLAUDE.md) son hoy las fuentes de decisión del proyecto.

---

## Historial de decisiones clave

### Calibración semi-automática + lanzador MEFI.bat (15 oct 2026)

- **`MEFI.bat` (raíz):** doble clic → detecta Python, crea `venv` si falta, instala dependencias la primera vez (marcador `venv\.listo`), verifica Tesseract, abre navegador en `:8501` y lanza Streamlit. Probado de punta a punta.
- **`src/digitizer.py::sugerir_puntos_calibracion`:** pre-rellena los dos puntos de calibración por OCR de etiquetas del margen o detección de líneas de grilla. La confirmación humana sigue siendo obligatoria.
- `pytest` 25/25 verde.

### Detector de contracciones v2 + métricas ampliadas (13 oct 2026)

- Reemplazó el detector naive de UA por un pipeline clásico TOCO (pasabajos 0.04 Hz, tono basal móvil, `find_peaks` con umbrales relativos). Mediana 11-17 contracciones/registro (~2/10 min) frente a las 90 imposibles del detector anterior.
- Criterio NICE de tachisistolia (≥5 contracciones/10 min) como 4ª variable del semáforo.
- Área bajo desaceleraciones como severidad cuantitativa en UI y prompt (AUC 0.710).
- Validación batch reporta PPV/NPV/exactitud balanceada y AUROC por feature.

### Robustecimiento CTU-UHB + disclaimer (18 ago 2026)

- Descarga del dataset completo con `scripts/descargar_ctu_uhb.py`.
- Fix del parser de metadata CTU-UHB (espacios múltiples, no `:`).
- Filtrado de dropouts del sensor Doppler (FCF=0 fuera de 50-220 lpm).
- Fix del criterio de Categoría I: ahora exige "sin desaceleraciones repetitivas" (proxy 3+ en 20 min), no cero desaceleraciones.
- Disclaimer clínico agregado en `src/app.py` con referencia al ensayo INFANT.

### Seguridad y redacción de casos (11 ago 2026)

- API key filtrada rotada; historial de git reescrito a commit limpio antes de cualquier push.
- Casos reales redactados a `fixtures/casos_redactados/` con `scripts/redactar_casos.py`.
- `.gitignore` reescrito en UTF-8; carpetas de datos excluidas.

---

## Arquitectura actual

```
[Imagen/PDF/CSV] → src/digitizer.py → DataFrame → src/clinical.py → features FIGO/NICE
                                                            ↓
                                                    src/prompts.py → texto
                                                            ↓
                                              src/llm_client.py + config.yaml → LLM
                                                            ↓
                                                    src/app.py → informe + UI
```

Ningún LLM ve la imagen ni la señal cruda: el LLM solo redacta sobre el dict de features.

---

## Módulos principales

| Archivo | Responsabilidad |
|---|---|
| `src/digitizer.py` | Imagen → serie de tiempo. Orientación, paneles FCF/UA, calibración semi-automática, extracción de curva, OCR local de cabecera/anotaciones. |
| `src/clinical.py` | Reglas FIGO 2015 / NICE NG229. Línea base, variabilidad, aceleraciones, desaceleraciones subclasificadas, patrón sinusoidal, clasificación FIGO + semáforo. |
| `src/prompts.py` | Prompt de sistema (importa umbrales de `clinical.py`) y constructor del prompt de usuario. |
| `src/llm_client.py` + `config.yaml` | Cliente LLM configurable por datos: Ollama / OpenRouter / Hugging Face Router. |
| `src/app.py` | UI Streamlit: uploader, calibración, digitalización, clasificación, generación de informe. |
| `scripts/validar_ctu_uhb.py` | Validación contra CTU-UHB (`--record-id` o `--all`). |
| `scripts/prueba_llm_local.py` | Prueba de humo con Ollama local (qwen3:4b), compara español directo vs. inglés maestro + traducción. |
| `MEFI.bat` | Lanzador de doble clic para usuarios no técnicos. |

---

## Verificación rápida

```powershell
cd "C:\MVP - MEFI"
.\venv\Scripts\Activate.ps1

# Tests
python -m pytest tests/ -q          # 25/25 verde

# Validación CTU-UHB
PYTHONIOENCODING=utf-8 python scripts/validar_ctu_uhb.py --all

# App
PYTHONIOENCODING=utf-8 streamlit run src/app.py
```

---

## Pendientes declarados

1. **Empaquetado instalable** para otros computadores del hospital (PyInstaller/innosetup o similar) — no iniciado.
2. **Gobernanza de datos con OpenRouter/Hugging Face** para uso con datos reales: hasta confirmar, solo Ollama local o fixtures sintéticas.
3. **Score continuo de riesgo** tipo DeepCTG como propuesta futura (requiere validación local).
4. **Canal de frecuencia cardíaca materna** si el hardware lo permite.

---

## Reglas duras

- Nunca commitear `fixtures/`, `data/ctu_uhb/`, `data/raw_scans/`, `data/processed_scans/`, `data/extracted/`, `Casos/`, `src/data/`.
- Nunca poner nombre/RUT/ID real de paciente en nombres de archivo, mensajes de commit ni código.
- Antes de cambiar un umbral clínico: correr `pytest` **y** `scripts/validar_ctu_uhb.py --all`, y reportar sensibilidad/especificidad antes/después.
- No bajar sensibilidad para ganar especificidad con el clasificador por reglas.
