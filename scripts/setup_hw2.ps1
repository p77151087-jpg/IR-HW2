param(
    [string]$Python = 'py',
    [string]$PythonVersion = '3.13'
)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$venvRoot = Join-Path $projectRoot '.venv-hw2'
$venvPython = Join-Path $venvRoot 'Scripts/python.exe'
$cacheRoot = Join-Path $projectRoot 'tmp/pip-cache'
$tempRoot = Join-Path $projectRoot 'tmp/env-tmp'
$reportRoot = Join-Path $projectRoot 'reports/hw2'
New-Item -ItemType Directory -Path $cacheRoot, $tempRoot, $reportRoot -Force | Out-Null
$previousCache = $env:PIP_CACHE_DIR
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
$previousUtf8 = $env:PYTHONUTF8
try {
    $env:PIP_CACHE_DIR = $cacheRoot
    $env:TEMP = $tempRoot
    $env:TMP = $tempRoot
    $env:PYTHONUTF8 = '1'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if ($Python -eq 'py') {
            & $Python "-$PythonVersion" -m venv $venvRoot
        } else {
            & $Python -m venv $venvRoot
        }
        if ($LASTEXITCODE -ne 0) { throw '建立 HW2 虛擬環境失敗。' }
    }
    & $venvPython -c 'import pathlib,sys; target=pathlib.Path(sys.argv[1]).resolve(); assert pathlib.Path(sys.prefix).resolve()==target, (sys.prefix,target); print(sys.version); print(sys.executable); print(sys.prefix)' $venvRoot
    if ($LASTEXITCODE -ne 0) { throw '虛擬環境驗證失敗，請檢查 .venv-hw2 的基礎 Python 是否存在。' }
    & $venvPython -m pip install -r (Join-Path $projectRoot 'requirements-hw2.txt') --log (Join-Path $reportRoot 'environment-install.log')
    if ($LASTEXITCODE -ne 0) { throw 'HW2 依賴安裝失敗。' }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'HW2 依賴衝突。' }
    & $venvPython -m streamlit version
    if ($LASTEXITCODE -ne 0) { throw 'Streamlit 啟動驗證失敗。' }
    Write-Host "HW2 環境已準備完成：$venvPython"
} finally {
    $env:PIP_CACHE_DIR = $previousCache
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
    $env:PYTHONUTF8 = $previousUtf8
}
