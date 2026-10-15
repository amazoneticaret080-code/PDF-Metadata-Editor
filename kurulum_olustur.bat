@echo off
REM Kursiyerlere gonderilecek kurulum dosyasini olusturur -> dist\PDFMetadataDuzenleyici_Kurulum_<surum>.exe
REM Gereken: Python (kutuphaneler otomatik kurulur) ve Inno Setup 6 (winget install JRSoftware.InnoSetup)
cd /d "%~dp0"
set "PY=python"
where python >nul 2>nul || set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"

set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo Inno Setup bulunamadi. Kurmak icin: winget install JRSoftware.InnoSetup
  pause
  exit /b 1
)

"%PY%" -m pip install -r requirements.txt pyinstaller
REM klasor derlemesi: tek dosyali exe'den hizli acilir, kurulum icin uygundur
"%PY%" -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --distpath build\uygulama --workpath build\pyinstaller ^
  --name PDFMetadataDuzenleyici ^
  --icon pdfmeta\assets\app.ico ^
  --add-data "pdfmeta\assets;pdfmeta\assets" ^
  --collect-submodules pikepdf ^
  --collect-all pyhanko ^
  --collect-all pyhanko_certvalidator ^
  --collect-all uharfbuzz ^
  --collect-submodules fontTools ^
  main.py || (pause & exit /b 1)

"%ISCC%" installer\kurulum.iss || (pause & exit /b 1)
echo.
echo Hazir: dist klasorundeki PDFMetadataDuzenleyici_Kurulum_*.exe dosyasini gonderebilirsiniz.
pause
