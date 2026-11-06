"""Dashboard Streamlit para el Asesor Clínico MEFI."""

import base64
import io
import os
from pathlib import Path
import fitz  # PyMuPDF para convertir PDFs a imágenes compatibles con modelos locales
import yaml
import streamlit as st
import streamlit.components.v1 as components
from openai import (
    APIConnectionError,
    AuthenticationError,
    NotFoundError,
    OpenAI,
    RateLimitError,
)
from dotenv import load_dotenv

import clinical
import prompts
import reporte_pdf
import rutas
from digitizer import (
    calibrar_desde_dos_puntos,
    detectar_anotaciones_clinicas,
    digitalizar_con_calibracion,
    extraer_metadatos_cabecera,
    preparar_imagen,
    sugerir_puntos_calibracion,
)

_CALIBRADOR_DIR = Path(__file__).resolve().parent / "componente_calibrador"
_calibrador_lineas = components.declare_component("calibrador_lineas", path=str(_CALIBRADOR_DIR))

rutas.sembrar_home()
CONFIG_PATH = str(rutas.ruta_lectura("config.yaml"))
ENV_PATH = str(rutas.ruta_escritura(".env"))
load_dotenv(ENV_PATH)
load_dotenv()  # fallback a .env en la raíz o variables del entorno

st.set_page_config(page_title="Asesor Clínico MEFI", layout="wide")

st.title("Asesor Clínico MEFI - Hospital Gustavo Fricke")

st.warning(
    "**Este sistema es una ayuda diagnóstica, no un diagnóstico.** La clasificación FIGO/NICE "
    "y el informe generado no reemplazan el juicio clínico ni la evaluación directa del "
    "paciente. Precisión de clasificación no implica beneficio clínico demostrado: el ensayo "
    "INFANT (Lancet, 2017) mostró que un sistema de apoyo a la decisión en CTG con alta "
    "precisión de clasificación no mejoró los desenlaces neonatales. Este MVP usa una "
    "simplificación de FIGO 2015 / NICE NG229 y no está validado en la población del "
    "Hospital Gustavo Fricke.",
    icon="⚠️",
)

# --- BARRA LATERAL: SELECTOR DINÁMICO DE ENTORNO ---
st.sidebar.header("⚙️ Configuración de Inferencia")


