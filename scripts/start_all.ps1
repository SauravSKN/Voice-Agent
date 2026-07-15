[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot "common.ps1")
Import-ProjectEnvironment | Out-Null

function Start-ScriptWindow([string]$Title, [string]$ScriptPath) {
    $command = "`$host.UI.RawUI.WindowTitle='$Title'; & '$ScriptPath'"
    Start-Process powershell.exe -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $command) | Out-Null
}

if (-not (Test-LocalPortOpen -Port 11434)) {
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { throw "Ollama is not installed or not on PATH. Follow README.md setup first." }
    Start-Process powershell.exe -ArgumentList @("-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='Hindi Voice Agent - Ollama'; ollama serve") | Out-Null
}

$ollamaDeadline = (Get-Date).AddSeconds(30)
while (
    (Get-Date) -lt $ollamaDeadline -and
    -not (Test-ExpectedHttpService -Url "http://127.0.0.1:11434/api/tags" -ExpectedText "models")
) {
    Start-Sleep -Milliseconds 500
}
if (-not (Test-ExpectedHttpService -Url "http://127.0.0.1:11434/api/tags" -ExpectedText "models")) {
    throw "Ollama did not become ready within 30 seconds. Check its window."
}

& (Join-Path $PSScriptRoot "check_setup.ps1")
if ($LASTEXITCODE -ne 0) { throw "Setup checks failed. Fix the FAIL messages above; no existing process was stopped." }

if (-not (Test-LocalPortOpen -Port 8000)) { Start-ScriptWindow "Hindi Voice Agent - Backend" (Join-Path $PSScriptRoot "start_backend.ps1") }
elseif (-not (Test-ExpectedHttpService -Url "http://127.0.0.1:8000/" -ExpectedText "Hindi Voice Agent backend")) { throw "Port 8000 is occupied by an unexpected service." }

$backendDeadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $backendDeadline -and -not (Test-ExpectedHttpService -Url "http://127.0.0.1:8000/" -ExpectedText "Hindi Voice Agent backend")) { Start-Sleep -Milliseconds 500 }
if (-not (Test-ExpectedHttpService -Url "http://127.0.0.1:8000/" -ExpectedText "Hindi Voice Agent backend")) { throw "Backend did not become ready within 30 seconds. Check its window." }

if (-not (Test-LocalPortOpen -Port 5500)) { Start-ScriptWindow "Hindi Voice Agent - Frontend" (Join-Path $PSScriptRoot "start_frontend.ps1") }
elseif (-not (Test-ExpectedHttpService -Url "http://127.0.0.1:5500/" -ExpectedText "Hindi Voice Agent")) { throw "Port 5500 is occupied by an unexpected service." }

Write-Host "`nHindi Voice Agent is starting locally." -ForegroundColor Green
Write-Host "Frontend: http://127.0.0.1:5500/"
Write-Host "Stop services safely with Ctrl+C in the windows started by this script."
Write-Host "This script never stops processes that were already running."
