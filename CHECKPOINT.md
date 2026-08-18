# CHECKPOINT: Asesor Clínico MEFI

**Fecha última actualización:** 18 de agosto de 2026
**Estado:** Rediseño de arquitectura en curso — **Fase 4 de 6 completa**. `src/digitizer.py` (Fase 1), `src/clinical.py` + `tests/test_clinical.py` (Fase 2), `src/prompts.py` + informe por texto (Fase 3), y validación CTU-UHB (Fase 4) todos funcionales. **Falta Fase 5 (disclaimer + gobernanza).**

**Extra (fuera del plan de 6 fases, a pedido del usuario):** proveedor LLM ahora 100% configurable por datos — `config.yaml` + `src/llm_client.py` generalizados (label, api_key_env por proveedor), agregado Hugging Face Router como tercera opción junto a OpenRouter/Ollama, y la sidebar de `src/app.py` permite elegir proveedor/modelo/API key y guardarlos como predeterminados sin tocar archivos a mano. Pendiente: empaquetado instalable para otros computadores del hospital (no iniciado).

> El plan completo y detallado (con el porqué de cada decisión) vive en `C:\Users\usuariohgf\.claude\plans\composed-sniffing-moler.md`. Este checkpoint es el resumen ejecutivo para retomar el trabajo directamente en VS Code.

---

## 0. Robustecimiento CTU-UHB + disciplina de datos (18 ago 2026, sesión aparte de las 6 fases)

Bloque de trabajo nuevo, fuera de la numeración de fases 1-6, ejecutado según plan en `C:\Users\usuariohgf\.claude\plans\lucky-skipping-patterson.md`:

- **Remediación PHI en git history:** se encontraron 2 archivos ya commiteados en `data/` con nombres completos de pacientes en el filename (contenido solo numérico, pero el nombre del archivo es PHI). Como era el commit tope (HEAD) sin hijos y sin nada publicado al remote (`origin` vacío, confirmado con `git ls-remote`), se remedió con `git reset --soft` al commit padre + renombrado + recommit, en vez de `git filter-repo`. Verificado con `git rev-list --objects --all | git cat-file --batch-check` que no queda ningún blob con el nombre del paciente.
- **Nomenclatura y carpetas de datos:** `data/README.md` documenta el estándar `YYYY-MM-DD_IDPaciente_HoraInicio`. Nuevas carpetas `data/raw_scans/`, `data/processed_scans/` (gitignored) y `data/extracted/` (CSVs de series de tiempo ya digitalizadas — reemplaza el patrón viejo de `data/*_extraido.csv` sueltos en la raíz).
- **CTU-UHB a escala:**
  - `scripts/descargar_ctu_uhb.py` (nuevo): descarga N registros o el dataset completo (552) vía `wfdb.dl_database()` a `data/ctu_uhb/` (gitignored).
  - **Bug encontrado y corregido** en `scripts/validar_ctu_uhb.py::cargar_registro_ctu_uhb()`: el parser de metadata buscaba `":"` en los comentarios del `.hea`, pero el formato real de CTU-UHB es `#pH           7.14` (espacios múltiples, sin `:`) — nunca capturaba pH/Apgar/BDecf. Corregido con `re.split(r"\s{2,}", ...)`. Verificado contra el registro 1001: ahora sí aparecen `pH: 7.14`, `Apgar1: 6`, `Apgar5: 8`.
  - `scripts/validar_ctu_uhb.py` gana modo batch (`--all`): valida todos los registros descargados y reporta sensibilidad/especificidad de "FIGO II/III" vs. "pH < 7.05" (matriz de confusión).
  - `scripts/create_csv_database.py` (nuevo, pedido explícito del usuario): genera `data/extracted/ctu_uhb/{record_id}.csv` (una serie de tiempo por registro, formato espejo) + `data/extracted/ctu_uhb_outcomes.csv` (una fila por registro con pH/Apgar/BDecf/etc., separado de las series). Ambos gitignored (datos derivados, pueden pesar).
