# CHECKPOINT: Asesor Clínico MEFI

**Fecha última actualización:** 9 de noviembre de 2026
**Estado general:** **Asesor Clínico MEFI v2.0 completado y verificado (Fases A, B, C y D; `VERSION_PROMPT = "v2.0-final-2026-11-09"`).** Fases 1-4 originales completas; Fase 5 (disclaimer clínico reforzado con ACOG CPG No. 10 + INFANT) visible en UI. Fase 0 (higiene y privacidad), Fase 1 (empaquetado instalable probado en otro PC) y Fase 1.1/1.2 (calibrador arrastrable con mouse, píldoras de escala en 1 clic con validador anti-error, barra de progreso y auto-colapsado, modo práctica con trazado sintético, tabla clínica de desaceleraciones, comparación Plantilla vs. IA y reporte PDF consolidado) completadas. Próxima fase de despliegue: Gobernanza de datos LLM (Fase 2, ver [ROADMAP.md](ROADMAP.md)).

**Validación actual post-Fase B v2.0 (CTU-UHB, 552 registros):** sensibilidad **95.0 %** (VP 38, FN 2) / especificidad **10.9 %** (VN 56, FP 456) / PPV **7.7 %** / NPV (VPN) **96.6 %** / exactitud balanceada **53.0 %**. AUROC área-desaceleraciones **0.710**. Cumple íntegramente el criterio de no inferioridad (sensibilidad ≥95.0 % y VPN ≥96.6 %; detalle paso a paso en [docs/VALIDACION_CTU_UHB.md](docs/VALIDACION_CTU_UHB.md)).

**Nota:** el plan técnico original en `C:\Users\usuariohgf\.claude\plans\composed-sniffing-moler.md` ya no existe; este checkpoint, [CLAUDE.md](CLAUDE.md) y [docs/MATRIZ_CONCILIACION_MEFI_v2.0.md](docs/MATRIZ_CONCILIACION_MEFI_v2.0.md) son hoy las fuentes de decisión del proyecto.

---

## Historial de decisiones clave

### MEFI v2.0 — Fases B, C y D completadas: Definiciones NICHD/ACOG validadas, Módulos Protocolo V2 y Diseños P3 (09 nov 2026)

- **Fase B — Definiciones NICHD/ACOG ejecutadas y validadas paso a paso (`src/clinical.py`, `src/prompts.py`, `docs/VALIDACION_CTU_UHB.md`):** cada cambio se ejecutó de manera individual verificando `pytest` y `scripts/pipeline/validar_ctu_uhb.py --all` sobre los 552 registros de CTU-UHB:
  - **B1 (`DESACEL_PROLONGADA_MIN_S = 120`):** desaceleración prolongada ajustada de 180s a **120s (2 min)** según ACOG CPG No. 10 Tabla 1 y Protocolo V2, conservando `DESACEL_MUY_PROLONGADA_S = 300` (5 min) como criterio patológico directo. Sensibilidad **95.0 %**, VPN **96.6 %**.
  - **B2 (`SINUSOIDAL_DURACION_MIN_S = 1200`):** duración mínima del patrón sinusoidal ajustada de 600s a **1200s (20 min)** según ACOG Tabla 1, reportando la duración efectiva en minutos y una nota explícita de que el Protocolo V2 institucional exige **>30 min** con ausencia de aceleraciones. Sensibilidad **95.0 %**, VPN **96.6 %**.
  - **B3 (Aceleraciones por edad gestacional y aceleración prolongada):** `detectar_aceleraciones()` parametriza el umbral por edad gestacional (`<32 semanas` usa **10 lpm × 10 s**; por defecto **15 lpm × 15 s**) y etiqueta como `aceleración prolongada` los eventos de **2 a 10 minutos (120–600s)**. Sensibilidad **95.0 %**, VPN **96.6 %**.
  - **B4 (Taquisistolía por promedio móvil de 30 minutos):** `_calcular_taquisistolia_ventana_30m()` evalúa el criterio ACOG/Protocolo V2 (`>5 contracciones en 10 min promediadas en ventana de 30 min`) y conserva la tasa global `≥5/10 min` (NICE NG229) como respaldo en trazados `<30 min`, exponiendo ambos criterios en el semáforo y en los informes. Sensibilidad **95.0 %**, VPN **96.6 %**, especificidad **10.9 %**.
  - **B5 (Variabilidad en 4 categorías NICHD):** `calcular_variabilidad()` expone `categoria_nichd` (`ausente` <1.0 lpm, `minima` ≤5.0 lpm, `moderada` 6–25 lpm, `marcada` >25 lpm) manteniendo `categoria` (`reducida`/`normal`/`aumentada`) para retrocompatibilidad. Sensibilidad **95.0 %**, VPN **96.6 %**.
  - **B6 (Variabilidad intra-desaceleración):** en cada desaceleración `≥2 min` (120s), `detectar_desaceleraciones()` mide la amplitud pico-a-pico detrended dentro del evento (`variabilidad_intra_lpm`) y activa `variabilidad_reducida_intra_evento = True` si es `<5 lpm`. Sensibilidad **95.0 %**, VPN **96.6 %**.
