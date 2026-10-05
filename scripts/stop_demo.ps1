# Stops only the project-owned background demo whose PID was recorded locally.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidPath = Join-Path $projectRoot 'tmp\streamlit.pid'
if (-not (Test-Path -LiteralPath $pidPath)) {
    Write-Output 'No recorded background demo. Use Ctrl+C in the terminal that started Streamlit.'
    exit 0
}
$recordedPid = [int](Get-Content -LiteralPath $pidPath)
$recordedProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $recordedPid"
if (-not $recordedProcess) {
    Write-Output 'The recorded demo is already stopped.'
    exit 0
}
$expectedPython = Join-Path $projectRoot '.venv-hw2\Scripts\python.exe'
if ($recordedProcess.ExecutablePath -ne $expectedPython -or
    $recordedProcess.CommandLine -notmatch '(streamlit.*run.*app\.py|scripts[/\\]run_offline_demo\.py)') {
    throw 'PID no longer belongs to this project demo; refusing to stop another process.'
}
Stop-Process -Id $recordedPid
Write-Output "Stopped project demo PID $recordedPid."