- **Metadatos de cabecera y anotaciones clínicas en `src/digitizer.py`** (nuevo, best-effort igual que la calibración OCR ya existente), **conectadas a la UI de `src/app.py`**:
  - `extraer_metadatos_cabecera(imagen_bytes)`: OCR sobre la franja superior del papel — intenta capturar ID, FHR impreso, fecha/hora, velocidad de papel. 100% local, nunca se envía a un proveedor LLM. Probado sobre los PNG ya redactados en `fixtures/casos_redactados/`: no reintroduce PHI (los campos estructurados salen `None` cuando el dato está tapado; en un caso el OCR alcanzó a leer un fragmento de ID numérico desde `texto_crudo` porque la redacción de ese campo específico no fue 100% — riesgo ya documentado del pipeline de redacción, no algo nuevo que introduzca esta función).
  - `detectar_anotaciones_clinicas(prep)`: OCR + keyword-spotting (peridural, oxitocina, meconio, etc.) en la franja debajo del panel UA, donde suelen ir anotaciones a mano. No clasifica impacto clínico, solo lo reporta como advertencia de texto para que el clínico lo confirme y para que `prompts.py` lo use como contexto.
  - En `src/app.py`: al preparar una imagen nueva se corren ambas funciones; los metadatos salen en un expander editable (el clínico corrige antes de confiar) y las anotaciones como `st.info` junto a las demás advertencias.
- **Disclaimer clínico (Fase 5, parte 1) agregado en `src/app.py`**: banner fijo bajo el título — ayuda diagnóstica no diagnóstico, referencia al ensayo INFANT (Lancet 2017), simplificación de MVP no validada en la población del Hospital Gustavo Fricke. Gobernanza de datos con OpenRouter sigue pendiente aparte.
- **Validación completa sobre los 552 registros de CTU-UHB — encontró y corrigió 2 problemas reales en la lógica clínica, no solo en el pipeline de datos:**
  1. **Dropouts del sensor Doppler sin filtrar** (`scripts/validar_ctu_uhb.py::convertir_a_dataframe`): CTU-UHB marca pérdida de contacto con FCF=0 (no NaN) — ~22% de las muestras en el registro 1001. Sin filtrarlas, un 0 dentro de una ventana de 1 minuto arruina el cálculo de variabilidad (máximo-mínimo) en `clinical.py`. Fix: `fcf_confiable = False` para valores fuera de 50-220 lpm (`FCF_MIN_FISIOLOGICO`/`FCF_MAX_FISIOLOGICO`), igual que `digitizer.py` ya hace con sus propios tramos dudosos.
  2. **Criterio de Categoría I demasiado estricto en `clinical.py::clasificar_figo()`**: exigía cero desaceleraciones tardías/variables, cuando FIGO 2015 en realidad exige que no sean *repetitivas* (>50% de las contracciones). Nuevo helper `_hay_desaceleraciones_repetitivas()` (proxy: 3+ en una ventana de 20 min) — una o dos aisladas ya no descalifican de Normal. `tests/test_clinical.py` actualizado: el test viejo que asumía "1 desaceleración tardía → Categoría II" se reemplazó por dos tests (aislada → I, repetitivas → II).
  - **Resultado del batch de 552 registros, antes/después de ambos fixes** (sensibilidad/especificidad de "FIGO II/III" vs. "pH de cordón < 7.05"):
    | | Antes (bug dropout) | + fix dropout | + fix repetitivas |
    |---|---|---|---|
    | Categoría I | 0/552 | 16/552 | 59/552 |
    | Sensibilidad | 100% | 100% | 95% |
    | Especificidad | 0% | 3.1% | 11.1% |
  - 11.1% de especificidad sigue siendo bajo, pero a partir de acá ya no es un bug de datos — es la limitación real y conocida de un clasificador basado en reglas simplificadas (consistente con la literatura: alta sensibilidad / baja especificidad es un patrón recurrente en sistemas de apoyo a CTG, el mismo punto de fondo del ensayo INFANT ya citado en el disclaimer). Mejorarlo más allá de esto requeriría lógica más fina en `clinical.py` (correlación real con contracciones, criterios de "atípica" en variables) — trabajo de una sesión dedicada, no seguido a ciegas acá.
- `pytest`: 19/19 verde.

---

## 1. Qué se hizo en esta sesión (11 ago 2026)

### 1.1 Seguridad — cerrado
- Se encontró una API key real de OpenRouter hardcodeada en `test_conexion.py` y `.streamlit/secrets.toml`, ambas ya trackeadas en git.
- `.gitignore` estaba corrupto (guardado en UTF-16 por un bug del entorno), por eso no excluía `secrets.toml` de verdad — reescrito en UTF-8 plano.
- Historial de git reescrito a un solo commit limpio (`b626889`) antes de cualquier `push` (el remoto `origin` seguía vacío) — verificado objeto por objeto que la key vieja no existe en ningún blob del repo.
- Key rotada en el dashboard de OpenRouter. La key vigente vive solo en `.env` y `.streamlit/secrets.toml` (ambos gitignored), nunca en código. `test_conexion.py` ahora la lee vía `python-dotenv`.