- **Fase C — Módulos informativos del Protocolo V2 (`src/clinical.py`, `src/prompts.py`, `src/ux_helpers.py`, `src/app.py`, `src/reporte_pdf.py`):**
  - **C1 (`evaluar_criterios_60`):** evalúa en desaceleraciones variables los 3 criterios «60» (`duración >60s`, `nadir <60 lpm`, `caída >60 lpm`) y activa el marcador de riesgo independiente si `≥2` criterios persisten por **más de 30 minutos**.
  - **C2 (`tipificar_hipoxia`):** tipifica de forma determinística e informativa la hipoxia intraparto en **Aguda**, **Subaguda**, **Progresiva** o **Crónica** según el Protocolo V2, integrándola en la Sección 3 de los informes y en tarjeta propia de la UI sin alterar la categoría FIGO.
  - **C3 (Contexto clínico estructurado):** incorpora los campos opcionales de **meconio**, **patología antenatal** y **comparación con MEFI previos** (con recordatorio del flujo de interpretación del Protocolo V2) en la UI, el prompt del LLM, el informe por plantilla y el PDF consolidado.
  - **C4 (Actualización de UI):** la tabla clínica de desaceleraciones y las tarjetas de la Sección 3 muestran los criterios «60», la variabilidad intra-evento, el riesgo Box 3 ACOG, la tipificación de hipoxia y la lectura ACOG estricta.
- **Fase D — Línea de investigación P3 y Matriz de Conciliación (`docs/`):**
  - **D1:** documento de diseño [`docs/DISENO_SCORE_CONTINUO_DEEPCTG.md`](docs/DISENO_SCORE_CONTINUO_DEEPCTG.md) y script prototipo [`scripts/pipeline/prototipo_score_continuo_ctu_uhb.py`](scripts/pipeline/prototipo_score_continuo_ctu_uhb.py).
  - **D2:** documento de diseño [`docs/DISENO_LINEA_TIEMPO_PARTO.md`](docs/DISENO_LINEA_TIEMPO_PARTO.md) para registro longitudinal de evaluaciones sucesivas.
  - **Capítulo 7 (Matriz de Conciliación):** documentado en [`docs/MATRIZ_CONCILIACION_MEFI_v2.0.md`](docs/MATRIZ_CONCILIACION_MEFI_v2.0.md).

### MEFI v2.0 — Fase A completada: Alineación normativa Protocolo V2 (sept. 2025) y ACOG CPG No. 10 (2025) sin cambio de umbrales (09 nov 2026)

