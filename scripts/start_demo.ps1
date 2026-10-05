$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONPYCACHEPREFIX = Join-Path $projectRoot 'tmp\pycache-hw2'
$env:MPLCONFIGDIR = Join-Path $projectRoot 'tmp\matplotlib'
$pythonPath = Join-Path $projectRoot '.venv-hw2\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw '請先執行 scripts/setup_hw2.ps1 建立 HW2 環境。'
}
& $pythonPath -X utf8 -c "import sys, inspect; from gensim.models import Word2Vec; import streamlit; import matplotlib; assert 'live' in inspect.signature(streamlit.text_input).parameters, '即時拼字建議需要 Streamlit 1.64；請執行 scripts/setup_hw2.ps1 更新環境'; print('HW2 Python: ' + sys.executable)"
if ($LASTEXITCODE -ne 0) {
    throw 'HW2 套件載入失敗。請先執行 scripts/setup_hw2.ps1，完成後再執行 scripts/start_demo.ps1。'
}
& $pythonPath -X utf8 -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
