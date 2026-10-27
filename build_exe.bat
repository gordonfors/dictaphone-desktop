@echo off
setlocal
cd /d "%~dp0"

if exist ".\.venv\Scripts\activate.bat" (
    call ".\.venv\Scripts\activate.bat"
)

python build.py
if errorlevel 1 (
    echo [Error] PyInstaller build failed!
    pause
    exit /b %errorlevel%
)

set "MAKENSIS="
if exist ".tools\nsis\nsis-3.10\makensis.exe" set "MAKENSIS=.tools\nsis\nsis-3.10\makensis.exe"
if exist "C:\Program Files (x86)\NSIS\makensis.exe" set "MAKENSIS=C:\Program Files (x86)\NSIS\makensis.exe"
if exist "C:\Program Files\NSIS\makensis.exe" set "MAKENSIS=C:\Program Files\NSIS\makensis.exe"
if not defined MAKENSIS (
    where makensis >nul 2>nul
    if %errorlevel% equ 0 set "MAKENSIS=makensis"
)

if defined MAKENSIS (
    echo.
    echo ========================================================
    echo [Installer] Building Windows installer via NSIS...
    echo ========================================================
    "%MAKENSIS%" /INPUTCHARSET UTF8 installer.nsi
    if errorlevel 1 (
        echo [Warning] NSIS installer build failed!
    ) else (
        echo [Installer] Installer successfully created in dist\DictaphoneSetup.exe
    )
) else (
    echo [Info] makensis.exe not found. Skipping installer build.
)

pause
