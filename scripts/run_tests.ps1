[CmdletBinding()]
param([switch]$Integration)

. (Join-Path $PSScriptRoot "common.ps1")
Import-ProjectEnvironment | Out-Null
$env:PYTHONUTF8 = "1"
$python = Get-ProjectPython
$root = Get-ProjectRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

function Invoke-Checked {
    param([Parameter(Mandatory = $true)][scriptblock]$Command, [Parameter(Mandatory = $true)][string]$Description)
    Write-Host "`n== $Description ==" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Description failed with exit code $LASTEXITCODE." }
}

Push-Location $backend
try {
    Invoke-Checked { & $python -m compileall -q app . } "Python syntax checks"
    Invoke-Checked {
        & $python -m unittest -v test_speech_to_text_service test_language_model_service test_conversation_memory test_conversation_endpoints test_voice_response_endpoint test_text_to_speech_service test_text_to_speech_endpoint test_health_endpoint
    } "Backend fast unit tests"
    Invoke-Checked { & $python -m pip check } "Python dependency check"
}
finally { Pop-Location }

if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js is required for frontend tests but was not found on PATH." }
Push-Location $frontend
try {
    Invoke-Checked { & node --check app.js } "Frontend syntax check"
    $frontendTests = Get-ChildItem -LiteralPath $frontend -Filter "test_*.js" | Sort-Object Name
    foreach ($test in $frontendTests) { Invoke-Checked { & node $test.FullName } "Frontend test: $($test.Name)" }
}
finally { Pop-Location }

if ($Integration) {
    Write-Host "`n== Explicit model-dependent integration tests ==" -ForegroundColor Magenta
    & (Join-Path $PSScriptRoot "check_setup.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Integration prerequisites failed." }
    if (-not (Test-ExpectedHttpService -Url "http://127.0.0.1:8000/" -ExpectedText "Hindi Voice Agent backend")) { throw "Start the backend before integration tests: .\scripts\start_backend.ps1" }
    $recording = Get-ChildItem -LiteralPath (Join-Path $backend "temporary_audio") -Filter "*.webm" -File | Select-Object -First 1
    if (-not $recording) { throw "A real WebM recording is required in backend/temporary_audio for Whisper and voice integration tests." }

    Push-Location $backend
    try {
        foreach ($test in @("test_transcription.py", "test_language_model.py", "test_conversation.py", "test_text_to_speech.py", "test_voice_response.py", "test_voice_conversation_tts.py")) {
            Invoke-Checked { & $python $test } "Integration test: $test"
        }
    }
    finally { Pop-Location }
}

Write-Host "`nAll requested tests passed." -ForegroundColor Green
