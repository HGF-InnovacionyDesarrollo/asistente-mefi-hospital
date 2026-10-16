#!/usr/bin/env python3
"""
Prueba de humo (oct 2026): corre el prompt real del MVP sobre un registro
CTU-UHB con Ollama local (qwen3:4b), mide tokens/segundo y compara dos
estratégias de generación del informe:

  A) Español directo  — system prompt de prompts.py tal cual.
  B) Inglés maestro + traducción al español con nota de "revisar por cambio
     de idioma" (la variante que se evalúa para el informe bilingüe).

Uso:
    python scripts/prueba_llm_local.py [--record-id 1001]

Requiere: servidor Ollama corriendo (ollama serve) y el modelo ya descargado
(ollama pull qwen3:4b). No toca la nube: todo va a localhost:11434.
"""

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "scripts"))

import clinical
import prompts
from validar_ctu_uhb import cargar_registro_ctu_uhb, convertir_a_dataframe

OLLAMA_URL = "http://localhost:11434/api/chat"
MODELO = "qwen3:4b"
SALIDA = RAIZ / "data" / "prueba_llm_local"
SALIDA.mkdir(parents=True, exist_ok=True)


def chat(system: str, user: str, num_ctx: int = 4096) -> dict:
    """Una llamada al chat de Ollama; devuelve dict con respuesta y métricas."""
    payload = {
        "model": MODELO,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"num_ctx": num_ctx, "temperature": 0.2},
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=3600) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    wall = time.time() - t0

    eval_count = data.get("eval_count", 0)
    eval_dur = data.get("eval_duration", 0)  # nanosegundos
    tok_s = (eval_count / (eval_dur / 1e9)) if eval_dur else None
    return {
        "respuesta": data["message"]["content"],
        "wall_s": round(wall, 1),
        "tokens_salida": eval_count,
        "tokens_por_seg": round(tok_s, 2) if tok_s else None,
        "tokens_entrada": data.get("prompt_eval_count"),
    }


SYSTEM_EN_MASTER = (
    prompts.SYSTEM_INSTRUCTIONS
    + "\n\n## 5. IDIOMA\nRedacta el informe completo en INGLÉS (English). "
    "Mantén la estructura Markdown y todos los disclaimers."
)

PROMPT_TRADUCCION = (
    "Traduce el siguiente informe clínico al español de forma fiel. "
    "Agrega como primera línea exactamente esta nota:\n"
    "> Traducción automática del informe maestro en inglés — "
    "revisar términos clínicos por cambio de idioma.\n\n"
    "No agregues ni quites contenido clínico; solo traduce.\n\n---\n\n"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-id", type=int, default=1001)
    args = parser.parse_args()

    print(f"[*] Cargando registro CTU-UHB {args.record_id}...")
    reg = cargar_registro_ctu_uhb(args.record_id, str(RAIZ / "data" / "ctu_uhb"))
    df = convertir_a_dataframe(reg["fcf_data"], reg["ua_data"], reg["fs"])
    features = clinical.extraer_features(df)
    print(f"  FIGO categoría {features['figo']['categoria']}, "
          f"basal {features['linea_base']:.0f} lpm, "
          f"{len(features['desaceleraciones'])} desaceleraciones.")

    user_prompt = prompts.construir_prompt_usuario(features)
    resultados = {"record_id": args.record_id, "modelo": MODELO, "casos": {}}

    # --- A) Español directo ---
    print("\n[A] Generando informe en ESPAÑOL DIRECTO (esto puede tardar varios minutos)...")
    r_a = chat(prompts.SYSTEM_INSTRUCTIONS, user_prompt)
    resultados["casos"]["es_directo"] = {k: v for k, v in r_a.items() if k != "respuesta"}
    (SALIDA / "informe_A_es_directo.md").write_text(r_a["respuesta"], encoding="utf-8")
    print(f"  ✓ {r_a['tokens_salida']} tokens en {r_a['wall_s']}s "
          f"({r_a['tokens_por_seg']} tok/s)")

    # --- B) Inglés maestro ---
    print("\n[B1] Generando informe MAESTRO EN INGLÉS...")
    r_b1 = chat(SYSTEM_EN_MASTER, user_prompt)
    resultados["casos"]["en_master"] = {k: v for k, v in r_b1.items() if k != "respuesta"}
    (SALIDA / "informe_B1_en_master.md").write_text(r_b1["respuesta"], encoding="utf-8")
    print(f"  ✓ {r_b1['tokens_salida']} tokens en {r_b1['wall_s']}s "
          f"({r_b1['tokens_por_seg']} tok/s)")

    print("\n[B2] Traduciendo al español...")
    r_b2 = chat(prompts.SYSTEM_INSTRUCTIONS, PROMPT_TRADUCCION + r_b1["respuesta"])
    resultados["casos"]["es_traduccion"] = {k: v for k, v in r_b2.items() if k != "respuesta"}
    (SALIDA / "informe_B2_es_traduccion.md").write_text(r_b2["respuesta"], encoding="utf-8")
    print(f"  ✓ {r_b2['tokens_salida']} tokens en {r_b2['wall_s']}s "
          f"({r_b2['tokens_por_seg']} tok/s)")

    (SALIDA / "metricas.json").write_text(
        json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 60)
    print("MÉTRICAS")
    print("=" * 60)
    print(json.dumps(resultados["casos"], indent=2, ensure_ascii=False))
    print(f"\n[*] Informes guardados en {SALIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