- **A1 — Conducta sugerida en Categoría II y III (`src/prompts.py`, `VERSION_PROMPT = "v2.0-faseA-2026-11-09"`):** se actualizaron `generar_informe_plantilla()` y `SYSTEM_INSTRUCTIONS` incorporando: (a) en Categoría II, aviso inmediato al médico/a ginecobstetra residente de turno por la matrón/a, lateralización materna, hidratación EV/corrección de hipotensión, reducción/suspensión de oxitocina, **amnioinfusión** ante desaceleraciones variables recurrentes, **corrección de fisiopatología materna** ante taquicardia, **oxígeno suplementario solo si SatO2 < 94 %** (citando recomendación ACOG CPG No. 10 contra uso rutinario), **tocolisis de acción rápida** (institucional: nitroglicerina/fenoterol; ACOG cita terbutalina) si persiste taquisistolía asociada a rasgos de alto riesgo, y ventana de observación de **½ a 1 hora** según Protocolo V2 matizada por el Box 3 ACOG; (b) en Categoría III, aviso inmediato, reanimación urgente, matices ACOG por subtipo (bradicardia con sospecha de rotura uterina → parto lo antes posible; contracción tetánica/taquisistolía → tocolisis antes del parto; sinusoidal > 30 min → parto expedito) y máximo **10 minutos** de observación del Protocolo V2 si no revierte.
- **A2 — Subclasificador determinístico de riesgo Box 3 ACOG (`evaluar_riesgo_categoria_ii()` en `src/clinical.py`):** estratifica Categoría II en `alto`, `intermedio` o `con rasgos protectores` evaluando variabilidad reducida/ausente, taquicardia, desaceleraciones tardías/variables recurrentes y >1 desaceleración prolongada frente a variabilidad moderada y presencia de aceleraciones, sin alterar `clasificar_figo()`.
- **A3 — Alerta informativa de sospecha de FCF materna (`detectar_sospecha_fcf_materna()` en `src/clinical.py`):** cuando se detectan ≥2 aceleraciones coincidentes temporalmente con picos de contracciones uterinas, emite recordatorio de verificar pulso materno con pulsioxímetro (ACOG CPG No. 10 / Protocolo V2 Supuesto 5).
- **A4 — Refuerzo del disclaimer regulador (`src/app.py`, `src/prompts.py`):** cita explícitamente la recomendación fuerte (evidencia moderada) de ACOG CPG No. 10 en contra de depender primariamente de sistemas computarizados para interpretar y manejar la FCF, junto al ensayo INFANT (Lancet 2017).
- **A5 — Reporte comparativo «ACOG estricta vs. MEFI» (`clasificar_acog_estricta()` en `src/clinical.py`):** contrasta la clasificación MEFI de alta sensibilidad (FIGO/NICE, sensibilidad 95.0 % / VPN 96.6 %) con la definición estricta NICHD/ACOG de Categoría III (variabilidad ausente <1 lpm + desaceleraciones recurrentes/bradicardia, o sinusoidal), exponiendo la nota comparativa en la UI y en ambos informes.

### Mejoras de experiencia de usuario (UX) y seguridad clínica en 4 bloques — Fase 1.2 (09 nov 2026)

- **Separación de responsabilidades y funciones puras verificables (`src/ux_helpers.py`, `tests/test_clinical.py`):** toda la lógica de validación de calibración, cálculo de calidad de lectura, formateo clínico de eventos y generación de trazados sintéticos de práctica se aisló en un módulo puro `src/ux_helpers.py` cubierto por tests unitarios (`32/32 passed`).
- **Bloque 1 — Seguridad de Calibración y Píldoras de 1 clic (`validar_estado_calibracion`, `_widget_calibracion` en `src/app.py`):** se agregaron botones rápidos de 1 clic con los múltiplos estándar del papel CTG (`210/180/150/120` y `90/60/50/30` en FCF; `100/80/60/50` y `40/25/20/0` en UA) mediante callbacks `on_click` seguros, y un validador preventivo que bloquea calibraciones con valores iguales, líneas colapsadas (`<15 px`) o escalas invertidas (ofreciendo un botón de 1 clic «🔄 Intercambiar valores Azul ↔ Roja»).
- **Bloque 2 — Flujo guiado por etapas y auto-colapsado inteligente (`_render_barra_progreso_ux` en `src/app.py`):** barra superior de 3 etapas (`1. Cargar monitoreo` → `2. Validar líneas de escala` → `3. Informes y PDF Consolidado`) y plegado automático del Paso 1 una vez digitalizado el trazado para llevar la vista directo a los resultados clínicos.
- **Bloque 3 — Seguridad de Auditoría y Lectura Clínica (`calcular_calidad_lectura`, `formatear_tabla_desaceleraciones`):** en la Sección 2 se muestra el porcentaje de lectura directa vs. interpolación junto a un botón rápido «🔧 Reajustar líneas de escala (Paso 1)», y en la Sección 3 se reemplazó el JSON crudo por una tabla clínica estructurada (*Inicio mm:ss*, *Fin mm:ss*, *Duración*, *Caída máx. lpm*, *Clasificación FIGO*, *Alerta >3 min*).
- **Bloque 4 — Barra lateral en Modo Clínico y Trazado Sintético de Práctica (`generar_imagen_ctg_demo`):** la barra lateral muestra en primer plano el estado de los motores (`📋 Motor Clínico Determinístico: Activo` y `🟢 IA Conectada y Lista`) dejando los ajustes técnicos dentro de un desplegable cerrado (`🔧 Configuración técnica de IA`), y la pantalla principal incorpora el botón **«🧪 Probar con un trazado de ejemplo»** que genera en memoria un monitoreo sintético libre de datos de pacientes reales para entrenamiento.