### 1.2 Investigación de estado del arte — cerrada
Investigación profunda (dos agentes en paralelo) sobre IA aplicada a interpretación de CTG/EFM fetal: guías clínicas vigentes (FIGO 2015, NICE NG229, ACOG, consenso fisiológico internacional 2018/rev. 2024), sistemas comerciales (STAN, PeriGen PeriWatch, K2 INFANT-Guardian...), el ensayo INFANT (Lancet 2017) como caso de precaución (precisión de clasificación ≠ beneficio clínico demostrado), el dataset abierto CTU-UHB (PhysioNet), y evidencia de que **ningún modelo de visión genérico (Qwen-VL, GPT-4V, Gemini, Claude) es confiable leyendo coordenadas numéricas exactas desde una imagen de gráfico** — la razón técnica detrás del rediseño de arquitectura de este plan.

Publicada como artifact: `https://claude.ai/code/artifact/1e09035f-ced7-44c3-bdcd-6fd5a7b3ea06`

### 1.3 Plan de trabajo — aprobado
Plan de 6 fases guardado en `C:\Users\usuariohgf\.claude\plans\composed-sniffing-moler.md`. Decisiones ya tomadas (no volver a discutirlas, solo ejecutar):

- **Arquitectura:** separar la digitalización de la imagen (determinística, auditable) de la interpretación clínica (LLM) — hoy `analizar_imagen_mefi()` en `src/app.py` hace ambas cosas en una sola llamada.
- **Calibración del digitalizador:** OCR con Tesseract desde la Fase 1 (no diferido), con calibración manual/2-clics como *fallback* si el OCR no da confianza suficiente.
- **Alcance del digitalizador:** FCF **+ UA** (actividad uterina) desde el inicio, para poder subclasificar desaceleraciones (precoz/tardía/variable) según FIGO/NICE.
- **Tests:** `pytest` solo para `src/clinical.py` (lógica de clasificación de riesgo fetal). El resto del repo sigue con scripts ad-hoc.
- **Proveedor LLM:** **OpenRouter como principal**, Ollama local como opción 2 en el mismo selector de la sidebar. **Pendiente sin resolver:** acuerdo de tratamiento de datos con OpenRouter/Google/Anthropic para datos reales de pacientes — hasta confirmarlo, ningún dato de paciente real (ni redactado) debe enviarse a OpenRouter, solo usarse localmente.

