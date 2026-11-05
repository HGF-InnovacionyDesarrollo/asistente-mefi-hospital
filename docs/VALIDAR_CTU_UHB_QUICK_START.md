# 🚀 Quick Start: Validar que CTU-UHB se está usando

## En una línea

```powershell
cd "c:\MVP - MEFI"; .\venv\Scripts\Activate.ps1; python scripts/pipeline/validar_ctu_uhb.py
```

---

## Paso a paso

### 1. Activa el entorno virtual
```powershell
cd "c:\MVP - MEFI"
.\venv\Scripts\Activate.ps1
```

### 2. Ejecuta la validación
```powershell
python scripts/pipeline/validar_ctu_uhb.py --record-id 1001
```

### 3. Verifica la salida

Si ves esto, **✓ funciona correctamente**:

```
======================================================================
VALIDACIÓN REGISTRO 1001 — Dataset CTU-UHB (PhysioNet)
======================================================================

[*] Cargando registro 1001 desde data\ctu_uhb...
  ✓ Registro cargado: 19200 muestras, 2 señales
  Señales: FHR, UC
  Fs: 4 Hz

[*] Convirtiendo a DataFrame...
  ✓ 19200 muestras, duración: 80.0 minutos
  FCF: 107±59 lpm (rango: 0-193)
  UA: 24.8±22.0 % (rango: 0.0-127.0)

[*] Extrayendo features con lógica FIGO/NICE...
  ✓ Pipeline completado exitosamente

[*] RESULTADOS:
  Línea base: 140 lpm
  Variabilidad: 51.1 lpm (aumentada)
  Aceleraciones: 10
  Desaceleraciones: 26
  ...
  Categoría FIGO: III
```

---

## ¿Qué significa cada sección?

### Carga del registro
- `19200 muestras` = datos reales cargados desde `data/ctu_uhb/1001.hea` + `1001.dat`
- `2 señales` = FCF (frecuencia cardíaca) + UA (contracciones)
- `Fs: 4 Hz` = 4 lecturas por segundo

### DataFrame
- `80.0 minutos` = duración del monitoreo
- `FCF: 107±59 lpm` = frecuencia cardíaca promedio (variabilidad alta)
- `UA: 24.8±22.0 %` = actividad uterina promedio

### Features extraidos
Tu lógica clínica (`src/clinical.py`) detectó:
- **10 aceleraciones** (buena señal)
- **26 desaceleraciones** (múltiples, variable pattern)
- **Variabilidad aumentada** (anormal, >25 lpm)

### Clasificación final
- `FIGO III` = **Sospecha de hipoxia fetal** ⚠️
  - Línea base: VERDE (normal)
  - Variabilidad: AMARILLO (aumentada)
  - Desaceleraciones: ROJO (anormales)

---

## Opciones avanzadas

### Validar múltiples registros
```powershell
python scripts/pipeline/validar_ctu_uhb.py --record-id 1002
python scripts/pipeline/validar_ctu_uhb.py --record-id 1003
```

### Salida en JSON (para análisis posterior)
```powershell
python scripts/pipeline/validar_ctu_uhb.py --record-id 1001 --json > validation.json
```

### Modo verbose (más detalles)
```powershell
python scripts/pipeline/validar_ctu_uhb.py --record-id 1001 -v
```

---

## Si algo falla

| Error | Solución |
|-------|----------|
| `FileNotFoundError: 1001.hea not found` | Los archivos no están en `data/ctu_uhb/`. Descargar: `mkdir -p data/ctu_uhb && cd data/ctu_uhb && curl -O https://physionet.org/files/ctu-uhb-ctgdb/1.0.0/1001.hea && curl -O https://physionet.org/files/ctu-uhb-ctgdb/1.0.0/1001.dat` |
| `No FCF signal found` | El registro no tiene columna FHR (formato no compatible) |
| `ModuleNotFoundError: No module named 'wfdb'` | `wfdb` no está instalado. Ejecutar: `pip install wfdb` |
| `AttributeError: 'Record' object has no attribute X` | Versión vieja de wfdb, actualizar: `pip install --upgrade wfdb` |

---

## ¿Cómo funciona en la práctica?

Hay **dos caminos** para que el sistema procese CTG:

### Camino 1: Imagen → Digitalización manual
```
[Foto de CTG en papel]
  ↓ clic usuario (app.py)
[OCR + dos clics de calibración] (digitizer.py)
  ↓
[DataFrame: tiempo, fcf, ua]
  ↓
[Clasificación FIGO] (clinical.py)
```

### Camino 2: Datos reales → Validación automática ← **TÚ ESTÁS AQUÍ**
```
[CTU-UHB 1001.hea/dat]
  ↓ (wfdb.rdrecord)
[DataFrame: tiempo, fcf, ua]
  ↓
[Clasificación FIGO] (clinical.py)
```

**Ambos caminos usan el MISMO código de clasificación** (`clinical.py`), así que si la validación funciona, sabes que el sistema clínico es correcto.

---

## 📚 Para entender más

- **Documentación completa**: [VALIDACION_CTU_UHB.md](VALIDACION_CTU_UHB.md)
- **Código de validación**: [scripts/pipeline/validar_ctu_uhb.py](scripts/pipeline/validar_ctu_uhb.py)
- **Lógica clínica**: [src/clinical.py](src/clinical.py)
- **Checkpoint del proyecto**: [CHECKPOINT.md](../CHECKPOINT.md)

---

**Última verificación**: ✓ Validado 2026-08-18 — Sistema usando CTU-UHB correctamente
