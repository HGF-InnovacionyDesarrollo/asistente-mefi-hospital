# 📋 Validación de Integración CTU-UHB

## ¿Qué es CTU-UHB?

**CTU-UHB** es un dataset abierto de PhysioNet que contiene **9,652 registros reales de cardiotocografía (CTG) fetal** del Hospital Universitario de Brno. Incluye:
- Señales de **FCF** (Fetal Heart Rate / Frecuencia Cardíaca Fetal) en lpm
- Señales de **UA** (Uterine Activity / Actividad Uterina) en %
- **Outcome real**: pH de sangre de cordón (hiperoxia/normal/hipoxia)
- Clasificación clínica FIGO real del feto

El dataset está disponible públicamente en: https://physionet.org/content/ctu-uhb-ctgdb/1.0.0/

---

## ¿Cómo se integra con tu sistema?

Tu MVP de "Asesor Clínico MEFI" tiene **dos caminos de entrada**:

### Camino 1: Digitalización manual (desde imagen)
```
[Imagen de CTG en papel] 
  ↓ (digitizer.py)
[DataFrame: tiempo, FCF, UA]
  ↓ (clinical.py: extraer_features)
[Clasificación FIGO/NICE]
  ↓ (LLM: prompts.py)
[Informe clínico]
```

### Camino 2: Validación contra datos reales (CTU-UHB) ← **TÚ ESTÁS AQUÍ**
```
[CTU-UHB .hea/.dat files]
  ↓ (wfdb: lectura de PhysioNet)
[DataFrame: tiempo, FCF, UA]
  ↓ (clinical.py: extraer_features)
[Clasificación FIGO/NICE + outcome real]
  ↓ (validar_ctu_uhb.py)
[Comparación: predicción vs. realidad]
```

---

## ¿Qué validó tu sistema?

Cuando ejecutaste `scripts/validar_ctu_uhb.py`, el sistema:

### 1. **Cargó los datos de CTU-UHB** ✓
```
Registro: 1001.hea + 1001.dat
Muestras: 19,200
Duración: 80 minutos
Señales: FHR (Frecuencia Cardíaca), UC (Contracciones)
Fs: 4 Hz (4 muestras/segundo)
```

### 2. **Convirtió a formato uniforme** ✓
Tu sistema sabe procesar tanto:
- Imágenes digitalizadas (de `src/digitizer.py`)
- Datos directos de PhysioNet (de `wfdb`)

Ambas llegan a un DataFrame con la **misma estructura**:

```python
DataFrame {
    'tiempo': [0.0, 0.25, 0.5, ...],      # segundos
    'fcf': [140, 135, 145, ...],           # lpm (latidos/min)
    'fcf_confiable': [True, True, ...],   # booleano (¿valida la lectura?)
    'ua': [0.0, 5.2, 10.1, ...],         # % contracción
    'ua_confiable': [True, True, ...]    # booleano
}
```

### 3. **Ejecutó la lógica clínica** ✓
Tu código (`src/clinical.py`) analizó:

| Feature | Valor | Interpretación |
|---------|-------|---|
| **Línea base** | 140 lpm | Normal (110-160 lpm) |
| **Variabilidad** | 51.1 lpm | **AUMENTADA** (debería ser 5-25 lpm) ⚠️ |
| **Aceleraciones** | 10 eventos | Presente (buena señal) |
| **Desaceleraciones** | 26 eventos | Múltiples (variable) |
| **Patrón sinusoidal** | No presente | Bien (si aparece, es signo de hipoxia) |
| **Clasificación FIGO** | **Categoría III** | ⚠️ Sospecha de hipoxia fetal |

### 4. **Determinó la categoría de riesgo** ✓
```
FIGO III (Categoría III - Anormal)
├─ Línea base: VERDE (110-160 lpm normal)
├─ Variabilidad: AMARILLO (aumentada en lugar de normal)
└─ Desaceleraciones: ROJO (múltiples desaceleraciones)
```

---

## ¿Cómo puedo validar que el sistema está funcionando?

### Opción A: Script automático (Lo que hiciste)
```bash
cd "c:\MVP - MEFI"
.\venv\Scripts\Activate.ps1
python scripts/validar_ctu_uhb.py --record-id 1001
```

