"""Dashboard Streamlit para el Asesor Clínico MEFI."""

import base64
import json
import os
import fitz  # PyMuPDF para convertir PDFs a imágenes compatibles con modelos locales
import yaml
import streamlit as st
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Asesor Clínico MEFI", layout="centered")

st.title("Asesor Clínico MEFI - Hospital Gustavo Fricke")

# --- BARRA LATERAL: SELECTOR DINÁMICO DE ENTORNO ---
st.sidebar.header("⚙️ Configuración de Inferencia")

def cargar_config_app():
    config_path = "config.yaml"
    if not os.path.exists(config_path):
        config_path = os.path.join("..", "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

config_data = cargar_config_app()

modo_operacion = st.sidebar.radio(
    "Selecciona el Entorno de Ejecución:",
    options=["Ollama (Local / Hospital)", "OpenRouter (Nube)"],
    index=0 if config_data.get("active_provider") == "ollama" else 1
)

if "Local" in modo_operacion:
    prov_key = "ollama"
    base_url = config_data["providers"]["ollama"]["base_url"]
    modelo_seleccionado = st.sidebar.selectbox(
        "Modelo local de visión:", 
        config_data["providers"]["ollama"]["vision_models"]
    )
    api_key = "ollama-local-placeholder"
else:
    prov_key = "openrouter"
    base_url = config_data["providers"]["openrouter"]["base_url"]
    modelo_seleccionado = st.sidebar.selectbox(
        "Modelo en nube de visión:", 
        config_data["providers"]["openrouter"]["vision_models"]
    )
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        st.sidebar.error("⚠️ Falta la OPENROUTER_API_KEY en el archivo .env")

try:
    client = OpenAI(base_url=base_url, api_key=api_key if api_key else "dummy-key")
    st.sidebar.success(f"Conectado a: **{prov_key.upper()}**")
except Exception as e:
    st.sidebar.error(f"Error al inicializar cliente: {e}")
    client = None

from processing import FCF_MAX_NORMAL, FCF_MIN_NORMAL, procesar_mefi

# --- FUNCIONES DE CONVERSIÓN Y ANÁLISIS ---

def convertir_pdf_a_imagen_bytes(pdf_bytes):
    """Convierte la primera página de un PDF en bytes de imagen JPEG para modelos locales."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if len(doc) > 0:
        pagina = doc[0]
        pix = pagina.get_pixmap(dpi=150)
        return pix.tobytes("jpeg")
    raise ValueError("El archivo PDF está vacío o no es legible.")

def _limpiar_bloque_codigo(texto):
    texto = texto.strip()
    if texto.startswith("```"):
        lineas = texto.splitlines()
        lineas = [l for l in lineas if not l.strip().startswith("```")]
        texto = "\n".join(lineas).strip()
    return texto

SYSTEM_INSTRUCTIONS = """# SYSTEM INSTRUCTIONS: Asesor Clínico MEFI - Hospital Dr. Gustavo Fricke (V3-2026)
## 1. IDENTIDAD Y ROL
**Rol:** Eres un Asistente Clínico Experto en Medicina Materno-Fetal avanzado.
**Misión:** Realizar un análisis multimodal de registros cardiotocográficos (MEFI) para proponer clasificación y conducta médica basada en el Protocolo Institucional.
"""

PROMPT_ANALISIS = (
    "Analiza este trazado cardiotocográfico fetal siguiendo tus instrucciones de "
    "sistema. Debes responder ÚNICAMENTE con un objeto JSON válido con dos campos:\n"
    '- "csv_data": un string con el CSV de los puntos de la curva de FCF.\n'
    '- "report": un string con el informe clínico completo en formato Markdown.'
)

def analizar_imagen_mefi(imagen_bytes, client, modelo):
    # Forzar tipo MIME de imagen pura (compatible con Ollama y LLaVA)
    tipo_mime = "image/jpeg"
    imagen_b64 = base64.b64encode(imagen_bytes).decode("utf-8")
    data_url = f"data:{tipo_mime};base64,{imagen_b64}"
    
    respuesta = client.chat.completions.create(
        model=modelo,
        max_tokens=2000,
        messages=[
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": [
                {"type": "text", "text": PROMPT_ANALISIS},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]},
        ],
    )
    
    contenido = _limpiar_bloque_codigo(respuesta.choices[0].message.content)
    try:
        datos = json.loads(contenido)
    except:
        return {"csv_data": "", "report": contenido}
        
    return {"csv_data": _limpiar_bloque_codigo(datos.get("csv_data", "")), "report": datos.get("report", "")}

# --- INTERFAZ PRINCIPAL ---
archivo_subido = st.file_uploader(
    "Sube un CSV (columnas 'tiempo' y 'fcf') o una imagen/PDF del trazado CTG",
    type=["csv", "jpg", "jpeg", "png", "pdf"],
)

if archivo_subido is not None and client is not None:
    os.makedirs("data", exist_ok=True)
    extension = os.path.splitext(archivo_subido.name)[1].lower()

    try:
        informe_clinico = None
        
        # Si es PDF, lo convertimos automáticamente a JPEG en memoria antes de pasarlo al modelo local
        if extension == ".pdf":
            with st.spinner("Convirtiendo PDF a imagen para análisis local..."):
                pdf_bytes = archivo_subido.getvalue()
                imagen_convertida_bytes = convertir_pdf_a_imagen_bytes(pdf_bytes)
                
                analisis = analizar_imagen_mefi(
                    imagen_convertida_bytes, client, modelo_seleccionado
                )
            csv_extraido = analisis["csv_data"]
            informe_clinico = analisis["report"]

        elif extension in (".jpg", ".jpeg", ".png"):
            with st.spinner("Analizando trazado con el Asesor Clínico MEFI..."):
                analisis = analizar_imagen_mefi(
                    archivo_subido.getvalue(), client, modelo_seleccionado
                )
            csv_extraido = analisis["csv_data"]
            informe_clinico = analisis["report"]

        if extension in (".pdf", ".jpg", ".jpeg", ".png"):
            with st.expander("Ver CSV extraído por el modelo"):
                st.code(csv_extraido, language="csv")

            nombre_csv = os.path.splitext(archivo_subido.name)[0] + "_extraido.csv"
            ruta_destino = os.path.join("data", nombre_csv)
            with open(ruta_destino, "w", encoding="utf-8") as f:
                f.write(csv_extraido)

            resultado = procesar_mefi(nombre_csv)
        else:
            ruta_destino = os.path.join("data", archivo_subido.name)
            with open(ruta_destino, "wb") as f:
                f.write(archivo_subido.getbuffer())
            resultado = procesar_mefi(archivo_subido.name)

        st.subheader("Resultados del análisis")
        st.table({
            "Métrica": ["Media FCF (lpm)", "Variabilidad FCF (desv. estándar)"],
            "Valor": [f"{resultado['media_fcf']:.1f}", f"{resultado['std_fcf']:.1f}"],
        })

        if informe_clinico:
            st.subheader("Análisis Clínico del Asesor")
            st.markdown(informe_clinico)

    except Exception as e:
        st.error(f"Error al procesar el archivo: {e}")