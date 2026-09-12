@echo off
echo === ScholarDesk Build ===
echo.

cd /d "%~dp0"

echo [1/7] Preparing isolated build workspace...
if exist "build" rmdir /s /q "build"
if exist "build" (
    echo Could not clean the build workspace. Close any process using it and try again.
    goto :error
)
mkdir "build" || (
    echo Could not create the build workspace.
    goto :error
)

set "PYTHONUSERBASE=%CD%\build\python-user-base"
set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"
set "VENV_RUFF=%CD%\.venv\Scripts\ruff.exe"

if not exist "%VENV_PYTHON%" (
    echo Virtual environment not found: %VENV_PYTHON%
    echo Create it with: py -3.13 -m venv .venv
    goto :error
)

echo [2/7] Running ruff...
"%VENV_RUFF%" check app tests *.py || goto :error

echo [3/7] Checking dependency integrity...
"%VENV_PYTHON%" -m pip check || goto :error

echo [4/7] Running tests...
"%VENV_PYTHON%" -m pytest -v --basetemp ".\build\pytest-tmp" || goto :error

echo [5/7] Building staged PyInstaller executables...
"%VENV_PYTHON%" -m PyInstaller ScholarDesk.spec --clean --noconfirm ^
    --distpath ".\build\release-stage\dist" ^
    --workpath ".\build\pyinstaller-work" || goto :error

echo [6/7] Writing release checksums...
"%VENV_PYTHON%" write_release_checksums.py ".\build\release-stage\dist" || goto :error

echo [7/7] Publishing the staged release...
if exist "build\previous-dist" rmdir /s /q "build\previous-dist"
if exist "dist" move "dist" "build\previous-dist" || goto :error
move "build\release-stage\dist" "dist" || goto :restore_previous_release
if exist "build\previous-dist" rmdir /s /q "build\previous-dist"

echo.
echo === BUILD SUCCESS ===
echo Output: dist\ScholarDesk.exe and dist\ScholarDeskAdmin.exe
goto :eof

:error
echo.
echo === BUILD FAILED ===
exit /b 1

:restore_previous_release
echo.
echo Publish failed. Restoring the previous release...
if exist "build\previous-dist" move "build\previous-dist" "dist"
goto :error
