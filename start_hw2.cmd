@echo off
setlocal
cd /d "%~dp0"
set "HW2_PYTHON=%~dp0.venv-hw2\Scripts\python.exe"
set "PYTHONPYCACHEPREFIX=%~dp0tmp\pycache-hw2"
set "MPLCONFIGDIR=%~dp0tmp\matplotlib"
if not exist "%HW2_PYTHON%" goto failed
"%HW2_PYTHON%" -X utf8 -c "import sys; from gensim.models import Word2Vec; import streamlit; import matplotlib; print('HW2 Python: ' + sys.executable)"
if errorlevel 1 goto failed
echo Open http://127.0.0.1:8501 in your browser. Keep this window open.
"%HW2_PYTHON%" -X utf8 -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
if errorlevel 1 goto failed
exit /b 0

:failed
echo HW2 could not start. Review the error above.
echo Missing packages: run .\scripts\setup_hw2.ps1 in PowerShell, then try again.
echo Port 8501 in use: stop the existing server with Ctrl+C, then try again.
pause
exit /b 1