### 1.4 Implementación — Fase 0 en curso
- **Tesseract-OCR 5.4.0 instalado** vía `winget` (sin admin) en `C:\Users\usuariohgf\AppData\Local\Programs\Tesseract-OCR\tesseract.exe`. **No quedó en el PATH del sistema** — cualquier código que use `pytesseract` debe fijar `pytesseract.pytesseract.tesseract_cmd` a esa ruta explícitamente (ver patrón ya usado en `scripts/redactar_casos.py`).
- El usuario compartió **19 casos reales** en `C:\Users\usuariohgf\Desktop\Casos\` (18 PDF + 1 JPEG). Confirmado visualmente que **no están de-identificados**: tienen `ID:` y `Nombre:` de paciente visibles, repetidos en cada segmento de página. El hospital está adquiriendo además un escáner para mejorar la resolución de estas capturas a futuro.
- **Decisión del usuario:** redactar (tapar) `ID`/`Nombre`/`RUT`/`Paciente` en cada archivo antes de usarlo para cualquier cosa, incluso pruebas 100% locales.
- Construido `scripts/redactar_casos.py`:
  - Para PDFs con texto nativo: borra de verdad el texto (no solo lo tapa visualmente) vía `page.add_redact_annot()` + `page.apply_redactions()` de PyMuPDF.
  - Además corre una pasada de OCR en 4 rotaciones (0°/90°/180°/270°, las fotos vienen apaisadas) sobre la página rasterizada, para tapar cualquier ID/Nombre que venga como imagen/foto y no como texto nativo. Combina las 4 detecciones tomando el mínimo por píxel.
  - Salida: un PNG por página en `fixtures/casos_redactados/` (**gitignored** — agregado a `.gitignore` junto con `data/ctu_uhb/`, que se usará en la Fase 4).
- Corrida lanzada en background esta sesión; al momento de este checkpoint iba en ~47 páginas procesadas (de ~50 esperadas). **Revisar el estado real al retomar** (`ls fixtures/casos_redactados` — debería haber terminado).

**Pendiente crítico e inmediato:** revisar visualmente **cada** PNG en `fixtures/casos_redactados/` y confirmar que ningún ID/Nombre/RUT queda legible antes de usarlos para calibrar nada. La redacción automática es *best-effort*, no está garantizada al 100% (confirmado: en al menos un archivo de prueba la redacción falló completamente en la primera pasada y quedó parcial en la segunda — ver 1.5). Si algún archivo queda con datos visibles, ajustar `KEYWORDS`/`PAD` en `scripts/redactar_casos.py` y volver a correrlo solo para ese archivo.

### 1.5 Implementación — Fase 1 (`src/digitizer.py`) — funcional, con una decisión de diseño importante

Construido `src/digitizer.py` con la arquitectura de dos pasos (`preparar_imagen()` → `digitalizar_con_calibracion()`) e integrado en `src/app.py`. Piezas:

- **Orientación automática:** prueba las 4 rotaciones de 90°, descarta las que no separan dos paneles horizontales, y desempata entre las que sí (ej. imagen correcta vs. al revés) con `pytesseract.image_to_osd` — su confianza absoluta es baja en estas fotos ruidosas, pero el "Rotate" sugerido (0 vs 180) resultó ser una señal confiable en la práctica.
- **Detección automática de paneles FCF/UA:** ubica el papel por contraste de brillo contra el fondo (señal fuerte y confiable), y separa FCF de UA buscando el hueco entre ambos. **Esta parte NO llegó a ser precisa** — en las pruebas, el "hueco" detectado terminó siendo un mínimo local de tinta dentro de la propia grilla, no el límite real del panel (confirmado midiendo a mano con una regla de píxeles sobre la imagen). En vez de seguir puliendo esa heurística, se le da **margen generoso** a cada panel (no corta la grilla real) y se acepta que el límite automático es aproximado.
- **Extracción de curva:** color + seguimiento por continuidad, con desempate por grosor de trazo (para no "engancharse" en bloques de texto/tinta más gruesos que la línea real) y detección de outliers contra una mediana móvil local. Huecos causados por ID/Nombre/fecha a mano/dobleces se interpolan y quedan registrados en `advertencias` con su rango de tiempo. **Validado visualmente contra 2 casos reales distintos** — sigue el trazo real con alta fidelidad.
- **Calibración del eje Y — decisión final: 2 clics manuales, no OCR.** Se intentó que `pytesseract` leyera las etiquetas numéricas del eje (`_calibrar_eje_ocr`, sigue en el código como intento automático de mejor esfuerzo) pero resultó **poco confiable de forma consistente** en estas fotos/escaneos reales (texto de impresora térmica, chico, sobre grilla). El usuario decidió priorizar calibración manual: en `src/app.py`, `_widget_calibracion()` muestra el panel recortado vía `streamlit_image_coordinates`, el clínico hace clic en 2 líneas de grilla de valor conocido, y `calibrar_desde_dos_puntos()` arma la calibración lineal desde esos 2 puntos reales (confianza 1.0, no estimada). **Esto no se probó interactivamente en el navegador** (el tooling de este sesión no pudo simular clics en el uploader de Streamlit) — si algo falla en el flujo de clics real, es lo primero a revisar.
- Verificado end-to-end con puntos de calibración medidos a mano sobre `MEFI.pdf`: línea base ≈112 lpm, rango 84-146, 88% de cobertura confiable — coherente con una lectura visual del trazado.

**Dependencias nuevas:** `scipy` (ya era transitiva vía scikit-learn, ahora explícita), `streamlit-image-coordinates` (clics sobre imagen), `wfdb` (confirmado compatible con Python 3.14.5, para Fase 4) — las tres ya en `requirements.txt`.

---

## 2. Plan de trabajo completo (6 fases)

Detalle técnico completo de cada fase en `C:\Users\usuariohgf\.claude\plans\composed-sniffing-moler.md`. Resumen:

- [ ] **Fase 0 (parcial):** redacción de casos reales corrida pero **no verificada visualmente al 100%** (crítico, ver 1.4); falta generar fixtures sintéticas con `matplotlib`; falta limpiar los `data/*_extraido.csv` vacíos.
- [x] **Fase 1 (funcional, ver 1.5):** `src/digitizer.py` — orientación + detección de paneles automática (aproximada, con margen generoso), calibración por 2 clics manuales (`streamlit-image-coordinates`), extracción de curva con detección de huecos/interpolación auditable, integrado en `src/app.py`. **Sin probar interactivamente en navegador real.**
- [x] **Fase 2 (completa, 13 ago 2026):** `src/clinical.py` + `tests/test_clinical.py` (pytest, 18 tests, todos en verde) — línea base (mediana iterativa excluyendo acel/decel, redondeada a 5 lpm), variabilidad real (banda de amplitud pico-a-pico por minuto excluyendo eventos con margen, no desviación estándar), aceleraciones (>=15 lpm, 15s-10min), desaceleraciones subclasificadas precoz/tardía/variable/indeterminada correlacionando el nadir contra picos de UA, patrón sinusoidal (FFT en banda 3-5 ciclos/min, amplitud 5-15 lpm, >=10 min sostenidos), `clasificar_figo()` (categorías I/II/III + semáforo NICE NG229 por variable). Punto de entrada único: `extraer_features(df)`. Tolerante a DataFrames sin `fcf_confiable`/`ua` (formato viejo de `data/sample.csv`, pre-digitizer). **Nota:** es una simplificación de MVP — no cubre cada matiz de FIGO/NICE (ver disclaimer pendiente de Fase 5); la validación real contra outcome (pH de cordón, CTU-UHB) es la Fase 4, todavía pendiente.
- [x] **Fase 3 (completa, 13 ago 2026):** `src/prompts.py` (nuevo) — `SYSTEM_INSTRUCTIONS` con los umbrales FIGO/NICE importados directo de `clinical.py` (nunca se desincronizan) + razonamiento de tipo de hipoxia (precoz/variable/tardía → compresión cabeza/cordón/insuficiencia uteroplacentaria, consenso 2018/rev. 2024) y `construir_prompt_usuario(features)` que renderiza el dict de `clinical.extraer_features()` como texto estructurado. `src/app.py`: `analizar_imagen_mefi()` (mandaba la imagen en base64) reemplazada por `generar_informe_clinico(features, client, modelo)` — el LLM ya NO ve la imagen, solo el texto clasificado; la UI ahora muestra la clasificación FIGO/semáforo NICE antes del botón de informe. `config.yaml` gana `text_models` por proveedor (separado de `vision_models`, que queda documentado pero sin uso activo) y `active_provider: openrouter` por defecto. Verificado: `pytest` (18/18), `streamlit run` levanta sin excepciones, prompt de sistema y de usuario generados correctamente sobre un caso sintético.
- [x] **Fase 4 (completa, 18 ago 2026):** `wfdb` instalado y confirmado compatible con Python 3.14.5; lectura de un registro real de CTU-UHB (1001) verificada end-to-end con 19,200 muestras en 80 minutos. Script `scripts/validar_ctu_uhb.py` completado: carga .hea/.dat de PhysioNet, convierte a DataFrame uniforme, ejecuta pipeline de `clinical.py`, y reporta clasificación FIGO/NICE. Validación de Registro 1001 completada: Categoría III con variabilidad aumentada y múltiples desaceleraciones. **Documentación:** [VALIDACION_CTU_UHB.md](VALIDACION_CTU_UHB.md) incluye procedimiento de validación, comparación camino manual vs. CTU-UHB, y línea base de correctitud.
- [ ] **Fase 5:** disclaimer clínico visible en la UI de Streamlit + documentar el precedente INFANT/STAN (precisión ≠ beneficio clínico) en este mismo archivo.

Tareas también están trackeadas en el sistema de tasks de esta sesión (#1 a #6, una por fase).

---

## 3. Cosas a tener presente al retomar en VS Code

- Leer `C:\Users\usuariohgf\.claude\plans\composed-sniffing-moler.md` antes de tocar código — tiene el enfoque técnico decidido para cada fase, no solo el resumen.
- **Nunca commitear** nada de `fixtures/` ni `data/ctu_uhb/` — ya están en `.gitignore`, pero doble-chequear si se agregan archivos nuevos fuera de esas carpetas.
- El riesgo de privacidad de datos con OpenRouter (imágenes/datos de pacientes reales saliendo del hospital) **sigue sin resolución formal**. No conectar los casos reales (ni redactados) a OpenRouter todavía — solo Ollama local o fixtures sintéticas hasta que se confirme.
- El `venv` usa Python 3.14.5. `pytesseract` necesita `tesseract_cmd` apuntado manualmente (no quedó en PATH del sistema).
- Si el entorno se mueve a otra máquina del hospital, Tesseract-OCR se instala sin admin vía `winget install --id UB-Mannheim.TesseractOCR -e`.

## 4. Notas técnicas históricas (pre-11 ago 2026)
- **Error 400 (Invalid Image Input):** se sospechó que `response_format={"type": "json_object"}` causaba conflictos con modelos de visión; se eliminó.
- **Error 404:** los IDs de modelos en OpenRouter son sensibles — usar `verificar_modelos.py` o la lista oficial antes de asumir un ID.
- Estructura previa: `App -> LLM Factory -> Provider` (sigue vigente como base; Fase 1-3 la extienden, no la reemplazan).
