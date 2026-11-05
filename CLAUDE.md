# CLAUDE.md — MVP MEFI (Asesor Clínico de Monitoreo Fetal)

> Contexto de orientación. El **historial detallado de decisiones vive en
> [CHECKPOINT.md](CHECKPOINT.md)** — léelo antes de tocar `src/clinical.py`,
> `src/digitizer.py` o los umbrales FIGO. El plan vivo de pendientes está en
> [ROADMAP.md](ROADMAP.md). Este archivo no los duplica.
>
> ⚠️ `CHECKPOINT.md` manda a leer
> `C:\Users\usuariohgf\.claude\plans\composed-sniffing-moler.md` antes de
> tocar código. **Ese archivo ya no existe** (verificado 14-09-2026). No lo
> busques: `CHECKPOINT.md` es hoy la única fuente del porqué de cada decisión.

## 1. Qué es

Herramienta de apoyo a la interpretación de cardiotocografía (CTG/MEFI) para
el Hospital Gustavo Fricke. Recibe una **foto o escaneo del papel impreso**,
lo digitaliza a serie de tiempo, calcula features clínicas con reglas
explícitas (FIGO 2015 / NICE NG229) y redacta un informe con un LLM.

Punto clave de diseño: **ningún LLM ve la imagen ni la señal.** Desde la
Fase 3, `clinical.py` produce un dict de features y el LLM solo redacta a
partir de ese texto estructurado. Si vuelves a mandar imágenes a un modelo,
estás revirtiendo una decisión deliberada.

Es **apoyo a decisión, no diagnóstico** — hay disclaimer en la UI con la
referencia al ensayo INFANT (Lancet 2017).

## 2. Reglas duras — datos de pacientes

- `casos_hospital/` contiene **81 escaneos originales del hospital** (JPG/PDF
  de tiras impresas) con `ID:` y `Nombre:` visibles en la cabecera de cada
  segmento de la tira. **No están anonimizados por dentro** — solo los
  nombres de archivo lo están (`YYYY-MM-DD_casoNN_Hora.ext`, asignado por
  `scripts/pipeline/mapear_casos.py` el 05-11-2026).
- El mapeo nombre-real ↔ casoNN vive **fuera del proyecto** en
  `C:\MEFI-privado\mapeo_casos.csv`. Contiene PHI: nunca lo muevas al repo
  ni a una carpeta sincronizada a la nube.
- Trabaja siempre desde `fixtures/casos_redactados/` (53 PNG ya redactados por
  `scripts/pipeline/redactar_casos.py`), nunca desde los originales.
- **Nada de esto sale del equipo**: ni a OpenRouter, ni a Hugging Face, ni a
  artefactos publicados, ni a la web. La gobernanza de datos con OpenRouter
  **sigue sin resolverse formalmente**; hasta que el usuario lo confirme, con
  datos reales solo Ollama local o fixtures sintéticas.
- `casos_hospital/`, `fixtures/`, `data/ctu_uhb/` y `data/extracted/` están
  en `.gitignore`. Revisa el `.gitignore` antes de agregar cualquier carpeta
  de datos nueva.
- **Nunca pongas un nombre de paciente en un nombre de archivo**, un mensaje
  de commit ni una regla de permisos. Ya pasó dos veces y hubo que reescribir
  historial de git para limpiarlo (ver CHECKPOINT §0 y §1.1).
- Estándar de nombres: `YYYY-MM-DD_IDPaciente_HoraInicio` (ver `data/README.md`).
- ⚠️ `redactar_casos.py` lee de `C:\Users\usuariohgf\Desktop\Casos` (fuera del
  repo). Verificar (Fase 0, pendiente de confirmación del usuario) que esa
  carpeta del Escritorio tampoco se sincronice a Drive/OneDrive.

## 3. Entorno

- `venv/` con **Python 3.14.5**. Invocar como `./venv/Scripts/python.exe`.
- Correr la app: `PYTHONIOENCODING=utf-8 streamlit run src/app.py`. Para usuarios
  no técnicos existe `MEFI.bat` en la raíz (doble clic: crea venv si falta,
  instala dependencias la primera vez —marcador `venv\.listo`—, abre el
  navegador en :8501 y lanza streamlit).
