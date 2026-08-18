"""Dashboard Streamlit para el Asesor Clínico MEFI."""

import os
import fitz  # PyMuPDF para convertir PDFs a imágenes compatibles con modelos locales
import yaml
import streamlit as st
from openai import (
    APIConnectionError,
    AuthenticationError,
    NotFoundError,
    OpenAI,
    RateLimitError,
)
from dotenv import load_dotenv
from streamlit_image_coordinates import streamlit_image_coordinates

import clinical
import prompts
from digitizer import (
    calibrar_desde_dos_puntos,
    detectar_anotaciones_clinicas,
    digitalizar_con_calibracion,
    extraer_metadatos_cabecera,
    preparar_imagen,
)

load_dotenv()

st.set_page_config(page_title="Asesor Clínico MEFI", layout="centered")

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

CONFIG_PATH = "config.yaml" if os.path.exists("config.yaml") else os.path.join("..", "config.yaml")
ENV_PATH = ".env" if os.path.exists(".env") or not os.path.exists(os.path.join("..", ".env")) else os.path.join("..", ".env")


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


def generar_informe_clinico(features, client, modelo):
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
            {"role": "user", "content": prompts.construir_prompt_usuario(features)},
        ],
    )
    return _limpiar_bloque_codigo(respuesta.choices[0].message.content)


def _imagen_bytes_desde_archivo(archivo_subido, extension):
    if extension == ".pdf":
        doc = fitz.open(stream=archivo_subido.getvalue(), filetype="pdf")
        if len(doc) == 0:
            raise ValueError("El archivo PDF está vacío o no es legible.")
        pix = doc[0].get_pixmap(dpi=DPI_RENDER_PDF)
        return pix.tobytes("png"), DPI_RENDER_PDF
    return archivo_subido.getvalue(), DPI_RENDER_PDF  # aprox. para fotos: no traen DPI real


ANCHO_ZOOM_PX = 1400  # cuanto ancho de imagen ORIGINAL entra en la ventana de zoom


def _panel_recortado(prep, panel, x0, x1, ancho_mostrado=900):
    recorte = prep.imagen.crop((x0, panel.y0, x1, panel.y1))
    escala = recorte.width / ancho_mostrado
    mostrado = recorte.resize((ancho_mostrado, max(1, int(recorte.height / escala))))
    return mostrado, escala


def _selector_zoom(prep):
    """Botones Anterior/Siguiente compartidos (mismo eje de tiempo en ambos paneles) para
    elegir qué franja horizontal ver de cerca — necesario en trazados largos (varios
    segmentos de papel), donde mostrar todo el ancho de una vez deja la grilla y los
    números ilegibles. Se usan botones en vez de un slider: con dos widgets
    streamlit_image_coordinates en la misma página (FCF y UA), el slider quedaba pegado
    en 0 por conflicto de estado entre componentes."""
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


def _widget_calibracion(prep, panel, nombre, valor_default_1, valor_default_2, key_prefix, x0, x1):
    """Muestra el panel recortado (en la ventana de zoom x0:x1), captura hasta 2 clics
    (streamlit_image_coordinates) y dos number_input con el valor clínico real de cada punto.
    Devuelve CalibracionEje o None."""
    st.markdown(f"**Calibración eje {nombre}** — hacé clic en dos líneas de grilla de valor conocido.")
    clics_key = f"{key_prefix}_clics"
    if clics_key not in st.session_state:
        st.session_state[clics_key] = []

    mostrado, escala = _panel_recortado(prep, panel, x0, x1)
    coords = streamlit_image_coordinates(mostrado, key=f"{key_prefix}_img_{x0}")
    if coords is not None:
        y_abs = coords["y"] * escala + panel.y0
        clics = st.session_state[clics_key]
        if not clics or abs(clics[-1] - y_abs) > 1:
            if len(clics) >= 2:
                clics = []
            clics.append(y_abs)
            st.session_state[clics_key] = clics

    clics = st.session_state[clics_key]
    col1, col2, col3 = st.columns(3)
    valor1 = col1.number_input(f"Valor punto 1 ({nombre})", value=valor_default_1, key=f"{key_prefix}_v1")
    valor2 = col2.number_input(f"Valor punto 2 ({nombre})", value=valor_default_2, key=f"{key_prefix}_v2")
    col3.metric("Puntos marcados", f"{len(clics)}/2")
    if col3.button("Reiniciar puntos", key=f"{key_prefix}_reset"):
        st.session_state[clics_key] = []
        st.rerun()

    if len(clics) == 2:
        return calibrar_desde_dos_puntos(clics[0], valor1, clics[1], valor2, panel)
    return None


