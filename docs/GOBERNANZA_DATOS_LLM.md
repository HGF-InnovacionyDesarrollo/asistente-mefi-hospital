# Política de Gobernanza de Datos y Uso de Modelos de Lenguaje (LLM)
## Asesor Clínico MEFI — Hospital Dr. Gustavo Fricke

**Versión:** 1.0  
**Fecha:** Noviembre de 2026  
**Ámbito de aplicación:** Proyecto Asesor Clínico de Monitoreo Fetal Intraparto (MEFI), Servicio de Obstetricia y Ginecología / Comité de Innovación e Informática Médica.

---

## 1. Propósito y Alcance

Este documento establece los principios, salvaguardas técnicas y directrices normativas para el tratamiento de información clínica y el uso de modelos de inteligencia artificial (LLM) dentro del sistema **Asesor Clínico MEFI**. 

Su objetivo es garantizar el cumplimiento irrestricto de la legislación chilena sobre protección de datos y confidencialidad médica, resguardando la privacidad del paciente y la seguridad de la información institucional del Hospital Dr. Gustavo Fricke y del Servicio de Salud Viña del Mar Quillota (SSVQ).

---

## 2. Marco Normativo Aplicable

1. **Ley N° 20.584**: Regula los derechos y deberes que tienen las personas en relación con acciones vinculadas a su atención en salud (en particular, reserva y custodia de la ficha clínica, artículos 12 y 13).
2. **Ley N° 19.628**: Sobre Protección de la Vida Privada y tratamiento de datos de carácter personal (clasificación de datos de salud como *datos sensibles*).
3. **Estándares de Seguridad de la Información del Ministerio de Salud (MINSAL)**: Normas técnicas sobre interoperabilidad, confidencialidad y preservación digital de registros clínicos.

---

## 3. Arquitectura de Privacidad por Diseño (Privacy by Design)

El sistema MEFI implementa un aislamiento deliberado entre la imagen del examen, los datos fisiológicos y los modelos de lenguaje:

```
[Foto / PDF de la tira de papel]
           │
           ▼ (Procesamiento 100% LOCAL en el PC)
 [OCR local Tesseract] ──► Cabecera con Nombre/RUT/Ficha ──► SE AISLA (No sale del PC)
           │
           ▼ (Visión por computador clásica: digitizer.py)
 [Series temporales numéricas FCF/UA] ──► data/extracted/ (Nombre anonimizado)
           │
           ▼ (Reglas determinísticas FIGO 2015 / NICE NG229: clinical.py)
 [Métricas clínicas estructuradas]
           ├────────────────────────────┐
           ▼ (Plantilla determinística)  ▼ (Inferencia LLM - Solo texto estructurado)
  [Informe por Protocolo]       [Informe Asistido por IA]
     (100% Fuera de línea)           (Local Ollama o Nube Autorizada)
```

### Regla de Oro del Sistema
> **Ningún modelo de lenguaje (LLM), ni local ni en la nube, "ve" la fotografía del trazado, ni la cabecera original del papel, ni las series de tiempo segundo a segundo.**  
> El modelo únicamente recibe un resumen textual con las variables ya computadas y clasificadas por reglas matemáticas determinísticas.

---

## 4. Clasificación y Flujo de los Datos

| Nivel de Información | Contenido | Tratamiento Técnico | ¿Puede salir del PC? |
|---|---|---|:---:|
| **Nivel 1: Datos de Identificación Directa (PHI)** | Nombre del paciente, RUN/RUT, número de ficha clínica o cama impresos en el papel térmico. | Se extraen por OCR local para verificación inmediata de la usuaria. Al guardar registros, se reemplazan obligatoriamente por identificadores anónimos (`YYYY-MM-DD_casoNN_Hora`). | **NUNCA** |
| **Nivel 2: Señales Fisiológicas Crudas** | Trazado gráfico, imagen del escaneo, series temporales continuas (muestras FCF/UA cada 0.25 s). | Se almacenan en el disco local (`%LOCALAPPDATA%\MEFI\data\extracted`) para auditoría y curvas. | **NUNCA** |
| **Nivel 3: Métricas Clínicas Agregadas** | Frecuencia basal (ej. 140 lpm), variabilidad (ej. 12 lpm), conteo de aceleraciones/desaceleraciones, categoría FIGO (I, II o III) y semáforo NICE. | Texto estructurado generado por `src/clinical.py` y `src/prompts.py`. No contiene datos de identidad ni patrones biométricos directos. | **Solo bajo canal autorizado** (ver Sección 5) |

