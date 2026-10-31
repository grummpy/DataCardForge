@echo off
setlocal
cd /d "%~dp0"
if not exist "art\icon.png" goto missingart
if not exist "art\cover.png" goto missingart
echo Using icon art\icon.png
echo Using cover art\cover.png
if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>&1 && (py -3 -m venv .venv) || (python -m venv .venv)
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
start "" /MIN cmd /c "ping -n 3 127.0.0.1 >nul & start http://127.0.0.1:8767"
python -m datacardforge
exit /b %ERRORLEVEL%
:missingart
echo DataCardForge needs art\icon.png and art\cover.png next to this launcher.
exit /b 1
