import os
import yaml
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

def cargar_config():
    """Carga la configuración desde el archivo config.yaml"""
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    if not os.path.exists(config_path):
        # Intentar ruta alternativa si se ejecuta desde la raíz
        config_path = "config.yaml"
    
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
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("⚠️ Se requiere una OPENROUTER_API_KEY en el archivo .env para usar OpenRouter.")
    else:
        api_key = "ollama-local-key" # Ollama no valida llave real, pero el SDK exige un string

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