"""Resolución de rutas del sistema, independiente del directorio de trabajo.

Dos modos de operación:

- **Desarrollo** (repo): `MEFI_HOME` no está definido; datos, config y `.env`
  viven en la raíz del proyecto, como históricamente.
- **Instalado/portable** (el `MEFI.bat` del bundle define `MEFI_HOME`):
  apunta a un directorio escribible por el usuario (`%LOCALAPPDATA%\\MEFI`),
  útil cuando la app vive en una carpeta de solo lectura (p. ej. Archivos de
  programa). La app siembra ahí `config.yaml`, `.env` y `data/` la primera
  vez (`sembrar_home()`) y después lee/escribe solo en ese lugar.

La raíz se ancla a la ubicación de este archivo (no al cwd): da igual desde
qué directorio se lance streamlit.
"""

import os
import shutil
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

_env_home = os.environ.get("MEFI_HOME", "").strip()
HOME = Path(_env_home) if _env_home else None


def en_modo_instalado() -> bool:
    return HOME is not None


def ruta_escritura(rel: str) -> Path:
    """Ruta escribible para datos/estado: MEFI_HOME si aplica, si no la raíz."""
    base = HOME if HOME else RAIZ
    destino = base / rel
    destino.parent.mkdir(parents=True, exist_ok=True)
    return destino


def ruta_lectura(rel: str) -> Path:
    """Config y plantillas: prioriza la copia de MEFI_HOME; si no existe,
    cae a la del bundle/raíz (la plantilla distribuida)."""
    if HOME is not None:
        local = HOME / rel
        if local.exists():
            return local
    return RAIZ / rel


def sembrar_home() -> None:
    """Primera corrida en modo instalado: copia config.yaml y .env plantilla
    y crea data/. Idempotente; en desarrollo no hace nada."""
    if HOME is None:
        return
    HOME.mkdir(parents=True, exist_ok=True)
    for rel in ("config.yaml", ".env"):
        plantilla = RAIZ / rel
        destino = HOME / rel
        if plantilla.exists() and not destino.exists():
            shutil.copy2(plantilla, destino)
    for rel in ("data/extracted", "data/tmp"):
        (HOME / rel).mkdir(parents=True, exist_ok=True)
