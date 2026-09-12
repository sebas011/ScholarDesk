@echo off
echo === ScholarDesk Build ===
echo.

cd /d "%~dp0"

echo [1/4] Cleaning old builds...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

set "PYTHONUSERBASE=%CD%\build\python-user-base"
set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"
set "VENV_RUFF=%CD%\.venv\Scripts\ruff.exe"
set "VENV_PYINSTALLER=%CD%\.venv\Scripts\pyinstaller.exe"

if not exist "%VENV_PYTHON%" (
    echo Virtual environment not found: %VENV_PYTHON%
    echo Create it with: py -3.13 -m venv .venv
    goto :error
)

echo [2/4] Running ruff...
"%VENV_RUFF%" check . || goto :error

echo [3/4] Running tests...
"%VENV_PYTHON%" -m pytest -v --basetemp ".\build\pytest-tmp" || goto :error

echo [4/4] Building PyInstaller executable...
"%VENV_PYINSTALLER%" ScholarDesk.spec --clean --noconfirm || goto :error

echo.
echo === BUILD SUCCESS ===
echo Output: dist\ScholarDesk.exe and dist\ScholarDeskAdmin.exe
goto :eof

:error
echo.
echo === BUILD FAILED ===
exit /b 1