### Usabilidad en terreno, informe por plantilla, comparación alineada y PDF consolidado — Fase 1.1 (06 nov 2026)

- **Calibración interactiva arrastrando las líneas directamente con el mouse (`src/componente_calibrador/`, `src/app.py`, `src/digitizer.py`):** se reemplazó `streamlit_image_coordinates` + sliders por un componente HTML/JS nativo (`src/componente_calibrador/index.html`) que dibuja la **🔵 Línea 1 Azul** y la **🔴 Línea 2 Roja** sobre cada panel (**FCF** y **UA**) y permite **arrastrarlas directamente con el mouse hacia arriba o abajo** a 60 FPS sin que la imagen desaparezca ni parpadee (`Streamlit.setFrameHeight` persistente en `ResizeObserver` y `RENDER_EVENT`). Además, `sugerir_puntos_calibracion()` filtra las lecturas OCR estrictamente a múltiplos válidos de escala CTG (`VALORES_ESCALA_FCF` y `VALORES_ESCALA_UA`), evitando números espurios (como `58`), para que el usuario solo tenga que arrastrar las líneas con el mouse y confirmar el número en las casillas inferiores (`step=10.0, format="%.0f"`).
- **Ejecución unificada al digitalizar + Síntesis de Concordancia (`src/app.py`, `src/prompts.py`):** al pulsar **«🚀 Digitalizar trazado y generar informes (Plantilla + IA)»**, el sistema extrae las curvas, genera el **Informe Determinístico por Plantilla** y, si hay proveedor LLM configurado, ejecuta **automáticamente el Informe IA** en el mismo paso (manteniendo también un botón de regeneración manual). Se agregó `generar_sintesis_concordancia()`, que muestra un recuadro superior resumiendo la convergencia y matices entre ambos informes.
- **Diseño visual ágil (`layout="wide"`) y comparación dimensión por dimensión (`src/app.py`, `src/prompts.py`):** la sección 3 reemplaza la tabla desproporcionada por un banner de Categoría FIGO y **6 tarjetas ejecutivas de KPIs** con el semáforo NICE. La sección 4 alinea fila por fila las **4 dimensiones clínicas** (*1. Parámetros y Hallazgo Principal*, *2. Clasificación Normativa FIGO/NICE*, *3. Correlación Fisiopatológica*, *4. Conducta Sugerida*) entre Plantilla e IA.
- **Contexto obstétrico, observaciones del profesional y Reporte Consolidado en PDF (`src/reporte_pdf.py`):** se agregaron campos opcionales de contexto clínico (*Edad gestacional*, *Contexto obstétrico*, *Uso de oxitocina*) y de validación presencial (*Nombre del profesional responsable* y *Observaciones clínicas*), los cuales se integran tanto en los informes como en el documento A4 descargable (`.pdf`) junto al trazado digitalizado y la tabla comparativa.
- **API key preconfigurada en el instalador, gobernanza y arranque limpio (`src/rutas.py`, `scripts/pipeline/build_portable.py`, `MEFI.bat`, `docs/GOBERNANZA_DATOS_LLM.md`):** `build_portable.py` incluye `.env` dentro de `dist/MEFI-portable/` (ignorado por Git), `rutas.sembrar_home()` completa las claves en `%LOCALAPPDATA%\MEFI\.env`, y se redactó la propuesta formal de gobernanza en `docs/GOBERNANZA_DATOS_LLM.md`.

### Empaquetado instalable — Fase 1 completada (05–06 nov 2026)