def cargar_config_app():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def guardar_config_app(config_data):
    """Persiste active_provider y el modelo elegido por proveedor en config.yaml."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f, allow_unicode=True, sort_keys=False)


def guardar_api_key(nombre_var, valor):
    """Crea o actualiza una variable en .env sin tocar las demás líneas."""
    lineas = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lineas = f.readlines()

    encontrada = False
    for i, linea in enumerate(lineas):
        if linea.strip().startswith(f"{nombre_var}="):
            lineas[i] = f"{nombre_var}={valor}\n"
            encontrada = True
            break
    if not encontrada:
        lineas.append(f"{nombre_var}={valor}\n")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lineas)
    os.environ[nombre_var] = valor


config_data = cargar_config_app()
proveedores = config_data.get("providers", {})
claves_proveedores = list(proveedores.keys())
etiquetas_proveedores = [proveedores[k].get("label", k) for k in claves_proveedores]

indice_activo = (
    claves_proveedores.index(config_data.get("active_provider"))
    if config_data.get("active_provider") in claves_proveedores
    else 0
)

etiqueta_elegida = st.sidebar.radio(
    "Selecciona el Entorno de Ejecución:",
    options=etiquetas_proveedores,
    index=indice_activo,
)
prov_key = claves_proveedores[etiquetas_proveedores.index(etiqueta_elegida)]
prov_config = proveedores[prov_key]

base_url = prov_config["base_url"]
modelos_texto_disponibles = prov_config.get("text_models") or prov_config.get("vision_models", [])
modelo_seleccionado = st.sidebar.selectbox(
    "Modelo de texto (informe clínico):",
    modelos_texto_disponibles,
    index=modelos_texto_disponibles.index(prov_config["model"])
    if prov_config.get("model") in modelos_texto_disponibles
    else 0,
)

api_key = None
if prov_config.get("needs_api_key", False):
    api_key_env = prov_config.get("api_key_env")
    api_key = os.getenv(api_key_env)
    if not api_key:
        st.sidebar.warning(f"⚠️ Falta {api_key_env} para usar {prov_config.get('label', prov_key)}.")
        with st.sidebar.expander("Ingresar API key", expanded=True):
            nueva_key = st.text_input(f"{api_key_env}", type="password", key=f"apikey_{prov_key}")
            if st.button("Guardar API key", key=f"guardar_apikey_{prov_key}") and nueva_key:
                guardar_api_key(api_key_env, nueva_key)
                st.sidebar.success("API key guardada en .env. Selecciona el proveedor de nuevo si no se aplica.")
                api_key = nueva_key
else:
    api_key = "local-key"

if st.sidebar.button("💾 Guardar como predeterminado"):
    config_data["active_provider"] = prov_key
    config_data["providers"][prov_key]["model"] = modelo_seleccionado
    guardar_config_app(config_data)
    st.sidebar.success("Preferencia guardada en config.yaml.")

try:
    client = OpenAI(base_url=base_url, api_key=api_key if api_key else "dummy-key", timeout=90.0)
    if api_key:
        st.sidebar.success(f"Conectado a: **{prov_config.get('label', prov_key)}**")
except Exception as e:
    st.sidebar.error(f"Error al inicializar cliente: {e}")
    client = None

from processing import FCF_MAX_NORMAL, FCF_MIN_NORMAL, procesar_mefi

DPI_RENDER_PDF = 300

# --- FUNCIONES DE CONVERSIÓN Y ANÁLISIS ---

def _limpiar_bloque_codigo(texto):
    texto = texto.strip()
    if texto.startswith("```"):
        lineas = texto.splitlines()
        lineas = [l for l in lineas if not l.strip().startswith("```")]
        texto = "\n".join(lineas).strip()
    return texto


def generar_informe_clinico(features, client, modelo, metadatos=None):
    """Le pide al LLM el informe clínico en texto puro, razonando sobre el dict de
    `clinical.extraer_features()` — ya NO se le manda la imagen del trazado (Fase 3
    del plan). Ver investigación de estado del arte: ningún VLM genérico lee
    coordenadas numéricas de forma confiable desde un gráfico, así que la
    digitalización (`digitizer.py`) y la clasificación (`clinical.py`) quedan
    fuera del LLM por completo; el LLM solo interpreta clínicamente el resultado."""
    respuesta = client.chat.completions.create(
        model=modelo,
        max_tokens=2000,
        messages=[
            {"role": "system", "content": prompts.SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": prompts.construir_prompt_usuario(features, metadatos=metadatos)},
        ],
    )
    return _limpiar_bloque_codigo(respuesta.choices[0].message.content)


def _ejecutar_llm_con_fallback(features, metadatos=None):
    """Ejecuta la consulta al LLM activo con fallback automático entre modelos
    gratuitos si ocurre saturación (429). Guarda el resultado en `st.session_state`."""
    if client is None or not api_key:
        return
    modelos_gratis = [m for m in modelos_texto_disponibles if m.endswith(":free")]
    if prov_key == "openrouter" and modelo_seleccionado in modelos_gratis:
        candidatos = [modelo_seleccionado] + [m for m in modelos_gratis if m != modelo_seleccionado]
    else:
        candidatos = [modelo_seleccionado]

    for i, modelo_intento in enumerate(candidatos):
        try:
            with st.spinner(f"Generando informe independiente con IA ({modelo_intento})..."):
                st.session_state.informe_llm = generar_informe_clinico(
                    features, client, modelo_intento, metadatos=metadatos
                )
                st.session_state.modelo_usado_llm = modelo_intento if i > 0 else modelo_seleccionado
            break
        except RateLimitError as e:
            if i < len(candidatos) - 1:
                st.info(f"{modelo_intento} saturado (límite de uso gratis) — probando con {candidatos[i+1]}...")
                continue
            st.warning(
                "Los modelos gratuitos de OpenRouter están con alta demanda en este instante. "
                "El **Informe por Plantilla** y el **PDF Consolidado** ya están listos; puedes pulsar "
                "«🔄 Regenerar análisis con IA» en unos segundos o elegir otro modelo en la barra lateral."
            )
        except NotFoundError as e:
            st.error(f"El modelo `{modelo_intento}` ya no existe en OpenRouter — revisá `config.yaml`.\n\n{e}")
            break
        except AuthenticationError as e:
            st.error(f"Problema de autenticación con {prov_key.upper()} — revisá la API key en `.env`.\n\n{e}")
            break
        except APIConnectionError as e:
            sugerencia = (
                f"Confirmá que Ollama esté corriendo (`ollama serve`) y que el modelo esté descargado (`ollama pull {modelo_intento}`)."
                if prov_key == "ollama"
                else "No se pudo conectar a OpenRouter — revisá tu conexión a internet."
            )
            st.error(f"Error de conexión con {prov_key.upper()}: {e}\n\n{sugerencia}")
            break
        except Exception as e:
            st.error(f"Error al generar el informe con {modelo_intento}: {e}")
            break


def _imagen_bytes_desde_archivo(archivo_subido, extension):
    if extension == ".pdf":
        doc = fitz.open(stream=archivo_subido.getvalue(), filetype="pdf")
        if len(doc) == 0:
            raise ValueError("El archivo PDF está vacío o no es legible.")
        pix = doc[0].get_pixmap(dpi=DPI_RENDER_PDF)
        return pix.tobytes("png"), DPI_RENDER_PDF
    return archivo_subido.getvalue(), DPI_RENDER_PDF  # aprox. para fotos: no traen DPI real


def _nombre_archivo_anonimizado(sufijo: str, id_caso: str | None = None, fecha_hora: str | None = None) -> str:
    """Genera un nombre de archivo a partir del ID y la fecha del caso, nunca del nombre
    original del archivo subido — ese nombre puede traer el nombre real del paciente
    (pasó en la práctica: un CSV digitalizado quedó guardado como
    "Javiera Antonia Millán Ortiz ..._extraido.csv" porque se usaba
    `archivo_subido.name` directo). Ver convención en data/README.md.

    Con ID de caso y fecha devuelve `YYYY-MM-DD_<id><sufijo>` (trazable, sin
    timestamp ni colisiones entre reruns). La fecha se tolera en ISO
    (YYYY-MM-DD) o chilena (DD/MM/YYYY, DD-MM-YYYY); si falta, usa la fecha
    actual y si falta el ID usa `sin-id`. Sin ambos, fallback al timestamp de
    subida, que garantiza unicidad."""
    import datetime
    import re

    ahora = datetime.datetime.now()
    if id_caso or fecha_hora:
        fecha = ahora.strftime("%Y-%m-%d")
        if fecha_hora:
            m = re.search(r"(\d{4})-(\d{2})-(\d{2})", fecha_hora) or re.search(
                r"(\d{2})[/-](\d{2})[/-](\d{4})", fecha_hora
            )
            if m:
                g = m.groups()
                fecha = f"{g[0]}-{g[1]}-{g[2]}" if len(g[0]) == 4 else f"{g[2]}-{g[1]}-{g[0]}"
        id_limpio = "sin-id"
        if id_caso:
            limpio = re.sub(r"[^a-z0-9_-]+", "", str(id_caso).lower().replace(" ", "-"))
            if limpio:
                id_limpio = limpio
        return f"{fecha}_{id_limpio}{sufijo}"
    marca = ahora.strftime("%Y%m%d_%H%M%S")
    return f"{marca}{sufijo}"


ANCHO_ZOOM_PX = 1400  # cuanto ancho de imagen ORIGINAL entra en la ventana de zoom


def _panel_recortado(prep, panel, x0, x1, ancho_mostrado=900):
    recorte = prep.imagen.crop((x0, panel.y0, x1, panel.y1))
    escala = recorte.width / ancho_mostrado
    mostrado = recorte.resize((ancho_mostrado, max(1, int(recorte.height / escala))))
    return mostrado, escala


def _imagen_a_data_uri(img_pil) -> str:
    """Codifica una imagen PIL como data URI PNG en base64 para el componente HTML."""
    buf = io.BytesIO()
    img_pil.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _selector_zoom(prep):
    """Botones Anterior/Siguiente compartidos (mismo eje de tiempo en ambos paneles) para
    elegir qué franja horizontal ver de cerca — necesario en trazados largos (varios
    segmentos de papel), donde mostrar todo el ancho de una vez deja la grilla y los
    números ilegibles."""
    ancho_total = prep.imagen.width
    if ancho_total <= ANCHO_ZOOM_PX:
        return 0, ancho_total
    maximo = ancho_total - ANCHO_ZOOM_PX
    if "zoom_x0" not in st.session_state:
        st.session_state.zoom_x0 = 0
    st.session_state.zoom_x0 = min(st.session_state.zoom_x0, maximo)

    col_izq, col_pos, col_der = st.columns([1, 2, 1])
    if col_izq.button("◀ Anterior", disabled=st.session_state.zoom_x0 <= 0, key="zoom_prev"):
        st.session_state.zoom_x0 = max(0, st.session_state.zoom_x0 - ANCHO_ZOOM_PX)
        st.rerun()
    if col_der.button("Siguiente ▶", disabled=st.session_state.zoom_x0 >= maximo, key="zoom_next"):
        st.session_state.zoom_x0 = min(maximo, st.session_state.zoom_x0 + ANCHO_ZOOM_PX)
        st.rerun()
    x0 = st.session_state.zoom_x0
    col_pos.caption(f"Viendo {x0}–{x0 + ANCHO_ZOOM_PX} px de {ancho_total} px totales")

    return x0, x0 + ANCHO_ZOOM_PX


def _aplicar_sugerencia(key_prefix, sugerencia, valor_default_1=None, valor_default_2=None):
    """Callback `on_click` del botón de restaurar posición inicial: se ejecuta ANTES de
    instanciar los `number_input` para evitar `StreamlitWidgetAlreadyInstantiatedError`."""
    (y1, v1), (y2, v2) = sugerencia
    st.session_state[f"{key_prefix}_clics"] = [float(y1), float(y2)]
    st.session_state[f"{key_prefix}_v1"] = float(valor_default_1 if valor_default_1 is not None else v1)
    st.session_state[f"{key_prefix}_v2"] = float(valor_default_2 if valor_default_2 is not None else v2)
    st.session_state[f"{key_prefix}_ver"] = st.session_state.get(f"{key_prefix}_ver", 0) + 1


def _widget_calibracion(prep, panel, nombre, valor_default_1, valor_default_2, key_prefix, x0, x1):
    """Muestra el panel recortado con 2 líneas horizontales interactivas (🔵 Línea 1 Azul
    y 🔴 Línea 2 Roja) que se arrastran directamente con el mouse hacia arriba o abajo
    sin que la imagen desaparezca ni parpadee, y permite confirmar debajo el número
    impreso en el papel para cada línea. Devuelve CalibracionEje o None."""
    st.markdown(
        f"**Panel {nombre}** — **1)** Arrastra con el mouse la **🔵 Línea 1 (Azul)** y la **🔴 Línea 2 (Roja)** "
        f"sobre la imagen hasta ubicarlas encima de dos líneas con número impreso en el papel. "
        f"**2)** Abajo, **confirma el número** de cada línea."
    )
    clics_key = f"{key_prefix}_clics"
    ver_key = f"{key_prefix}_ver"
    panel_alto = max(1, int(panel.y1 - panel.y0))
    if clics_key not in st.session_state:
        st.session_state[clics_key] = []
    if ver_key not in st.session_state:
        st.session_state[ver_key] = 0
    for k, v in ((f"{key_prefix}_v1", float(valor_default_1)), (f"{key_prefix}_v2", float(valor_default_2))):
        if k not in st.session_state:
            st.session_state[k] = v

    sugerencia_key = f"{key_prefix}_sugerencia"
    if sugerencia_key not in st.session_state:
        valores_default = (valor_default_1, valor_default_2)
        st.session_state[sugerencia_key] = sugerir_puntos_calibracion(prep.gris, panel, valores_default)
    sugerencia = st.session_state[sugerencia_key]

    # Inicializar siempre con 2 líneas listas para arrastrar y valores limpios (ej. 210 y 30 / 100 y 0)
    if len(st.session_state[clics_key]) < 2:
        if sugerencia is not None:
            (y1_sug, v1_sug), (y2_sug, v2_sug) = sugerencia
            st.session_state[clics_key] = [float(y1_sug), float(y2_sug)]
            st.session_state[f"{key_prefix}_v1"] = float(v1_sug)
            st.session_state[f"{key_prefix}_v2"] = float(v2_sug)
        else:
            st.session_state[clics_key] = [
                float(panel.y0 + panel_alto * 0.20),
                float(panel.y0 + panel_alto * 0.80),
            ]
        st.session_state[ver_key] += 1

    mostrado_base, escala = _panel_recortado(prep, panel, x0, x1, ancho_mostrado=1050)
    clics_actuales = st.session_state[clics_key]
    y1_px_ini = max(2.0, min(float(mostrado_base.height - 2), (clics_actuales[0] - panel.y0) / escala))
    y2_px_ini = max(2.0, min(float(mostrado_base.height - 2), (clics_actuales[1] - panel.y0) / escala))

    v1_actual = int(round(st.session_state[f"{key_prefix}_v1"]))
    v2_actual = int(round(st.session_state[f"{key_prefix}_v2"]))

    respuesta_drag = _calibrador_lineas(
        img_src=_imagen_a_data_uri(mostrado_base),
        img_height=int(mostrado_base.height),
        y1_px=float(y1_px_ini),
        y2_px=float(y2_px_ini),
        label1=f"Línea 1 (Azul): {v1_actual}",
        label2=f"Línea 2 (Roja): {v2_actual}",
        sync_id=int(st.session_state[ver_key]),
        key=f"{key_prefix}_calibrador",
        default=None,
    )

    if isinstance(respuesta_drag, dict) and "y1_px" in respuesta_drag and "y2_px" in respuesta_drag:
        # Solo aplicar si corresponde al sync_id vigente (no pisar un reset recién hecho)
        if respuesta_drag.get("sync_id", st.session_state[ver_key]) == st.session_state[ver_key]:
            y1_abs = float(respuesta_drag["y1_px"]) * escala + panel.y0
            y2_abs = float(respuesta_drag["y2_px"]) * escala + panel.y0
            st.session_state[clics_key] = [y1_abs, y2_abs]

    clics = st.session_state[clics_key]

    ejemplos = "ej. 210, 180, 150, 120, 90, 60, 30" if valor_default_1 > 120 else "ej. 100, 80, 60, 50, 40, 25, 20, 0"
    col1, col2, col3 = st.columns([2, 2, 1.5])
    valor1 = col1.number_input(
        f"🔵 Confirmar número Línea 1 Azul ({nombre})",
        step=10.0,
        format="%.0f",
        help=f"Escribe o ajusta el número impreso en el papel donde dejaste la Línea 1 Azul ({ejemplos}).",
        key=f"{key_prefix}_v1",
    )
    valor2 = col2.number_input(
        f"🔴 Confirmar número Línea 2 Roja ({nombre})",
        step=10.0,
        format="%.0f",
        help=f"Escribe o ajusta el número impreso en el papel donde dejaste la Línea 2 Roja ({ejemplos}).",
        key=f"{key_prefix}_v2",
    )
    if sugerencia is not None:
        col3.write("")
        col3.button(
            "✨ Restaurar posición inicial",
            key=f"{key_prefix}_auto",
            on_click=_aplicar_sugerencia,
            args=(key_prefix, sugerencia, valor_default_1, valor_default_2),
            use_container_width=True,
        )
    st.caption(
        f"💡 **Paso visual:** Arrastra con el mouse las líneas **🔵 Azul** y **🔴 Roja** sobre la imagen de arriba "
        f"y confirma aquí abajo el número impreso en esa línea del papel ({ejemplos})."
    )

    if len(clics) == 2 and valor1 != valor2 and abs(clics[1] - clics[0]) >= 2.0:
        return calibrar_desde_dos_puntos(clics[0], valor1, clics[1], valor2, panel)
    return None


# --- GUÍA PASO A PASO Y CARGA DE ARCHIVO ---
with st.expander("🧭 ¿Cómo funciona el sistema? — Guía rápida paso a paso", expanded=True):
    st.markdown(
        """