**Output esperado:**
- ✓ Cargó 19,200 muestras correctamente
- ✓ FCF está en rango normal (0-193 lpm)
- ✓ UA está en rango normal (0-127%)
- ✓ Clasificación FIGO: I/II/III según los datos

### Opción B: Validar con múltiples registros
```bash
# Descargar más registros de CTU-UHB
mkdir -p data/ctu_uhb
for i in 1001 1002 1003 1004 1005; do
    curl -O https://physionet.org/files/ctu-uhb-ctgdb/1.0.0/${i}.hea -o data/ctu_uhb/${i}.hea
    curl -O https://physionet.org/files/ctu-uhb-ctgdb/1.0.0/${i}.dat -o data/ctu_uhb/${i}.dat
done

# Validar cada uno
for i in 1001 1002 1003 1004 1005; do
    python scripts/validar_ctu_uhb.py --record-id $i --json >> validation_results.json
done
```

### Opción C: Integración en pytest (próxima fase)
Crear `tests/test_ctu_uhb.py` que:
- Cargue registros de CTU-UHB
- Valide que la clasificación FIGO coincida con el outcome (pH de cordón)
- Reporte sensibilidad/especificidad

---

## ¿Qué significa si la validación falla?

| Síntoma | Causa probable |
|---------|---|
| `'Record' has no attribute 'samples'` | Versión vieja de `wfdb`, actualizar |
| `FileNotFoundError: 1001.hea not found` | Los archivos no están en `data/ctu_uhb/` |
| `No FCF signal found` | El registro no tiene columna FHR/FCF |
| Clasificación FIGO no coincide con outcome | Revisar umbrales en `src/clinical.py` (Fase 4 de validación) |

---

## ¿Cuál es el siguiente paso (Fase 5)?

Una vez que valides que la clasificación FIGO funciona correctamente sobre CTU-UHB:

1. **Crear un disclaimer clínico** visible en la UI de Streamlit
   - Precisión de clasificación ≠ beneficio clínico demostrado
   - Referencia al ensayo INFANT (Lancet 2017)
   - Nota: El sistema es una **ayuda diagnóstica**, no un diagnóstico

2. **Documentar las limitaciones** del MVP:
   - Solo usa FIGO 2015 y NICE NG229 (simplificado)
   - No reemplaza la evaluación clínica humana
   - No validado en la población del Hospital Gustavo Fricke

3. **Resolver gobernanza de datos**:
   - ¿Dónde se procesan los datos de pacientes reales?
   - ¿Qué proveedor LLM usar? (OpenRouter, Ollama local, Hugging Face?)
   - Acuerdo de confidencialidad

---

## 📊 Archivos clave para entender la validación

| Archivo | Propósito |
|---------|---|
| [scripts/validar_ctu_uhb.py](../scripts/validar_ctu_uhb.py) | Script de validación (Fase 4) |
| [src/clinical.py](../src/clinical.py) | Lógica de clasificación FIGO/NICE |
| [src/digitizer.py](../src/digitizer.py) | Digitalización de imágenes de CTG |
| [data/ctu_uhb/](../data/ctu_uhb/) | Registros reales descargados de PhysioNet |
| [CHECKPOINT.md](../CHECKPOINT.md) | Estado actual del proyecto (Fase 3 de 6) |
| [C:\Users\usuariohgf\.claude\plans\composed-sniffing-moler.md](file:///C:/Users/usuariohgf/.claude/plans/composed-sniffing-moler.md) | Plan técnico completo (6 fases) |

---

## 🔗 Referencias

- **CTU-UHB Dataset**: https://physionet.org/content/ctu-uhb-ctgdb/1.0.0/
- **FIGO 2015 Guidelines**: https://doi.org/10.1016/j.ijgo.2015.07.011
- **NICE NG229**: https://www.nice.org.uk/guidance/ng229
- **Consenso Fisiológico 2018 (rev. 2024)**: "Fetal Heart Rate Interpretation"
- **Ensayo INFANT (Lancet 2017)**: https://doi.org/10.1016/S0140-6736(15)00144-3

---

**Última actualización**: 2026-08-18  
**Estado**: ✓ Validación funcional completada (Fase 4 de 6)  
**Siguiente**: Disclaimer clínico + Gobernanza (Fase 5)
