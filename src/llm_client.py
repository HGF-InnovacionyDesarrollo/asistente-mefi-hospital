import os
import yaml
from openai import OpenAI
from dotenv import load_dotenv

import rutas

load_dotenv(rutas.ruta_escritura(".env"))

def cargar_config():
    """Carga la configuración desde config.yaml (copia de MEFI_HOME si aplica,
    si no la plantilla que acompaña al código)."""
    config_path = rutas.ruta_lectura("config.yaml")

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_llm_client():
    """
    Inicializa y retorna el cliente de OpenAI/OpenRouter o Ollama 
    basado en el proveedor activo en config.yaml.
    """
    config = cargar_config()
    proveedor_activo = config.get("active_provider", "ollama")
    prov_config = config["providers"][proveedor_activo]
    
    base_url = prov_config["base_url"]
    modelo = prov_config["model"]

    if prov_config.get("needs_api_key", False):
        api_key_env = prov_config.get("api_key_env")
        api_key = os.getenv(api_key_env) if api_key_env else None
        if not api_key:
            raise ValueError(
                f"⚠️ Se requiere la variable {api_key_env} en el archivo .env para usar "
                f"{prov_config.get('label', proveedor_activo)}."
            )
    else:
        api_key = "local-key" # Proveedores locales no validan llave real, pero el SDK exige un string

    client = OpenAI(
        base_url=base_url,
        api_key=api_key
    )
    
    return client, modelo

def get_vision_models():
    """Retorna la lista de modelos de visión disponibles según el proveedor activo."""
    config = cargar_config()
    proveedor_activo = config.get("active_provider", "ollama")
    return config["providers"][proveedor_activo].get("vision_models", [])