# Guía general — Asesor Clínico MEFI

**Proyecto:** Asesor Clínico de Monitoreo Fetal (MEFI) — Hospital Dr. Gustavo Fricke
**Audiencia:** cualquier profesional del hospital (clínica, innovación, tecnologías de la información, gestión). No se asume conocimiento técnico.
**Última actualización:** noviembre de 2026

---

## 1. ¿Qué es este sistema?

Una herramienta de **apoyo a la interpretación de cardiotocografías** (los monitoreos fetales, CTG) que se imprimen en papel. La persona usuaria toma una foto o escaneo del papel, y el sistema:

1. **Digitaliza** el trazado (frecuencia cardíaca fetal y actividad uterina) convirtiéndolo en datos numéricos.
2. **Analiza** esos datos con reglas clínicas publicadas internacionalmente (FIGO 2015 y NICE NG229).
3. **Redacta un informe** en lenguaje clínico, usando un modelo de lenguaje (IA) que trabaja **solo sobre los datos ya calculados** — ninguna IA "ve" la imagen ni el trazado crudo.

**Lo que el sistema NO es:** no diagnostica, no decide tratamientos y no reemplaza el juicio clínico. Es un segundo par de ojos que ordena y cuantifica lo que el papel muestra. En la interfaz se muestra siempre un aviso (disclaimer) al respecto, con referencia al ensayo clínico INFANT (Lancet, 2017).

## 2. ¿Por qué existe? Objetivos del proyecto

- **Problema:** muchos monitoreos del hospital quedan solo en papel; interpretarlos a ojo es variable entre observadores y no deja datos reutilizables.
- **Objetivo general:** apoyar a las personas clínicas con una lectura sistemática, cuantificada y redactada de cada monitoreo.
- **Objetivos específicos:**
  - Convertir papel en datos de calidad auditables (la persona ve qué tramos fueron reconstruidos).
  - Aplicar las mismas reglas internacionales a todos los casos, sin variabilidad.
  - Mantener los datos de pacientes dentro del equipo (ver sección 6).
  - Validar el sistema contra evidencia publicada antes de cualquier uso clínico real.

## 3. Cómo funciona, en palabras simples

```
[Foto o PDF del papel]
        │  (digitalización: orienta, detecta paneles, calibra con 2 puntos por panel)
        ▼
[Serie de tiempo: frecuencia fetal y contracciones, segundo a segundo]
        │  (reglas explícitas FIGO 2015 / NICE NG229 — sin aprendizaje automático)
        ▼
[Clasificación: categoría FIGO + semáforo de variables + conteo de contracciones]
        │  (redacción del informe; la IA solo recibe texto estructurado)
        ▼
[Informe clínico en español]
```

Diseño deliberado relevante para la confianza clínica: **la IA nunca interpreta la imagen**. Las reglas médicas viven en código abierto y verificable (`src/clinical.py`); la IA solo redacta el informe a partir de un resumen estructurado de esas reglas.

## 4. Cómo se usa (paso a paso)

### 4.1 Requisitos

- Computador del hospital con Windows.
- Primera vez solo: doble clic en **`MEFI.bat`** (en la carpeta del proyecto). El script instala lo necesario de forma automática y abre el navegador en la dirección del sistema. En adelante, ese mismo acceso directo basta.
- En un computador nuevo puede hacer falta instalar el motor de lectura de texto (OCR) Tesseract: `winget install --id UB-Mannheim.TesseractOCR -e`.

### 4.2 Analizar un monitoreo

1. **Abrir** la aplicación (doble clic en `MEFI.bat` o en el acceso directo "MEFI - Asesor Clínico").
2. **Subir** la foto o el PDF del trazado. El sistema orienta la imagen y detecta automáticamente los dos paneles (frecuencia fetal arriba, actividad uterina abajo).
3. **Revisar los metadatos** que el sistema leyó de la cabecera (identificador interno, fecha/hora de inicio, velocidad de papel). Son lectura automática de "mejor esfuerzo": corregirlos si no cuadran con el papel.
4. **Calibrar** cada panel marcando dos puntos de referencia con valores conocidos (por ejemplo, 210 y 30 lpm en el panel fetal; 100 y 0 en el panel uterino). El sistema puede pre-marcarlos automáticamente, pero **la confirmación humana es obligatoria**.
5. Clic en **"Digitalizar trazado"**. Se muestra la curva extraída sobre la imagen: en celeste lo leído directamente, en naranja lo reconstruido por interpolación. Cada archivo queda guardado con nombre anónimo en `data/extracted/`.
6. **Revisar la clasificación**: categoría FIGO, semáforo por variable (línea base, variabilidad, aceleraciones, desaceleraciones, contracciones) y, si aplica, alerta de tachisistolia.
7. Clic en **"Generar informe clínico con LLM"** para obtener el texto del informe.

### 4.3 Configuración del modelo de redacción (barra lateral)

Se puede elegir entre proveedores locales (Ollama, dentro del equipo) o en la nube (OpenRouter, Hugging Face) y el modelo concreto. **Regla vigente mientras no se apruebe la gobernanza de datos: con datos reales de pacientes usar solo el proveedor local.** Los proveedores en la nube quedan para pruebas con datos sintéticos o anonimizados.

## 5. Qué tan confiable es: resultados y límites

Validado contra **CTU-UHB**, la base de datos abierta internacional de referencia (552 registros reales con pH de sangre de cordón como verdad de fondo, Hospital Universitario de Brno, PhysioNet):

