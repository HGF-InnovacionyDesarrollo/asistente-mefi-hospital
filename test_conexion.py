import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Configuración básica
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

try:
    # Intentamos listar modelos para probar conexión
    models = client.models.list()
    print("¡Conexión exitosa! Puedes hablar con OpenRouter.")
except Exception as e:
    print(f"Error de conexión: {e}")