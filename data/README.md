# Convención de datos

## Nomenclatura

`YYYY-MM-DD_IDPaciente_HoraInicio.ext`

- `IDPaciente`: identificador interno/anonimizado (nunca nombre ni RUT del paciente).
  Para casos del hospital se usa el `casoNN` asignado por
  `scripts/pipeline/mapear_casos.py`.
- `HoraInicio`: hora de inicio del registro, formato `HHhMMminSSs` (tomada de la cabecera del papel).

**Nunca** usar el nombre real del paciente en un nombre de archivo, ni siquiera en archivos locales sin commitear — es PHI y queda expuesto igual que el contenido.

## Carpetas

- `extracted/` — CSVs de series de tiempo ya digitalizadas (`tiempo, fcf, fcf_confiable, ua, ua_confiable`), formato espejo de CTU-UHB.
  - `extracted/ctu_uhb/` — los 552 registros de CTU-UHB convertidos a CSV (se regeneran con `scripts/pipeline/create_csv_database.py`).
  - `extracted/comparaciones/` — extracciones A/B del mismo caso con distinta fuente (ej. `2026-06-24_caso01_07h27min47s_jpg.csv` = extracción desde JPG vs. la versión canónica desde PDF).
  - `extracted/patrones_referencia/` — casos clínicos de patrón particular conservados como referencia (sinusal, PTVE).
- `ctu_uhb/` — registros `.hea`/`.dat` descargados de PhysioNet (gitignored, se regeneran con `scripts/pipeline/descargar_ctu_uhb.py`).

Los escaneos originales del hospital NO viven aquí: están en `../casos_hospital/`
(gitignored, nombres anonimizados) y su mapeo nombre-real↔casoNN fuera del
proyecto en `C:\MEFI-privado\mapeo_casos.csv`.

## Inventario de casos extraídos

| CSV | Caso | Fuente | Estado |
|---|---|---|---|
| `2025-06-26_CCI.csv` | (prueba jun-2025) | `caso05` (CCI26062025.pdf) | válido |
| `2025-06-26_MEFI1.csv` | (prueba jun-2025) | `caso06` (MEFI126062025.pdf) | válido |
| `2026-06-06_caso02_02h21min59s.csv` | caso02 | escaneo 2026-06-06 02:21:59 | válido |
| `2026-06-24_caso01_07h27min47s.csv` | caso01 | par PDF/JPG digitalizado | válido (canónico) |
| `2026-06-24_caso01_07h27min47s_jpg.csv` | caso01 | mismo caso, desde JPG | comparación A/B |
| `2026-08-18_caso03.csv` | caso03 | escaneo origen no identificado | válido |
| `2026-08-18_caso04.csv` | caso04 | — | **eliminado 2026-11-05** (calibración rota, FCF negativo) |
| `2026-10-16_extraido_calibracion_semi_auto.csv` | sin identificar | prueba calibración semi-auto (16-oct) | válido |

Casos `caso03`/`caso04` quedan reservados hasta identificar su escaneo original
(ver `casos_hospital/README.md`).

## Por qué

Un incidente ya ocurrido: nombres de pacientes reales quedaron como filename en `data/` y se commitearon a git (remediado — ver historial). La nomenclatura y separación de carpetas de este documento existen para que no vuelva a pasar.
