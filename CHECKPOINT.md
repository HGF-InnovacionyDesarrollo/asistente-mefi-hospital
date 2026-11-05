# CHECKPOINT: Asesor Clínico MEFI

**Fecha última actualización:** 5 de noviembre de 2026
**Estado general:** Fases 1-4 completas y verificadas; Fase 5 (disclaimer clínico) visible en UI. Fase 0 del ROADMAP (reorganización, higiene y privacidad) completada este día. Próxima fase planeada: empaquetado instalable (ver [ROADMAP.md](ROADMAP.md)).

**Validación actual (CTU-UHB, 552 registros):** sensibilidad 95.0 % / especificidad 11.1 % / PPV 7.7 % / NPV 96.6 % / exactitud balanceada 53.1 %. AUROC área-desaceleraciones 0.710. La especificidad baja es una propiedad conocida del problema, no un bug del implementación (ver [docs/ESTADO_DELARTE_2026.md](docs/ESTADO_DELARTE_2026.md)).

**Nota:** el plan técnico original en `C:\Users\usuariohgf\.claude\plans\composed-sniffing-moler.md` ya no existe; este checkpoint y [CLAUDE.md](CLAUDE.md) son hoy las fuentes de decisión del proyecto.

---

## Historial de decisiones clave

### Reorganización Fase 0 — higiene, privacidad y base de casos (05 nov 2026)

- **Estructura:** `scripts/` dividido en `pipeline/` + `analisis/` + `utilidades/` con `scripts/README.md`; documentos movidos a `docs/` (`ESTADO_DELARTE_2026.md`, `VALIDACION_CTU_UHB.md`, `VALIDAR_CTU_UHB_QUICK_START.md`; figuras a `docs/figs/`); creado `ROADMAP.md` (plan vivo — los pendientes de este archivo migraron ahí).
- **Anonimización de escaneos:** `Casos/` eliminada; sus 81 archivos renombrados al estándar anónimo en `casos_hospital/` (`escaneos/` 79, `digitalizados/` 2) con `scripts/pipeline/mapear_casos.py`. Mapeo nombre-real↔casoNN en `C:\MEFI-privado\mapeo_casos.csv` (fuera del repo y de la nube). `caso01`/`caso02` preservados por compatibilidad con `data/extracted/`; `caso03`/`caso04` reservados (su escaneo original aún no está identificado — tabla en `data/README.md`).
- **Limpieza:** eliminados duplicados y restos — `Mefi_muestra.csv` (0 bytes), duplicado byte-idéntico `20261016_111907_extraido.csv`, `2026-08-18_caso04.csv` (calibración rota, FCF −5831), `src/data/` (2 CSV con UA −22014), carpetas vacías `data/raw_scans/` + `data/processed_scans/` (se reintroducen solo si la Fase 1 los usa), restos de sincronización Drive (`.tmp.drive*`, 2× `desktop.ini`), `__pycache__`/`.pytest_cache`.
- **`app.py::_nombre_archivo_anonimizado`:** las extracciones ahora se guardan como `YYYY-MM-DD_<id-caso>_extraido.csv` usando el ID de registro (editable en UI u OCR de cabecera) y la fecha OCR; fallback a timestamp si no hay metadata. Elimina la clase de duplicados tipo `20261016_1118xx`.
- **`fixtures/muestras_digitizer/`** recibe lo que era `Casos/Finales/samples/` (casos/crops/simples).
- **Pendiente de este bloque (no bloqueante):** confirmar que `C:\Users\usuariohgf\Desktop\Casos` (fuente de `redactar_casos.py`) tampoco se sincroniza a la nube, y sacar `C:\MVP - MEFI` de Google Drive (encontramos `.tmp.driveupload/466395` = índice de git: Drive estuvo tocando el repo).
- **Verificación:** `pytest` 25/25 y `scripts/pipeline/validar_ctu_uhb.py --all` con métricas idénticas a oct-2026 (la reorganización no tocó lógica clínica).

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

- Descarga del dataset completo con `scripts/pipeline/descargar_ctu_uhb.py`.
- Fix del parser de metadata CTU-UHB (espacios múltiples, no `:`).
- Filtrado de dropouts del sensor Doppler (FCF=0 fuera de 50-220 lpm).
- Fix del criterio de Categoría I: ahora exige "sin desaceleraciones repetitivas" (proxy 3+ en 20 min), no cero desaceleraciones.
- Disclaimer clínico agregado en `src/app.py` con referencia al ensayo INFANT.

### Seguridad y redacción de casos (11 ago 2026)

- API key filtrada rotada; historial de git reescrito a commit limpio antes de cualquier push.
- Casos reales redactados a `fixtures/casos_redactados/` con `scripts/pipeline/redactar_casos.py`.
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

## Verificación rápida

```powershell
cd "C:\MVP - MEFI"
.\venv\Scripts\Activate.ps1

# Tests
python -m pytest tests/ -q          # 25/25 verde

# Validación CTU-UHB
PYTHONIOENCODING=utf-8 python scripts/pipeline/validar_ctu_uhb.py --all

# App
PYTHONIOENCODING=utf-8 streamlit run src/app.py
```

---

## Reglas duras

- Nunca commitear `casos_hospital/`, `fixtures/`, `data/ctu_uhb/`, `data/extracted/`.
- Nunca poner nombre/RUT/ID real de paciente en nombres de archivo, mensajes de commit ni código.
- Antes de cambiar un umbral clínico: correr `pytest` **y** `scripts/pipeline/validar_ctu_uhb.py --all`, y reportar sensibilidad/especificidad antes/después.
- No bajar sensibilidad para ganar especificidad con el clasificador por reglas.