- Tests: `./venv/Scripts/python.exe -m pytest tests/ -q` (25/25 en verde hoy).
- `pytesseract` necesita `tesseract_cmd` apuntado a mano — no está en el PATH.
  En otra máquina: `winget install --id UB-Mannheim.TesseractOCR -e`.
- Secretos en `.env` y `.streamlit/secrets.toml`, ambos gitignored. Nunca en
  código (ya hubo una API key filtrada y rotada).

## 4. Mapa de módulos

| Archivo | Responsabilidad |
|---|---|
| `src/digitizer.py` | Imagen → serie de tiempo. Orientación, detección de paneles, calibración por 2 clics, huecos auditables. También OCR de cabecera y de anotaciones a mano (100% local). |
| `src/clinical.py` | Reglas clínicas. Línea base, variabilidad, aceleraciones, desaceleraciones (precoz/tardía/variable), patrón sinusoidal, `clasificar_figo()`. Entrada única: `extraer_features(df)`. |
| `src/prompts.py` | Importa los umbrales **directo de `clinical.py`** para que no se desincronicen. |
| `src/llm_client.py` + `config.yaml` | Proveedor LLM 100% configurable por datos (Ollama / OpenRouter / Hugging Face). Agregar proveedor = agregar bloque en el YAML, sin tocar código. |
| `src/app.py` | UI Streamlit. Exporta extracciones como `YYYY-MM-DD_<id-caso>_extraido.csv` (ID editable + fecha OCR; nunca el nombre del archivo subido). |

Scripts organizados en `scripts/pipeline/` (datos y validación: `validar_ctu_uhb`,
`descargar_ctu_uhb`, `create_csv_database`, `redactar_casos`, `mapear_casos`),
`scripts/analisis/` (estudios históricos) y `scripts/utilidades/` (smoke tests
y herramientas de equipo). Detalle de cada uno en `scripts/README.md`.

## 5. Estado y el problema abierto

Fases 1-4 completas, Fase 5 (disclaimer) parcial. Validación contra CTU-UHB:
**sensibilidad 95%, especificidad ~11%** (oct 2026; era 12.3% con el detector de
UA viejo, ver CHECKPOINT §-2). La especificidad baja **ya no es un problema a
resolver**: la investigación de estado del arte
([docs/ESTADO_DELARTE_2026.md](docs/ESTADO_DELARTE_2026.md))
confirmó que el techo AUC sobre CTU-UHB para todo método publicado es 0.68-0.75
y que FIGO es por diseño un indicador de alta sensibilidad / bajo PPV. Mejorarla
de verdad requeriría un score continuo de riesgo entrenado (propuesta futura,
tipo DeepCTG — ROADMAP Fase 3), no más ajustes de reglas.

Esa especificidad baja **ya no es un bug** — se persiguió a fondo el 26-ago. Se
intentó reemplazar el proxy de "desaceleraciones repetitivas" (3+ en 20 min) por
la definición real de FIGO (>50% de las contracciones): la especificidad subió a
78,9% pero **la sensibilidad cayó a 67,5%**, porque el detector de picos de UA no
es confiable sobre señal ruidosa. Se revirtió a propósito: en una herramienta de
apoyo clínico, perder hipoxias reales es mucho peor que sobre-alertar.

**No vuelvas a "arreglar" la especificidad ajustando umbrales sobre el mismo
detector de UA.** Requiere una detección de contracciones genuinamente mejor.

Pendientes declarados y priorizados: [ROADMAP.md](ROADMAP.md) (Fase 1:
empaquetado instalable, es la siguiente).

## 6. Reglas para el agente

- Antes de cambiar un umbral clínico: corre `pytest` **y** el batch de 552
  (`scripts/pipeline/validar_ctu_uhb.py --all`), y reporta sensibilidad/especificidad
  antes y después. Un cambio que sube especificidad bajando sensibilidad no es
  una mejora.
- La FCF fuera de 50-220 lpm es dropout del sensor, no dato. Filtrar siempre
  (`fcf_confiable`).
- Si cierras un bloque de trabajo, actualiza `CHECKPOINT.md` (bitácora) y
  `ROADMAP.md` (estado de tareas) — son el mecanismo de traspaso de este proyecto.
