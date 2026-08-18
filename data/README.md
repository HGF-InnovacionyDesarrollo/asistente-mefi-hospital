# Convención de datos

## Nomenclatura

`YYYY-MM-DD_IDPaciente_HoraInicio.ext`

- `IDPaciente`: identificador interno/anonimizado (nunca nombre ni RUT del paciente).
- `HoraInicio`: hora de inicio del registro, formato `HHhMMminSSs` (tomada de la cabecera del papel).

**Nunca** usar el nombre real del paciente en un nombre de archivo, ni siquiera en archivos locales sin commitear — es PHI y queda expuesto igual que el contenido.

## Carpetas

- `raw_scans/` — imágenes/PDF crudos tal como llegan del hospital (gitignored, nunca se commitea).
- `processed_scans/` — imágenes recortadas/preprocesadas por el pipeline de digitalización (gitignored, nunca se commitea).
- `extracted/` — CSVs de series de tiempo ya digitalizadas (`tiempo, fcf, fcf_confiable, ua, ua_confiable`), formato espejo de CTU-UHB. Los derivados de CTU-UHB van en `extracted/ctu_uhb/`.
- `ctu_uhb/` — registros `.hea`/`.dat` descargados de PhysioNet (gitignored, se regeneran con `scripts/descargar_ctu_uhb.py`).
- `sample.csv` — muestra sintética de referencia, se mantiene en la raíz.

## Por qué

Un incidente ya ocurrido: nombres de pacientes reales quedaron como filename en `data/` y se commitearon a git (remediado — ver historial). La nomenclatura y separación de carpetas de este documento existen para que no vuelva a pasar.
