from src.llm_client import get_llm_client

# Usamos tu arquitectura modular
client, _ = get_llm_client()

# Pedimos la lista real de modelos disponibles
try:
    models = client.models.list()
    print("Modelos encontrados en tu cuenta:")
    for m in models.data:
        # Filtramos para mostrar solo los de google o anthropic
        if "google" in m.id or "anthropic" in m.id:
            print(f"- {m.id}")
except Exception as e:
    print(f"Error: {e}")