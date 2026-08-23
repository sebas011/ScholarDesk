@echo off
echo === ScholarDesk Build ===
echo.

cd /d "%~dp0"

echo [1/4] Cleaning old builds...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

echo [2/4] Running ruff...
ruff check . || goto :error

echo [3/4] Running tests...
pytest -v || goto :error

echo [4/4] Building PyInstaller executable...
pyinstaller ScholarDesk.spec --clean --noconfirm || goto :error

echo.
echo === BUILD SUCCESS ===
echo Output: dist\ScholarDesk.exe
goto :eof

:error
echo.
echo === BUILD FAILED ===
exit /b 1