1. **Paso 1 — Cargar el monitoreo (Imagen o PDF):** Sube la foto o escaneo del trazado. *¿Qué hace el sistema?* Endereza la hoja automáticamente, lee los datos de cabecera (ID, fecha, velocidad) y separa el gráfico superior (**FCF: Frecuencia Cardíaca Fetal**) del inferior (**UA: Actividad Uterina / Contracciones**).
2. **Paso 2 — Mover las líneas con el mouse y confirmar el número (Calibración):** Sobre cada gráfico verás una **🔵 Línea 1 (Azul)** y una **🔴 Línea 2 (Roja)**:
   - **Arrastra cada línea con el mouse** hacia arriba o hacia abajo hasta ubicarla sobre una línea del papel que tenga número impreso (por ejemplo, `210` y `60` o `30` en FCF; `100` y `0` en UA).
   - **Abajo de la imagen**, confirma o escribe el número exacto de esa línea en las casillas **🔵 Confirmar número Línea 1 Azul** y **🔴 Confirmar número Línea 2 Roja**.
3. **Paso 3 — Digitalizar y generar informes en un clic:** Pulsa **«🚀 Digitalizar trazado y generar informes»**. Verás la curva extraída dibujada en **celeste** sobre el papel para auditoría visual.
4. **Paso 4 — Clasificación, Comparación lado a lado y PDF Consolidado:** El sistema entrega la **Categoría FIGO 2015 / Semáforo NICE**, compara fila por fila el **Informe por Plantilla** con el **Informe con IA (LLM)** y permite descargar el **Reporte Clínico Consolidado (.pdf)**.
        """
    )

archivo_subido = st.file_uploader(
    "Paso 1: Sube un CSV (columnas 'tiempo' y 'fcf') o una imagen/PDF del trazado CTG",
    type=["csv", "jpg", "jpeg", "png", "pdf"],
)

if archivo_subido is not None:
    os.makedirs("data", exist_ok=True)
    extension = os.path.splitext(archivo_subido.name)[1].lower()

    if extension == ".csv":
        try:
            nombre_anonimo = _nombre_archivo_anonimizado(".csv")
            ruta_destino = os.path.join(str(rutas.ruta_escritura("data")), nombre_anonimo)
            with open(ruta_destino, "wb") as f:
                f.write(archivo_subido.getbuffer())
            resultado = procesar_mefi(nombre_anonimo)
            st.subheader("Resultados del análisis")
            st.table({
                "Métrica": ["Media FCF (lpm)", "Variabilidad FCF (desv. estándar)"],
                "Valor": [f"{resultado['media_fcf']:.1f}", f"{resultado['std_fcf']:.1f}"],
            })
        except Exception as e:
            st.error(f"Error al procesar el archivo: {e}")

    else:
        # Solo re-preparar (orientar + detectar paneles) si es un archivo nuevo — evita
        # recalcular en cada rerun que dispara un clic de calibración. "archivo_actual"
        # solo se marca DESPUÉS de que preparar_imagen() tuvo éxito, para que si falla
        # se pueda reintentar (y se vea el error real) en vez de quedar en un estado roto.
        if st.session_state.get("archivo_actual") != archivo_subido.name:
            st.session_state.pop("prep", None)
            for _p in ("fcf", "ua"):
                st.session_state[f"{_p}_clics"] = []
                st.session_state[f"{_p}_ver"] = st.session_state.get(f"{_p}_ver", 0) + 1
                st.session_state.pop(f"{_p}_sugerencia", None)
                st.session_state.pop(f"{_p}_auto_init", None)
                st.session_state.pop(f"{_p}_v1", None)
                st.session_state.pop(f"{_p}_v2", None)
                st.session_state.pop(f"{_p}_pos_y1", None)
                st.session_state.pop(f"{_p}_pos_y2", None)
            st.session_state.pop("resultado_digitalizacion", None)
            st.session_state.pop("informe_llm", None)
            st.session_state.pop("modelo_usado_llm", None)
            try:
                with st.spinner("Orientando imagen y detectando paneles FCF/UA..."):
                    imagen_bytes, dpi_usado = _imagen_bytes_desde_archivo(archivo_subido, extension)
                    st.session_state.prep = preparar_imagen(imagen_bytes, dpi_render=dpi_usado)
                    st.session_state.metadatos_cabecera = extraer_metadatos_cabecera(imagen_bytes)
                    st.session_state.anotaciones_clinicas = detectar_anotaciones_clinicas(st.session_state.prep)
                st.session_state.archivo_actual = archivo_subido.name
            except Exception as e:
                st.error(f"Error al preparar la imagen: {e}")
                st.exception(e)

        if "prep" not in st.session_state:
            st.stop()

        prep = st.session_state.prep
        for adv in prep.advertencias:
            st.warning(adv)

        for adv in st.session_state.get("anotaciones_clinicas", []):
            st.info(adv)

        meta = st.session_state.get("metadatos_cabecera") or {}
        with st.expander("📋 Metadatos del registro y contexto obstétrico (opcional — enriquece los informes y el PDF)", expanded=True):
            st.caption(
                "Los datos de cabecera se leen localmente por OCR de mejor esfuerzo. "
                "Puedes corregirlos o agregar el contexto obstétrico para que ambos informes y el PDF consolidado lo integren."
            )
            c1, c2, c3 = st.columns(3)
            c1.text_input("ID de registro (anónimo/interno)", value=meta.get("id") or "", key="meta_id")
            c1.text_input("Fecha/hora de inicio", value=meta.get("fecha_hora") or "", key="meta_fecha")
            c2.number_input(
                "Velocidad de papel (cm/min)",
                value=float(meta.get("velocidad_papel_cm_min") or 1.0),
                key="meta_velocidad",
            )
            c2.text_input("Edad gestacional (ej. 39+2 sem)", value="", key="ctx_eg")
            c3.selectbox(
                "Contexto obstétrico",
                options=[
                    "Trabajo de parto fase activa",
                    "Preparto / Fase latente",
                    "Período expulsivo",
                    "Control antenatal",
                    "No especificado",
                ],
                index=0,
                key="ctx_etapa",
            )
            c3.selectbox(
                "Uso de oxitocina / conducción",
                options=[
                    "Sin oxitocina",
                    "En conducción con oxitocina",
                    "No especificado",
                ],
                index=2,
                key="ctx_oxitocina",
            )

        st.subheader("1. Calibración y validación de coordenadas del trazado")
        st.info(
            "**¿Qué debes hacer en este paso?**\n"
            "1. **Arrastra con el mouse** la **🔵 Línea 1 (Azul)** y la **🔴 Línea 2 (Roja)** hacia arriba o hacia abajo directamente sobre cada imagen hasta ubicarlas sobre dos líneas del papel que tengan número impreso.\n"
            "2. **Abajo de cada imagen, confirma el número** impreso en el papel para la línea azul y la línea roja (por ejemplo: `210` y `60` o `30` en FCF; `100` y `0` en UA).\n"
            "3. Pulsa **«🚀 Digitalizar trazado y generar informes»** para obtener la curva auditada, el Informe por Plantilla, el Informe IA y el PDF Consolidado en un solo paso."
        )
        x0_zoom, x1_zoom = _selector_zoom(prep)
        cal_fcf = _widget_calibracion(prep, prep.panel_fcf, "FCF (lpm)", 210, 30, "fcf", x0_zoom, x1_zoom)
        st.divider()
        cal_ua = _widget_calibracion(prep, prep.panel_ua, "UA", 100, 0, "ua", x0_zoom, x1_zoom)

        if cal_fcf is not None and cal_ua is not None:
            st.success(
                "✅ Coordenadas de ambos paneles listas. "
                "Una vez ubicadas las líneas con el mouse y confirmados sus números, presiona el botón para procesar todo:"
            )
            if st.button("🚀 Digitalizar trazado y generar informes (Plantilla + IA)", type="primary", use_container_width=True):
                with st.spinner("Extrayendo curvas FCF/UA..."):
                    st.session_state.resultado_digitalizacion = digitalizar_con_calibracion(
                        prep, cal_fcf, cal_ua
                    )
                    st.session_state.pop("informe_llm", None)
                    st.session_state.pop("modelo_usado_llm", None)
                # Ejecución automática del informe LLM en el mismo paso si hay conexión
                try:
                    features_auto = clinical.extraer_features(st.session_state.resultado_digitalizacion.df)
                    meta_auto = {
                        "id": st.session_state.get("meta_id") or meta.get("id"),
                        "fecha_hora": st.session_state.get("meta_fecha") or meta.get("fecha_hora"),
                        "velocidad_papel_cm_min": st.session_state.get("meta_velocidad") or 1.0,
                        "edad_gestacional": st.session_state.get("ctx_eg") or "",
                        "contexto_clinico": st.session_state.get("ctx_etapa") or "No especificado",
                        "uso_oxitocina": st.session_state.get("ctx_oxitocina") or "No especificado",
                    }
                    _ejecutar_llm_con_fallback(features_auto, metadatos=meta_auto)
                except Exception:
                    pass
        else:
            faltan = []
            if cal_fcf is None:
                faltan.append("panel FCF")
            if cal_ua is None:
                faltan.append("panel UA")
            st.warning(
                f"⏳ Falta completar los 2 puntos de referencia en: **{', '.join(faltan)}**. "
                "Usa el botón «✨ Detección automática» o haz 2 clics sobre las líneas del gráfico correspondiente."
            )

        if "resultado_digitalizacion" in st.session_state:
            resultado = st.session_state.resultado_digitalizacion
            st.subheader("2. Curva digitalizada (auditoría)")
            st.caption(
                "Verifica que la línea celeste siga el trazo impreso en el papel. Si la curva está "
                "desplazada verticalmente, ajusta los puntos de calibración en el Paso 1 y vuelve a digitalizar."
            )
            st.image(
                resultado.overlay,
                caption="Celeste = lectura directa · Naranja = tramo reconstruido por interpolación",
            )
            for adv in resultado.advertencias:
                st.info(adv)

            id_caso_actual = st.session_state.get("meta_id") or (meta or {}).get("id")
            fecha_caso_actual = st.session_state.get("meta_fecha") or (meta or {}).get("fecha_hora")
            nombre_csv = _nombre_archivo_anonimizado(
                "_extraido.csv",
                id_caso=id_caso_actual,
                fecha_hora=fecha_caso_actual,
            )
            ruta_destino = os.path.join(str(rutas.ruta_escritura("data/extracted")), nombre_csv)
            resultado.df.to_csv(ruta_destino, index=False)
            st.caption(f"Guardado como `{ruta_destino}` (nombre anonimizado, no el del archivo subido).")
            with st.expander("Ver CSV digitalizado"):
                st.dataframe(resultado.df)

            st.subheader("3. Panel de Parámetros y Clasificación (FIGO 2015 / NICE NG229)")
            try:
                features = clinical.extraer_features(resultado.df)
            except ValueError as e:
                features = None
                st.error(f"No se pudo calcular la clasificación clínica: {e}")

            if features is not None:
                figo = features["figo"]
                color_semaforo = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴"}
                banner_fn = {
                    "I": st.success,
                    "II": st.warning,
                    "III": st.error,
                }.get(figo["categoria"], st.info)
                banner_fn(
                    f"### Categoría FIGO {figo['categoria']} — {figo['descripcion']}\n"
                    f"**Criterios determinantes:** {' · '.join(figo['razones'])}"
                )

                contr = features.get("contracciones") or {}
                valor_contracciones = (
                    f"{contr.get('num')}"
                    + (f" ({contr.get('por_10min')}/10m)" if contr.get("por_10min") is not None else "")
                    if contr.get("num") is not None
                    else "Sin UA"
                )
                area_decel = features.get("area_desaceleraciones_lpm_s")

                # Tarjetas ejecutivas proporcionales (6 KPIs en una fila)
                k1, k2, k3, k4, k5, k6 = st.columns(6)
                with k1.container(border=True):
                    st.caption(f"{color_semaforo[figo['semaforo_nice']['linea_base']]} Línea Base")
                    st.markdown(f"**{features['linea_base']:.0f} lpm**")
                    st.caption("Normal: 110–160")
                with k2.container(border=True):
                    st.caption(f"{color_semaforo[figo['semaforo_nice']['variabilidad']]} Variabilidad")
                    st.markdown(f"**{features['variabilidad']['amplitud_media_lpm']} lpm**")
                    st.caption(f"Cat: {features['variabilidad']['categoria']}")
                with k3.container(border=True):
                    st.caption("🟢 Aceleraciones")
                    st.markdown(f"**{len(features['aceleraciones'])} eventos**")
                    st.caption("Reactividad ≥15 lpm")
                with k4.container(border=True):
                    st.caption(f"{color_semaforo[figo['semaforo_nice']['desaceleraciones']]} Desaceleraciones")
                    st.markdown(f"**{len(features['desaceleraciones'])} eventos**")
                    st.caption(
                        f"Área: {area_decel:,} lpm·s".replace(",", ".")
                        if area_decel is not None
                        else "Sin área"
                    )
                with k5.container(border=True):
                    st.caption(f"{color_semaforo[figo['semaforo_nice'].get('contracciones', 'verde')]} Contracciones")
                    st.markdown(f"**{valor_contracciones}**")
                    st.caption("Taquisistolia ≥5/10m" if contr.get("tachisistolia") else "Rango <5/10m")
                with k6.container(border=True):
                    es_sin = features["patron_sinusoidal"]["presente"]
                    st.caption("🔴 Sinusoidal" if es_sin else "🟢 Sinusoidal")
                    st.markdown("**Presente**" if es_sin else "**Ausente**")
                    st.caption("Banda 3–5 cpm")

                with st.expander("🔍 Ver desglose detallado de desaceleraciones y tabla técnica"):
                    st.json(features["desaceleraciones"])

                # --- PASO 4: COMPARACIÓN ORDENADA (PLANTILLA vs LLM) + REPORTE PDF CONSOLIDADO ---
                st.subheader("4. Comparación de Informes (Plantilla vs. IA) y Reporte Final en PDF")
                st.caption(
                    "Observa cómo los dos informes se construyen por separado sobre las mismas mediciones "
                    "y compara sus conclusiones punto por punto. Puedes completar tu nombre y observaciones "
                    "clínicas para que salgan impresos directamente en el **Reporte Consolidado en PDF**."
                )

                with st.container(border=True):
                    st.markdown("##### 🖊️ Datos de Validación Profesional para el Reporte PDF (Opcional)")
                    p_col1, p_col2 = st.columns([1, 2])
                    prof_nombre = p_col1.text_input(
                        "Nombre y cargo del profesional responsable",
                        value="",
                        placeholder="Ej. Mat. / Dr(a). ...",
                        key="pdf_profesional",
                    )
                    prof_obs = p_col2.text_area(
                        "Observaciones clínicas presenciales / conducta adoptada (se imprimen en el PDF)",
                        value="",
                        height=68,
                        placeholder="Ingresa aquí tus notas clínicas o apreciación presencial para consolidarlas en el PDF...",
                        key="pdf_observaciones",
                    )

                metadatos_informe = {
                    "id": id_caso_actual,
                    "fecha_hora": fecha_caso_actual,
                    "velocidad_papel_cm_min": st.session_state.get("meta_velocidad")
                    or (meta or {}).get("velocidad_papel_cm_min")
                    or 1.0,
                    "edad_gestacional": st.session_state.get("ctx_eg") or "",
                    "contexto_clinico": st.session_state.get("ctx_etapa") or "No especificado",
                    "uso_oxitocina": st.session_state.get("ctx_oxitocina") or "No especificado",
                    "profesional": prof_nombre,
                    "observaciones_clinicas": prof_obs,
                }
                informe_plantilla = prompts.generar_informe_plantilla(features, metadatos=metadatos_informe)

                # Recuadro automático de Síntesis de Concordancia
                sintesis = prompts.generar_sintesis_concordancia(
                    features, informe_plantilla, st.session_state.get("informe_llm")
                )
                bloque_sintesis = "\n".join(f"- {p}" for p in sintesis["puntos"])
                if sintesis["estado"] == "alta":
                    st.success(f"**🔍 Síntesis de Concordancia: {sintesis['titulo']}**\n\n{bloque_sintesis}")
                elif sintesis["estado"] == "parcial":
                    st.warning(f"**🔍 Síntesis de Concordancia: {sintesis['titulo']}**\n\n{bloque_sintesis}")
                else:
                    st.info(f"**🔍 Síntesis de Concordancia: {sintesis['titulo']}**\n\n{bloque_sintesis}")

                bar_col1, bar_col2 = st.columns(2)
                with bar_col1:
                    if client is not None and api_key:
                        texto_boton_llm = (
                            "🔄 Regenerar análisis con IA (LLM)"
                            if st.session_state.get("informe_llm")
                            else "✨ Generar análisis con IA (LLM) para comparar con la Plantilla"
                        )
                        if st.button(texto_boton_llm, key="btn_generar_llm", use_container_width=True):
                            _ejecutar_llm_con_fallback(features, metadatos=metadatos_informe)
                            st.rerun()
                    else:
                        st.warning("Configura una API key en la barra lateral o activa Ollama para usar el contraste con IA.")

                with bar_col2:
                    pdf_bytes = reporte_pdf.generar_pdf_consolidado(
                        features=features,
                        informe_plantilla=informe_plantilla,
                        informe_llm=st.session_state.get("informe_llm"),
                        metadatos=metadatos_informe,
                        overlay_img=resultado.overlay,
                        modelo_llm=st.session_state.get("modelo_usado_llm") or modelo_seleccionado,
                    )
                    nombre_pdf = _nombre_archivo_anonimizado(
                        "_reporte_consolidado.pdf", id_caso=id_caso_actual, fecha_hora=fecha_caso_actual
                    )
                    st.download_button(
                        "📄 Descargar Reporte Consolidado en PDF (Plantilla + IA + Trazado)",
                        data=pdf_bytes,
                        file_name=nombre_pdf,
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True,
                        key="dl_reporte_pdf",
                    )

                tab_comp, tab_plantilla, tab_llm = st.tabs([
                    "⚖️ Comparación Ordenada por Dimensión (Plantilla vs. IA)",
                    "📋 Informe Completo por Plantilla (Sin IA)",
                    "🤖 Informe Completo con IA (LLM)",
                ])

                with tab_comp:
                    sec_plantilla = prompts.extraer_secciones_informe(informe_plantilla)
                    informe_llm_actual = st.session_state.get("informe_llm")
                    sec_llm = prompts.extraer_secciones_informe(informe_llm_actual)

                    enc_izq, enc_der = st.columns(2)
                    enc_izq.markdown("##### 📋 A. Informe Determinístico (Plantilla FIGO/NICE)")
                    enc_der.markdown(
                        f"##### 🤖 B. Informe Asistido por IA (`{st.session_state.get('modelo_usado_llm') or modelo_seleccionado}`)"
                    )
                    if not informe_llm_actual:
                        st.info(
                            "💡 El **Informe por Plantilla (izquierda)** ya está calculado. Pulsa el botón "
                            "**«✨ Generar análisis con IA (LLM)»** arriba para completar las tarjetas de la derecha "
                            "y comparar cómo ambos enfoques llegan a sus conclusiones."
                        )

                    for clave_dim, titulo_dim in prompts.DIMENSIONES_COMPARACION:
                        st.markdown(f"**{titulo_dim}**")
                        c_izq, c_der = st.columns(2)
                        with c_izq.container(border=True):
                            st.markdown(sec_plantilla.get(clave_dim, ""))
                        with c_der.container(border=True):
                            st.markdown(sec_llm.get(clave_dim, ""))

                with tab_plantilla:
                    with st.container(border=True):
                        st.markdown(informe_plantilla)
                    nombre_md_plantilla = _nombre_archivo_anonimizado(
                        "_informe_plantilla.md", id_caso=id_caso_actual, fecha_hora=fecha_caso_actual
                    )
                    st.download_button(
                        "⬇️ Descargar informe por plantilla (.md)",
                        data=informe_plantilla,
                        file_name=nombre_md_plantilla,
                        mime="text/markdown",
                        key="dl_informe_plantilla",
                    )

                with tab_llm:
                    if st.session_state.get("informe_llm"):
                        with st.container(border=True):
                            st.markdown(st.session_state.informe_llm)
                        nombre_md_llm = _nombre_archivo_anonimizado(
                            "_informe_llm.md", id_caso=id_caso_actual, fecha_hora=fecha_caso_actual
                        )
                        st.download_button(
                            "⬇️ Descargar informe IA (.md)",
                            data=st.session_state.informe_llm,
                            file_name=nombre_md_llm,
                            mime="text/markdown",
                            key="dl_informe_llm",
                        )
                    else:
                        st.info("Genera primero el análisis con IA usando el botón superior.")