- **Enfoque elegido:** bundle portable con **Python embebido** (no PyInstaller: streamlit+PyInstaller es frágil) + script InnoSetup (`installer/mefi.iss`) que lo empaqueta en `Setup.exe` con instalación por usuario (`{localappdata}`, sin administrador). `scripts/pipeline/build_portable.py` construye `dist/MEFI-portable/` (descarga python-3.14.x-embed, habilita site-packages en el `._pth`, instala `requirements.txt`, copia `src/`, `MEFI.bat`, `config.yaml`, guía Word y README).
- **Portabilidad de rutas (nuevo `src/rutas.py`):** todas las rutas dejan de depender del cwd. En el bundle, `MEFI.bat` define `MEFI_HOME=%LOCALAPPDATA%\MEFI` y la app siembra ahí `config.yaml`, `.env` y `data/` (config y datos deben ser escribibles aunque la app se instale en carpeta de solo lectura). En desarrollo (sin `MEFI_HOME`) todo sigue en la raíz del repo, comportamiento idéntico al histórico.
- **Tesseract configurable:** `digitizer` acepta `MEFI_TESSERACT` (env) y `tesseract\tesseract.exe` junto al bundle, además de las rutas de instalación clásicas. La app ya degradaba bien sin OCR (confirmado: `_TESSERACT_OK` guarda todos los puntos de llamada).
- **`MEFI.bat`:** ahora prefiere `python\python.exe` del bundle (sin venv ni pip en el equipo destino) y conserva el flujo venv para el repo. `crear_acceso_directo.ps1` resuelve la raíz desde su propia ubicación en vez de ruta dura.
- **Verificación local y en equipo externo:** pytest 25/25; smoke de streamlit con el Python del repo (HTTP 200) y con el **Python embebido del bundle** (HTTP 200); **modo instalado verificado** (`MEFI_HOME` en ruta limpia: siembra de `config.yaml` + `data/`, `ruta_escritura` y lectura de providers por `llm_client` OK); batch CTU-UHB idéntico. **Probado en un segundo PC (06-11-2026):** la aplicación cargó y corrió correctamente tras la demora inicial de arranque. Falta únicamente definir la gobernanza LLM (Fase 2) antes de distribuir masivamente.

### Guía general para profesionales (05 nov 2026)

- Nuevo `docs/GUIA_PROFESIONALES.md`: qué es el sistema, objetivos, uso paso a paso, límites validados explicados en palabras simples, privacidad y glosario — en lenguaje neutro para audiencias no técnicas (clínica, innovación, TI, gestión). Enlazada desde CLAUDE.md §1.

### Reorganización Fase 0 — higiene, privacidad y base de casos (05 nov 2026)

- **Estructura:** `scripts/` dividido en `pipeline/` + `analisis/` + `utilidades/` con `scripts/README.md`; documentos movidos a `docs/` (`ESTADO_DELARTE_2026.md`, `VALIDACION_CTU_UHB.md`, `VALIDAR_CTU_UHB_QUICK_START.md`; figuras a `docs/figs/`); creado `ROADMAP.md` (plan vivo — los pendientes de este archivo migraron ahí).
- **Anonimización de escaneos:** `Casos/` eliminada; sus 81 archivos renombrados al estándar anónimo en `casos_hospital/` (`escaneos/` 79, `digitalizados/` 2) con `scripts/pipeline/mapear_casos.py`. Mapeo nombre-real↔casoNN en `C:\MEFI-privado\mapeo_casos.csv` (fuera del repo y de la nube). `caso01`/`caso02` preservados por compatibilidad con `data/extracted/`; `caso03`/`caso04` reservados (su escaneo original aún no está identificado — tabla en `data/README.md`).
- **Limpieza:** eliminados duplicados y restos — `Mefi_muestra.csv` (0 bytes), duplicado byte-idéntico `20261016_111907_extraido.csv`, `2026-08-18_caso04.csv` (calibración rota, FCF −5831), `src/data/` (2 CSV con UA −22014), carpetas vacías `data/raw_scans/` + `data/processed_scans/` (se reintroducen solo si la Fase 1 los usa), restos de sincronización Drive (`.tmp.drive*`, 2× `desktop.ini`), `__pycache__`/`.pytest_cache`.
- **`app.py::_nombre_archivo_anonimizado`:** las extracciones ahora se guardan como `YYYY-MM-DD_<id-caso>_extraido.csv` usando el ID de registro (editable en UI u OCR de cabecera) y la fecha OCR; fallback a timestamp si no hay metadata. Elimina la clase de duplicados tipo `20261016_1118xx`.
- **`fixtures/muestras_digitizer/`** recibe lo que era `Casos/Finales/samples/` (casos/crops/simples).
- **Privacidad confirmada (05-11-2026, usuario):** el proyecto ya no se sincroniza con Google Drive; `C:\Users\usuariohgf\Desktop\Casos` ya no existe (si hay que re-redactar casos, actualizar `SRC_DIR` en `redactar_casos.py`).
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
