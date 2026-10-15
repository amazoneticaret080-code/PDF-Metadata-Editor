@echo off
REM Programi Python ile calistirir (gerekirse kutuphaneleri kurar)
cd /d "%~dp0"
set "PY=python"
set "PYW=pythonw"
where python >nul 2>nul
if errorlevel 1 (
  set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
)
"%PY%" -c "import pikepdf, PySide6, pyhanko, fontTools" 2>nul || "%PY%" -m pip install -r requirements.txt
start "" "%PYW%" main.py %*
