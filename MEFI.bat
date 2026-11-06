@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Asesor Clinico MEFI

echo ============================================================
echo   ASESOR CLINICO MEFI - Hospital Gustavo Fricke
echo ============================================================
echo.

REM --- 1. Interprete de Python: bundle portable (python\) o entorno del repo ---
REM RUNPY lleva comillas propias cuando la ruta puede tener espacios.
set "RUNPY="
if exist "%~dp0python\python.exe" (
    set "RUNPY=""%~dp0python\python.exe"""
    if not defined MEFI_HOME set "MEFI_HOME=%LOCALAPPDATA%\MEFI"
    if exist "%~dp0tesseract\tesseract.exe" set "MEFI_TESSERACT=%~dp0tesseract\tesseract.exe"
    echo [OK] Python incluido en el paquete.
    goto :deps_ok
)

set "PYDETECT="
where py >nul 2>&1 && (py -3 -c "import sys" >nul 2>&1 && set "PYDETECT=py -3")
if not defined PYDETECT (
    where python >nul 2>&1 && (python -c "import sys" >nul 2>&1 && set "PYDETECT=python")
)
if not defined PYDETECT (
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
echo [OK] Python encontrado: %PYDETECT%

REM --- 2. Crear el entorno virtual la primera vez e instalar dependencias ---
if not exist "venv\Scripts\python.exe" (
    echo.
    echo [1/3] Primera ejecucion: creando entorno virtual...
    %PYDETECT% -m venv venv
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
set "RUNPY=venv\Scripts\python.exe"

:deps_ok
REM --- 3. Avisar si falta Tesseract OCR (opcional pero recomendado) ---
%RUNPY% -c "import pytesseract; pytesseract.get_tesseract_version()" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [AVISO] No se detecto Tesseract OCR. La app funciona igual, pero la
    echo         lectura automatica de etiquetas estara deshabilitada.
    echo         Para instalarlo ^(administrador^):  winget install -e --id UB-Mannheim.TesseractOCR
    echo.
)

echo [3/3] Iniciando la aplicacion ^(la primera vez puede tardar 15-30 segundos; el navegador se abrira automaticamente al estar lista^)...
set PYTHONIOENCODING=utf-8
%RUNPY% -m streamlit run src\app.py --server.port 8501 --server.headless false

echo.
echo La aplicacion se cerro. Esta ventana puede cerrarse.
pause
