# scripts/

Herramientas del proyecto, separadas por responsabilidad. Ninguna corre como
parte de la app; se invocan a mano según se necesite.

## pipeline/ — datos y validación (código vivo del proyecto)

| Script | Qué hace |
|---|---|
| `mapear_casos.py` | Renombra escaneos del hospital al estándar anónimo `YYYY-MM-DD_casoNN_Hora.ext`; escribe el mapeo PHI fuera del proyecto (`C:\MEFI-privado\`). `--dry-run` primero, `--apply` después. |
| `redactar_casos.py` | Genera `fixtures/casos_redactados/` tapando ID/Nombre/RUT de los originales. Lee de una carpeta fuera del repo (`SRC_DIR` dentro del script). |
| `descargar_ctu_uhb.py` | Descarga registros `.hea/.dat` de CTU-UHB (PhysioNet) a `data/ctu_uhb/`. |
| `create_csv_database.py` | Convierte `data/ctu_uhb/` a CSVs espejo en `data/extracted/ctu_uhb/` + outcomes. |
| `validar_ctu_uhb.py` | Validación de la clasificación FIGO/NICE contra el outcome real (pH de cordón). `--all` para los 552 registros. |
| `build_portable.py` | Construye `dist/MEFI-portable/` (Fase 1): Python embebido + dependencias + app; insumos del instalador InnoSetup. |

## analisis/ — estudios que respaldan decisiones (históricos, no del flujo diario)

| Script | Qué hace |
|---|---|
| `prototipo_contracciones.py` | Detector de contracciones v2 validado antes de integrarlo a `clinical.py` (oct 2026). |
| `analizar_falsos_positivos.py` | Diagnóstico de qué criterio dispara cada FP/FN del batch CTU-UHB. |
| `generar_figuras_sota.py` | Regenera las figuras de `docs/ESTADO_DELARTE_2026.md`. |

## utilidades/ — herramientas de equipo y pruebas de humo

| Script | Qué hace |
|---|---|
| `prueba_llm_local.py` | Smoke test del prompt real con Ollama local (requiere `ollama serve`). |
| `test_conexion.py` | Prueba manual de conexión a OpenRouter (no es test de pytest: ejecuta código al importarse). |
| `verificar_modelos.py` | Lista los modelos disponibles en la cuenta configurada. |
| `crear_acceso_directo.ps1` | Crea el acceso directo de escritorio a `MEFI.bat`. |
| `generar_guia_docx.py` | Vuelca `docs/GUIA_PROFESIONALES.md` a `GUIA_PROFESIONALES.docx` (Word) en la raíz. Correrlo tras editar la guía. |