| Medida | Valor | Qué significa en la práctica |
|---|---|---|
| Sensibilidad | **95,0 %** | Detecta 19 de cada 20 hipoxias reales. |
| Especificidad | **11,1 %** | De cada 10 alertas, ~9 son falsas alarmas. |
| Valor predictivo negativo | **96,6 %** | Si el sistema dice "normal", casi siempre lo es. |

**Cómo leer esto clínicamente:** el sistema está deliberadamente calibrado para **no pasar por alto hipoxias reales**, a costa de sobre-alertar. No sirve para *descartar* problemas (su valor está en detectar y cuantificar), y ninguna alerta debe tomarse como diagnóstico. La literatura internacional muestra que **ningún método automatizado de CTG —ni reglas ni aprendizaje profundo— supera un AUC ~0,75** prediciendo acidemia fetal sobre esta base de datos: la baja especificidad es una propiedad conocida del problema clínico, no un defecto de implementación (análisis completo en `docs/ESTADO_DELARTE_2026.md`).

## 6. Privacidad y datos de pacientes

- **Nada sale del equipo:** ni imágenes, ni trazados, ni nombres se envían a servicios externos. La excepción potencial es la redacción del informe con proveedores en la nube, **vedada con datos reales** hasta que el hospital apruebe formalmente esa gobernanza (ver `ROADMAP.md`, Fase 2).
- **Nomenclatura sin identidad:** los archivos se nombran solo con fecha, código interno anónimo (casoNN) y hora (`YYYY-MM-DD_casoNN_Hora`). La tabla que relaciona códigos con nombres reales vive **fuera del proyecto**, en el equipo del equipo clínico (`C:\MEFI-privado\`), jamás en el repositorio ni en la nube.
- **Acceso a los originales:** los escaneos originales (`casos_hospital/`) y las imágenes redactadas (`fixtures/`) están excluidos del control de versiones y del uso cotidiano del sistema.
- Los datos de validación externos (CTU-UHB) son públicos y anonimizados desde su origen.

## 7. Dónde está cada cosa (orientación general)

```
C:\MVP - MEFI\
├── MEFI.bat               ← doble clic para abrir el sistema
├── CLAUDE.md              ← contexto técnico para personas que desarrollan
├── CHECKPOINT.md          ← bitácora de decisiones del proyecto
├── ROADMAP.md             ← plan de trabajo y próximas fases
├── docs/
│   ├── GUIA_PROFESIONALES.md  ← este documento
│   ├── ESTADO_DELARTE_2026.md ← evidencia científica revisada
│   └── VALIDACION_CTU_UHB.md  ← detalle de la validación
├── src/                   ← código del sistema (app, reglas clínicas, digitalización)
├── scripts/               ← herramientas auxiliares (ver scripts/README.md)
├── data/                  ← datos numéricos extraídos y base de validación
├── fixtures/              ← imágenes de prueba redactadas
└── casos_hospital/        ← escaneos originales (acceso restringido, anonimizados por nombre)
```

## 8. Glosario

| Término | Significado |
|---|---|
| **CTG / MEFI** | Cardiotocografía / monitoreo fetal electrónico: registro de frecuencia cardíaca fetal y contracciones uterinas. |
| **FCF** | Frecuencia cardíaca fetal (latidos por minuto). |
| **UA / TOCO** | Actividad uterina (contracciones), registrada por tocografía. |
| **FIGO 2015** | Guía internacional de interpretación de CTG de la Federación Internacional de Ginecología y Obstetricia. |
| **NICE NG229** | Guía del instituto nacional de salud de Reino Unido; aporta criterios como la tachisistolia (≥5 contracciones/10 min). |
| **CTU-UHB** | Base de datos abierta de 9.652 registros CTG reales (PhysioNet), estándar mundial para validar sistemas como este. |
| **LLM** | Modelo de lenguaje (IA generativa); aquí se usa únicamente para redactar el informe sobre datos ya calculados. |
| **pH de cordón** | Acidez de la sangre del cordón al nacer; es la verdad de fondo usada para validar (pH < 7,05 = hipoxia). |
| **Sensibilidad / especificidad** | Capacidad de detectar los casos reales / capacidad de no alarmar en casos sanos. |

## 9. Preguntas frecuentes

**¿Puedo confiar en el informe que genera?**
Es un apoyo, no un diagnóstico. Las reglas de clasificación están validadas y son de código abierto; la redacción con IA debe releerse siempre. La clasificación FIGO y el semáforo son los elementos verificables.

**¿Qué pasa con los monitoreos que el sistema no logra leer?**
La calibración es humana y la curva se muestra con sus tramos reconstruidos en naranja. Si la imagen es ilegible, la persona usuaria lo verá en el paso de auditoría antes de cualquier informe.

**¿Puedo usarlo desde otro computador del hospital?**
Hoy el sistema corre en este equipo. La Fase 1 del plan (ver `ROADMAP.md`) es justamente empaquetarlo como instalador para desplegarlo en otros equipos.

**¿Quién mantiene el proyecto y dónde están las decisiones técnicas?**
En `CHECKPOINT.md` está la bitácora completa de decisiones con fechas; `ROADMAP.md` muestra el plan; `CLAUDE.md` resume el estado técnico para quienes desarrollen.

---

*Documento elaborado por el equipo de desarrollo del proyecto. Para sugerencias de mejora de esta guía, contactar al equipo de innovación.*