---

## 5. Matriz de Uso de Proveedores LLM

El sistema permite configurar diferentes motores de redacción en [`config.yaml`](file:///c:/MVP%20-%20MEFI/config.yaml). Su autorización operativa se rige por la siguiente matriz:

### 5.1 Proveedor Local (Ollama — Servidor Hospital / PC de Trabajo)
* **Infraestructura:** Motor de inferencia ejecutado en la GPU/CPU del propio computador o en un servidor dedicado de la red intranet hospitalaria (sin salida a internet).
* **Modelos:** Llama-3, Qwen-2.5, Phi-3 o equivalentes de código abierto.
* **Estado de Autorización:** **AUTORIZADO PARA USO CLÍNICO INSTITUCIONAL.**
* **Justificación:** Los datos jamás abandonan el perímetro de la red institucional; no hay terceros intermediarios ni almacenamiento externo.

### 5.2 Proveedor en la Nube (OpenRouter / APIs Comerciales)
* **Infraestructura:** Servicios en la nube mediante API cifrada (HTTPS/TLS 1.3).
* **Modelos:** Google Gemma, Anthropic Claude, Meta Llama Cloud, entre otros.
* **Salvaguardas actuales:**
  1. No se envía nombre, RUT ni identificador del paciente (campos omitidos en el prompt).
  2. No se envía imagen ni gráfico del monitoreo.
  3. Las claves de API se almacenan de manera local y cifrada en el perfil de usuario (`%LOCALAPPDATA%\MEFI\.env`), excluidas del repositorio Git.
* **Estado de Autorización:** **RESTRINGIDO A FASE PILOTO / SIMULACIÓN / CAPACITACIÓN.**  
  *Su despliegue formal en atención asistencial directa queda condicionado a la suscripción de un acuerdo de procesamiento de datos o verificación de política de retención cero (*Zero Data Retention*) formalizada con el proveedor.*

### 5.3 Informe por Plantilla (Sin IA)
* **Infraestructura:** Código Python puro basado en la biblioteca estándar y reglas FIGO/NICE.
* **Estado de Autorización:** **PLENAMENTE VIGENTE Y AUTÓNOMO.**  
  *Constituye el estándar base del sistema y no requiere conectividad externa de ningún tipo.*

---

## 6. Procedimientos Operativos para el Personal Clínico

1. **Revisión del Informe por Plantilla como Fuente Primaria:** El personal debe basar su revisión en las variables cuantitativas y la clasificación FIGO generadas por la plantilla protocolizada.
2. **Rol del Informe LLM:** Todo texto generado por IA generativa debe entenderse estrictamente como una sugerencia de redacción y correlación docente-asistencial, requiriendo validación y firma humana responsable.
3. **Custodia de Llaves y Accesos:** Queda prohibido compartir o extraer el archivo `.env` fuera del entorno de instalación autorizado por el hospital.
4. **Mapeo de Casos de Investigación:** Cualquier proyecto de validación retrospectiva debe mantener la tabla de equivalencia (Nombre Real ↔ Código Caso) en soporte externo aislado (`C:\MEFI-privado\`) bajo custodia exclusiva del equipo investigador principal.

---

## 7. Plan de Auditoría y Mejora Continua

* **Auditoría de Tráfico:** Se realizarán inspecciones periódicas de los payloads enviados por `llm_client.py` para asegurar que ningún campo de cabecera o texto libre de la ficha sea transmitido inadvertidamente en el prompt.
* **Transición a Nube Soberana / On-Premise:** Se priorizará el despliegue de un nodo centralizado de Ollama dentro del centro de datos del Hospital Fricke / SSVQ, eliminando progresivamente la necesidad de proveedores externos en la nube para el trabajo clínico diario.

