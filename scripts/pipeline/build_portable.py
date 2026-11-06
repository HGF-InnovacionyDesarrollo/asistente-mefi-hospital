#!/usr/bin/env python3
"""Construye el bundle portable de MEFI en dist/MEFI-portable/.

Contenido del bundle:
- python/  : distribucion embebida de Windows de Python (misma version
             mayor.menor que el interprete de desarrollo) con las
             dependencias de requirements.txt instaladas
- src/     : codigo de la aplicacion
- MEFI.bat : lanzador (usa python\\python.exe del bundle, sin venv)
- config.yaml, GUIA_PROFESIONALES.docx
- README.txt : instrucciones de uso del paquete

Requiere internet (descarga Python embebido, get-pip y las ruedas de las
dependencias). El resultado se distribuye como ZIP o se empaqueta con
Inno Setup (installer/mefi.iss) para producir un Setup.exe.

Uso:
    python scripts/pipeline/build_portable.py
"""

import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DESTINO = RAIZ / "dist" / "MEFI-portable"
FTP_PYTHON = "https://www.python.org/ftp/python/"
ARQUITECTURA = "amd64"
MAJOR_MENOR = f"{sys.version_info.major}.{sys.version_info.minor}"


def run(cmd: list[str]) -> None:
    print(f"[build] {' '.join(str(c) for c in cmd)}")
    subprocess.run([str(c) for c in cmd], check=True)


def descargar(url: str, destino: Path) -> None:
    print(f"[build] descargando {url}")
    with urllib.request.urlopen(url, timeout=120) as r, open(destino, "wb") as f:
        shutil.copyfileobj(r, f)


def version_embebida_disponible() -> str:
    """Mayor patch de MAJOR_MENOR publicado en python.org."""
    html = urllib.request.urlopen(FTP_PYTHON, timeout=30).read().decode()
    patches = re.findall(rf"{re.escape(MAJOR_MENOR)}\.(\d+)/", html)
    if not patches:
        raise SystemExit(f"No se encontraron versiones {MAJOR_MENOR}.x publicadas en python.org")
    return f"{MAJOR_MENOR}.{max(int(p) for p in patches)}"


def preparar_python() -> Path:
    ver = version_embebida_disponible()
    print(f"[build] Python embebido {ver}")
    tmp_zip = DESTINO / "_python-embed.zip"
    descargar(f"{FTP_PYTHON}{ver}/python-{ver}-embed-{ARQUITECTURA}.zip", tmp_zip)

    pydir = DESTINO / "python"
    if pydir.exists():
        shutil.rmtree(pydir)
    pydir.mkdir(parents=True)
    with zipfile.ZipFile(tmp_zip) as zf:
        zf.extractall(pydir)
    tmp_zip.unlink()

    # Habilitar site-packages en el ._pth (distribucion embebida viene cerrada)
    pth = next(pydir.glob(f"python*{MAJOR_MENOR.replace('.', '')}._pth"))
    contenido = pth.read_text(encoding="utf-8")
    if "import site" not in contenido:
        contenido = contenido.replace("#import site", "import site")
    if "Lib\\site-packages" not in contenido:
        contenido += "\nLib\\site-packages\n"
    pth.write_text(contenido, encoding="utf-8")
    return pydir


def instalar_dependencias(py_exe: Path) -> None:
    getpip = DESTINO / "_get-pip.py"
    descargar("https://bootstrap.pypa.io/get-pip.py", getpip)
    run([py_exe, getpip, "--no-warn-script-location"])
    getpip.unlink()
    run([py_exe, "-m", "pip", "install", "--no-warn-script-location", "-r", RAIZ / "requirements.txt"])


def _quitar_solo_lectura(func, path, _exc_info) -> None:
    import os
    import stat

    os.chmod(path, stat.S_IWRITE)
    func(path)


def copiar_aplicacion() -> None:
    import os
    import stat

    for item in ("src", "MEFI.bat", "config.yaml", ".env", "GUIA_PROFESIONALES.docx"):
        origen = RAIZ / item
        destino = DESTINO / item
        if not origen.exists():
            print(f"[build] AVISO: no existe {origen}, se omite")
            continue
        if destino.exists():
            if destino.is_dir():
                shutil.rmtree(destino, onexc=_quitar_solo_lectura)
            else:
                os.chmod(destino, stat.S_IWRITE)
                destino.unlink()
        if origen.is_dir():
            shutil.copytree(
                origen,
                destino,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                dirs_exist_ok=True,
            )
        else:
            shutil.copy2(origen, destino)

    (DESTINO / "README.txt").write_text(
        "ASESOR CLINICO MEFI - paquete portable\n"
        "========================================\n\n"
        "Uso: doble clic en MEFI.bat. No requiere Python instalado.\n\n"
        "- La primera corrida crea los datos de trabajo en\n"
        "  %LOCALAPPDATA%\\MEFI (config.yaml editable, .env, data/extracted/).\n"
        "- Tesseract OCR es opcional: para lectura automatica de etiquetas,\n"
        "  instalelo (winget install -e --id UB-Mannheim.TesseractOCR) o copie\n"
        "  una instalacion portable a la carpeta 'tesseract\\' junto a MEFI.bat.\n"
        "- Guia de usuario: GUIA_PROFESIONALES.docx\n\n"
        "Distribucion: ZIP directo o Setup.exe via installer/mefi.iss (Inno Setup).\n",
        encoding="utf-8",
    )


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    py_exe = DESTINO / "python" / "python.exe"
    if "--only-app" in sys.argv and py_exe.exists():
        print("[build] --only-app: reutilizando python/ existente en el bundle")
    else:
        pydir = preparar_python()
        instalar_dependencias(pydir / "python.exe")
    copiar_aplicacion()
    print(f"\n[build] OK: {DESTINO}")
    print("[build] Siguiente paso para Setup.exe: iscc installer\\mefi.iss (requiere Inno Setup)")


if __name__ == "__main__":
    main()
