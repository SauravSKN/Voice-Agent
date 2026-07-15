[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot "common.ps1")
Import-ProjectEnvironment | Out-Null
$python = Get-IndicParlerPython
$backend = Join-Path (Get-ProjectRoot) "backend"

$env:PYTHONUTF8 = "1"
Set-Location $backend
& $python -m uvicorn app.indic_parler_service:app --host 127.0.0.1 --port 8002
