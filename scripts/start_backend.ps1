[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot "common.ps1")
Import-ProjectEnvironment | Out-Null
$python = Get-ProjectPython

if (Test-LocalPortOpen -Port 8000) {
    if (Test-ExpectedHttpService -Url "http://127.0.0.1:8000/" -ExpectedText "Hindi Voice Agent backend") {
        Write-Host "Backend is already running at http://127.0.0.1:8000" -ForegroundColor Green
        exit 0
    }
    throw "Port 8000 is occupied by an unexpected service. Nothing was stopped."
}

Write-Host "Starting backend on http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "Press Ctrl+C in this window to stop it."
Push-Location (Join-Path (Get-ProjectRoot) "backend")
try {
    & $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
    exit $LASTEXITCODE
}
finally { Pop-Location }
