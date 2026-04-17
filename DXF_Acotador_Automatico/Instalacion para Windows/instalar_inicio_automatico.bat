@echo off
:: ============================================================
::  DXF WATCHER — Instalador de inicio automático (Windows)
::  Ejecuta como Administrador si da problemas.
:: ============================================================
title Instalar DXF Watcher al inicio

cd /d "%~dp0"

:: Buscar pythonw.exe para ejecutar sin ventana de consola
for /f "tokens=*" %%i in ('python -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set PYTHONW=%%i

if not exist "%PYTHONW%" (
    echo No se encontro pythonw.exe. Usando python.exe...
    for /f "tokens=*" %%i in ('python -c "import sys; print(sys.executable)"') do set PYTHONW=%%i
)

set SCRIPT="%~dp0dxf_watcher.py"
set CONFIG="%~dp0watcher_config.json"
set TASK_NAME=DXF_Watcher

echo.
echo Instalando tarea programada: %TASK_NAME%
echo Script  : %SCRIPT%
echo Config  : %CONFIG%
echo Python  : %PYTHONW%
echo.

:: Crear tarea en el Programador de Tareas de Windows
:: Se ejecuta al iniciar sesión, sin ventana visible
schtasks /create /tn "%TASK_NAME%" /tr "\"%PYTHONW%\" %SCRIPT% --config %CONFIG%" /sc onlogon /rl limited /f >nul 2>&1

if errorlevel 1 (
    echo Intentando con privilegios elevados...
    :: Crear shortcut en la carpeta de inicio como alternativa
    set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup

    echo Set oWS = WScript.CreateObject("WScript.Shell") > "%TEMP%\crear_shortcut.vbs"
    echo sLinkFile = "%STARTUP%\DXF_Watcher.lnk" >> "%TEMP%\crear_shortcut.vbs"
    echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%TEMP%\crear_shortcut.vbs"
    echo oLink.TargetPath = "%PYTHONW%" >> "%TEMP%\crear_shortcut.vbs"
    echo oLink.Arguments = "%SCRIPT% --config %CONFIG%" >> "%TEMP%\crear_shortcut.vbs"
    echo oLink.WorkingDirectory = "%~dp0" >> "%TEMP%\crear_shortcut.vbs"
    echo oLink.Description = "DXF Watcher - Generador automatico de PDFs" >> "%TEMP%\crear_shortcut.vbs"
    echo oLink.WindowStyle = 7 >> "%TEMP%\crear_shortcut.vbs"
    echo oLink.Save >> "%TEMP%\crear_shortcut.vbs"

    cscript //nologo "%TEMP%\crear_shortcut.vbs"
    del "%TEMP%\crear_shortcut.vbs"

    echo Acceso directo creado en la carpeta de inicio:
    echo %STARTUP%\DXF_Watcher.lnk
) else (
    echo Tarea programada creada correctamente.
    echo El watcher se iniciara automaticamente al iniciar sesion.
)

echo.
echo Para desinstalar ejecuta: schtasks /delete /tn "%TASK_NAME%" /f
echo.
pause
