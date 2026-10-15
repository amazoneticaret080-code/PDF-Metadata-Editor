@echo off
REM Tek dosyalik, kurulumsuz calisan .exe olusturur -> dist\PDFMetadataDuzenleyici.exe
cd /d "%~dp0"
set "PY=python"
where python >nul 2>nul || set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
"%PY%" -m pip install -r requirements.txt pyinstaller
"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name PDFMetadataDuzenleyici ^
  --icon pdfmeta\assets\app.ico ^
  --add-data "pdfmeta\assets;pdfmeta\assets" ^
  --collect-submodules pikepdf ^
  --collect-all pyhanko ^
  --collect-all pyhanko_certvalidator ^
  --collect-all uharfbuzz ^
  --collect-submodules fontTools ^
  main.py
echo.
echo Hazir: dist\PDFMetadataDuzenleyici.exe
pause
