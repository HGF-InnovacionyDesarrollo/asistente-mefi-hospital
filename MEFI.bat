@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Asesor Clinico MEFI

echo ============================================================
echo   ASESOR CLINICO MEFI - Instalacion y arranque
echo ============================================================
echo.

REM --- 1. Buscar un interprete de Python instalado en el equipo ---
REM (se usa "&&" y no %errorlevel% dentro de bloques: %errorlevel% se
REM  expande antes de ejecutar el bloque y quedaria con el valor viejo)
set "PY="
where py >nul 2>&1 && (py -3 -c "import sys" >nul 2>&1 && set "PY=py -3")
if not defined PY (
    where python >nul 2>&1 && (python -c "import sys" >nul 2>&1 && set "PY=python")
)
if not defined PY (
    echo [ERROR] No se encontro Python instalado.
    echo.
    echo Para instalarlo ^(una sola vez, con derechos de administrador^):
    echo   1. Abra "Terminal" o "PowerShell" como administrador
    echo   2. Ejecute:  winget install -e --id Python.Python.3.12
    echo   3. Cierre esta ventana y vuelva a hacer doble clic en MEFI.bat
    echo.
    pause
    exit /b 1
)
echo [OK] Python encontrado: %PY%

REM --- 2. Crear el entorno virtual la primera vez e instalar dependencias ---
if not exist "venv\Scripts\python.exe" (
    echo.
    echo [1/3] Primera ejecucion: creando entorno virtual...
    %PY% -m venv venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
)
if not exist "venv\.listo" (
    echo [2/3] Instalando dependencias ^(puede tardar varios minutos^)...
    venv\Scripts\python.exe -m pip install --upgrade pip
    venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Fallo la instalacion de dependencias. Revise su conexion a internet.
        pause
        exit /b 1
    )
    echo ok > venv\.listo
) else (
    echo [OK] Dependencias ya instaladas - se omite la instalacion.
)

REM --- 3. Avisar si falta Tesseract OCR (opcional pero recomendado) ---
venv\Scripts\python.exe -c "import pytesseract; pytesseract.get_tesseract_version()" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [AVISO] No se detecto Tesseract OCR. La app funciona igual, pero la
    echo         lectura automatica de etiquetas estara deshabilitada.
    echo         Para instalarlo ^(administrador^):  winget install -e --id UB-Mannheim.TesseractOCR
    echo.
)

echo [3/3] Abriendo la aplicacion en el navegador...
set PYTHONIOENCODING=utf-8
start "" http://localhost:8501
%SystemRoot%\System32\timeout.exe /t 5 /nobreak >nul 2>&1
if errorlevel 1 ping -n 6 127.0.0.1 >nul
venv\Scripts\python.exe -m streamlit run src\app.py --server.port 8501

echo.
echo La aplicacion se cerro. Esta ventana puede cerrarse.
pause
