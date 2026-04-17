@echo off
:: ============================================================
::  DXF WATCHER — Launcher para Windows
::  Doble clic para iniciar. Minimiza a la barra de tareas.
:: ============================================================
title DXF Watcher

:: Ir al directorio donde está este .bat
cd /d "%~dp0"

:: Comprobar si watchdog está instalado
python -c "import watchdog" 2>nul
if errorlevel 1 (
    echo Instalando dependencia "watchdog"...
    pip install watchdog
    if errorlevel 1 (
        echo ERROR: No se pudo instalar watchdog. Asegurate de tener Python en el PATH.
        pause
        exit /b 1
    )
)

echo.
echo  ====================================================
echo   DXF WATCHER  iniciado
echo   Edita watcher_config.json para cambiar la carpeta
echo   Cierra esta ventana o pulsa Ctrl+C para detener
echo  ====================================================
echo.

python dxf_watcher.py --config watcher_config.json
pause
