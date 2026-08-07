@echo off
REM Builds ScholarDesk.exe - a single file, no Python install required to run it.
REM Run this once on Windows, in this folder, after `pip install -r requirements.txt`.

pip install pyinstaller
if errorlevel 1 (
    echo.
    echo pip install pyinstaller FAILED. See the error above. Stopping.
    pause
    exit /b 1
)

REM Using "python -m PyInstaller" instead of the bare "pyinstaller" command
REM on purpose: pip installs the pyinstaller.exe launcher into a Scripts
REM folder that is NOT guaranteed to be on PATH (this bit us once already -
REM pip prints a warning about it during install, easy to miss). Calling it
REM as a Python module instead only requires "python" itself to be on PATH,
REM which it already is if pip just ran successfully above.
python -m PyInstaller --onefile --name ScholarDesk ^
  --add-data "app/templates;app/templates" ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols ^
  --hidden-import uvicorn.protocols.http ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.lifespan ^
  --hidden-import uvicorn.lifespan.on ^
  run.py

if errorlevel 1 (
    echo.
    echo BUILD FAILED - see the PyInstaller output above for the actual error.
    echo dist\ScholarDesk.exe was NOT created.
    pause
    exit /b 1
)

if not exist "dist\ScholarDesk.exe" (
    echo.
    echo Build reported success but dist\ScholarDesk.exe is missing.
    echo Something unexpected happened - do not trust this build.
    pause
    exit /b 1
)

echo.
echo Build succeeded. dist\ScholarDesk.exe exists and is ready to use.
echo Copy it anywhere you like - grants.db will be created next to wherever
echo the .exe lives, the first time you run it.
pause
