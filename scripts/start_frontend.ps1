[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot "common.ps1")
$python = Get-ProjectPython

if (Test-LocalPortOpen -Port 5500) {
    if (Test-ExpectedHttpService -Url "http://127.0.0.1:5500/" -ExpectedText "Hindi Voice Agent") {
        Write-Host "Frontend is already running at http://127.0.0.1:5500/" -ForegroundColor Green
        exit 0
    }
    throw "Port 5500 is occupied by an unexpected service. Nothing was stopped."
}

Write-Host "Starting frontend on http://127.0.0.1:5500/" -ForegroundColor Cyan
Write-Host "Press Ctrl+C in this window to stop it."
& $python -m http.server 5500 --bind 127.0.0.1 --directory (Join-Path (Get-ProjectRoot) "frontend")
exit $LASTEXITCODE