# --- INTERFAZ PRINCIPAL ---
archivo_subido = st.file_uploader(
    "Sube un CSV (columnas 'tiempo' y 'fcf') o una imagen/PDF del trazado CTG",
    type=["csv", "jpg", "jpeg", "png", "pdf"],
)

if archivo_subido is not None:
    os.makedirs("data", exist_ok=True)
    extension = os.path.splitext(archivo_subido.name)[1].lower()

    if extension == ".csv":
        try:
            ruta_destino = os.path.join("data", archivo_subido.name)
            with open(ruta_destino, "wb") as f:
                f.write(archivo_subido.getbuffer())
            resultado = procesar_mefi(archivo_subido.name)
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
            st.session_state.fcf_clics = []
            st.session_state.ua_clics = []
            st.session_state.pop("resultado_digitalizacion", None)
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

        meta = st.session_state.get("metadatos_cabecera")
        if meta is not None:
            with st.expander("Metadatos de cabecera (leídos por OCR — revisar y corregir)"):
                st.caption(
                    "Lectura automática de mejor esfuerzo sobre la cabecera del papel — "
                    "no es confiable al 100%, se procesa localmente y no se envía a ningún "
                    "proveedor LLM. Corregí los campos antes de usarlos."
                )
                c1, c2 = st.columns(2)
                c1.text_input("ID de registro", value=meta.get("id") or "", key="meta_id")
                c1.number_input("FHR impreso (bpm)", value=meta.get("fhr_bpm") or 0, key="meta_fhr")
                c2.text_input("Fecha/hora de inicio", value=meta.get("fecha_hora") or "", key="meta_fecha")
                c2.number_input(
                    "Velocidad de papel (cm/min)",
                    value=meta.get("velocidad_papel_cm_min") or 1.0,
                    key="meta_velocidad",
                )

        st.subheader("1. Calibración manual del trazado")
        st.caption(
            "El OCR automático de las etiquetas del eje no es confiable en fotos/escaneos "
            "reales — se calibra marcando 2 puntos de referencia conocidos por panel."
        )
        x0_zoom, x1_zoom = _selector_zoom(prep)
        cal_fcf = _widget_calibracion(prep, prep.panel_fcf, "FCF (lpm)", 210, 30, "fcf", x0_zoom, x1_zoom)
        cal_ua = _widget_calibracion(prep, prep.panel_ua, "UA", 100, 0, "ua", x0_zoom, x1_zoom)

        if cal_fcf is not None and cal_ua is not None:
            if st.button("Digitalizar trazado", type="primary"):
                with st.spinner("Extrayendo curvas FCF/UA..."):
                    st.session_state.resultado_digitalizacion = digitalizar_con_calibracion(
                        prep, cal_fcf, cal_ua
                    )

        if "resultado_digitalizacion" in st.session_state:
            resultado = st.session_state.resultado_digitalizacion
            st.subheader("2. Curva digitalizada (auditoría)")
            st.image(
                resultado.overlay,
                caption="Celeste = lectura directa · Naranja = tramo reconstruido por interpolación",
            )
            for adv in resultado.advertencias:
                st.info(adv)

            nombre_csv = os.path.splitext(archivo_subido.name)[0] + "_extraido.csv"
            ruta_destino = os.path.join("data", nombre_csv)
            resultado.df.to_csv(ruta_destino, index=False)
            with st.expander("Ver CSV digitalizado"):
                st.dataframe(resultado.df)

            st.subheader("3. Clasificación clínica (FIGO 2015 / NICE NG229)")
            try:
                features = clinical.extraer_features(resultado.df)
            except ValueError as e:
                features = None
                st.error(f"No se pudo calcular la clasificación clínica: {e}")

            if features is not None:
                figo = features["figo"]
                color_semaforo = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴"}
                st.markdown(f"**Categoría FIGO {figo['categoria']} — {figo['descripcion']}**")
                st.caption(" · ".join(figo["razones"]))
                st.table({
                    "Variable": ["Línea base", "Variabilidad", "Aceleraciones", "Desaceleraciones", "Patrón sinusoidal"],
                    "Valor": [
                        f"{features['linea_base']:.0f} lpm",
                        f"{features['variabilidad']['amplitud_media_lpm']} lpm ({features['variabilidad']['categoria']})",
                        f"{len(features['aceleraciones'])} detectada(s)",
                        f"{len(features['desaceleraciones'])} detectada(s)",
                        "presente" if features["patron_sinusoidal"]["presente"] else "no detectado",
                    ],
                    "Semáforo NICE": [
                        color_semaforo[figo["semaforo_nice"]["linea_base"]],
                        color_semaforo[figo["semaforo_nice"]["variabilidad"]],
                        "—",
                        color_semaforo[figo["semaforo_nice"]["desaceleraciones"]],
                        "—",
                    ],
                })
                with st.expander("Ver desaceleraciones detectadas en detalle"):
                    st.json(features["desaceleraciones"])

            if client is not None and features is not None:
                if st.button("Generar informe clínico con LLM"):
                    modelos_gratis = [m for m in modelos_texto_disponibles if m.endswith(":free")]
                    # Candidatos a probar en orden: el modelo elegido primero, y si es uno de
                    # los gratis y se satura (429), se sigue con los demás gratis automático
                    # (nunca se salta solo a uno de pago sin que el usuario lo elija a mano).
                    if prov_key == "openrouter" and modelo_seleccionado in modelos_gratis:
                        candidatos = [modelo_seleccionado] + [m for m in modelos_gratis if m != modelo_seleccionado]
                    else:
                        candidatos = [modelo_seleccionado]

                    informe_clinico = None
                    for i, modelo_intento in enumerate(candidatos):
                        try:
                            with st.spinner(f"Analizando con {modelo_intento}..."):
                                informe_clinico = generar_informe_clinico(features, client, modelo_intento)
                            if i > 0:
                                st.caption(f"({modelo_seleccionado} estaba saturado — se usó {modelo_intento} en su lugar)")
                            break
                        except RateLimitError as e:
                            if i < len(candidatos) - 1:
                                st.info(f"{modelo_intento} saturado (límite de uso gratis) — probando con {candidatos[i+1]}...")
                                continue
                            st.error(
                                f"Todos los modelos gratis están saturados ahora mismo. "
                                f"Esperá un momento y reintentá, o elegí un modelo de pago en la barra lateral.\n\n{e}"
                            )
                        except NotFoundError as e:
                            st.error(
                                f"El modelo `{modelo_intento}` ya no existe en OpenRouter — revisá "
                                f"`config.yaml` contra https://openrouter.ai/models.\n\n{e}"
                            )
                            break
                        except AuthenticationError as e:
                            st.error(f"Problema de autenticación con {prov_key.upper()} — revisá la API key en `.env`.\n\n{e}")
                            break
                        except APIConnectionError as e:
                            sugerencia = (
                                f"Confirmá que Ollama esté corriendo (`ollama serve`) y que el "
                                f"modelo esté descargado (`ollama pull {modelo_intento}`)."
                                if prov_key == "ollama" else
                                "No se pudo conectar a OpenRouter — revisá tu conexión a internet."
                            )
                            st.error(f"Error de conexión con {prov_key.upper()}: {e}\n\n{sugerencia}")
                            break
                        except Exception as e:
                            st.error(f"Error al generar el informe con {modelo_intento}: {e}")
                            break

                    if informe_clinico:
                        st.subheader("Análisis Clínico del Asesor")
                        st.markdown(informe_clinico)
            elif client is None:
                st.warning("Sin cliente LLM configurado — revisa la barra lateral para generar el informe.")