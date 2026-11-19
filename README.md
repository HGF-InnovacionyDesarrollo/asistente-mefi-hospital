# Asesor Clínico MEFI v2.0 — Hospital Dr. Gustavo Fricke

Herramienta de apoyo a la decisión clínica para la interpretación de **cardiotocografía intraparto (CTG / MEFI)** desarrollada para la **Unidad de Parto Integral (SAIP)** junto a la **Unidad de Innovación y Desarrollo** del Hospital Dr. Gustavo Fricke.

- **Base normativa integrada (v2.0):**
  - **Protocolo de Vigilancia del Bienestar Fetal Intraparto V2** (Hospital Dr. Gustavo Fricke, septiembre 2025).
  - **ACOG Clinical Practice Guideline No. 10**, *Intrapartum Fetal Heart Rate Monitoring: Interpretation and Management* (*Obstet Gynecol* 2025;146:583–599).
  - **FIGO 2015** y **NICE NG229**.
- **Arquitectura de privacidad y precisión:** ningún modelo de lenguaje (LLM) recibe la imagen del monitoreo ni datos filiatorios (PHI). La visión clásica ([`src/digitizer.py`](src/digitizer.py)) extrae las series de tiempo FCF/UA, el motor determinístico ([`src/clinical.py`](src/clinical.py)) calcula y clasifica las variables clínicas (validado contra 552 registros de PhysioNet CTU-UHB con **sensibilidad 95,0 %** y **VPN 96,6 %**), y se generan en paralelo el **Informe Determinístico por Plantilla**, el **Informe IA** y el **Reporte Consolidado en PDF** ([`src/reporte_pdf.py`](src/reporte_pdf.py)).

---

## Mapa del Proyecto (Estructura Organizada)

```text
C:\MVP - MEFI\
├── MEFI.bat                          # Lanzador directo en Windows (doble clic)
├── config.yaml                       # Configuración de proveedores y modelos LLM
├── requirements.txt                  # Dependencias Python del proyecto
├── GUIA_PROFESIONALES.docx           # Guía rápida para profesionales (incluida en el instalador)
├── CLAUDE.md                         # Contexto arquitectónico y reglas duras del proyecto
├── CHECKPOINT.md                     # Bitácora histórica de decisiones técnicas y clínicas
├── ROADMAP.md                        # Estado de fases y hoja de ruta
│
├── src/                              # Código fuente de la aplicación (8 módulos en producción)
│   ├── app.py                        # Interfaz interactiva Streamlit (3 etapas guiadas)
│   ├── clinical.py                   # Motor determinístico puro (FIGO / NICE / ACOG / Protocolo V2)
│   ├── digitizer.py                  # Digitalización por visión clásica de papel CTG (FCF y UA)
│   ├── prompts.py                    # Plantilla determinística, prompts versionados y concordancia
│   ├── reporte_pdf.py                # Generador del Reporte Clínico Consolidado en PDF (A4)
│   ├── ux_helpers.py                 # Validadores de seguridad de calibración, tablas y demo sintético
│   ├── llm_client.py                 # Cliente unificado para proveedores LLM (Ollama / OpenRouter / HF)
│   ├── rutas.py                      # Resolución portable de rutas (desarrollo vs. instalado en %LOCALAPPDATA%)
│   └── componente_calibrador/        # Componente HTML/JS de líneas Azul/Roja arrastrables con el mouse
│
├── tests/                            # Batería de pruebas unitarias automatizadas (pytest: 50 tests)
│   └── test_clinical.py              # Pruebas determinísticas de FCF, UA, Fases A/B/C v2.0, UX y PDF
│
├── docs/                             # Documentación técnica, validación científica y manuales
│   ├── VALIDACION_CTU_UHB.md         # Resultados sobre 552 registros reales CTU-UHB (antes y después Fase B)
│   ├── MATRIZ_CONCILIACION_MEFI_v2.0.md # Matriz de conciliación Protocolo V2 + ACOG CPG No. 10 (Cap. 7)
│   ├── ESTADO_DELARTE_2026.md        # Revisión de literatura internacional y techo AUROC en CTG
│   ├── GOBERNANZA_DATOS_LLM.md       # Gobernanza de datos y privacidad frente a proveedores LLM
│   ├── GUIA_PROFESIONALES.md         # Fuente Markdown de la guía para profesionales clínicos
│   ├── DISENO_SCORE_CONTINUO_DEEPCTG.md # Diseño Fase D1: score continuo de riesgo (5 niveles)
│   ├── DISENO_LINEA_TIEMPO_PARTO.md  # Diseño Fase D2: línea de tiempo longitudinal de evaluaciones
│   ├── figs/                         # Curvas ROC y gráficos de validación científica
│   └── manuales/                     # Documentos Word ejecutivos y manuales de usuario
│       ├── EXPLICACION_EJECUTIVA_MEFI.docx
│       ├── MANUAL_PRACTICO_USO_MEFI.docx
│       └── PROPUESTA_ACTUALIZACION_MEFI_v2.0.docx
│
├── scripts/                          # Herramientas de validación, empaquetado y análisis
│   ├── README.md                     # Índice detallado de scripts
│   ├── pipeline/                     # validar_ctu_uhb.py, build_portable.py, prototipo_score_continuo_ctu_uhb.py
│   ├── analisis/                     # Estudios de contracciones, falsos positivos y figuras SOTA
│   └── utilidades/                   # Generación de guía Word, acceso directo y pruebas de conexión
│
├── installer/                        # Configuración del instalador de Windows
│   └── mefi.iss                      # Script Inno Setup que genera dist/MEFI-Setup.exe
│
├── data/                             # Datos de validación (gitignored para proteger privacidad)
│   └── README.md                     # Convención de nombres anonimizados e inventario
│
└── dist/                             # Salida compilada (gitignored)
    ├── MEFI-Setup.exe                # Instalador autocontenido para PCs del hospital
    └── MEFI-portable/                # Paquete portable con Python embebido
```

---

## Comandos Frecuentes

- **Iniciar la aplicación:** doble clic en [`MEFI.bat`](MEFI.bat) o:
  ```powershell
  .\venv\Scripts\streamlit.exe run src\app.py
  ```
- **Correr la batería de pruebas unitarias (50 tests):**
  ```powershell
  .\venv\Scripts\python.exe -m pytest tests/ -q
  ```
- **Validar contra los 552 registros de CTU-UHB (PhysioNet):**
  ```powershell
  .\venv\Scripts\python.exe scripts/pipeline/validar_ctu_uhb.py --all
  ```
- **Actualizar el paquete portable y compilar el instalador `MEFI-Setup.exe`:**
  ```powershell
  .\venv\Scripts\python.exe scripts/pipeline/build_portable.py --only-app
  & "C:\Users\usuariohgf\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer\mefi.iss
  ```
