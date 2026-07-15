[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot "common.ps1")
$failures = 0
$warnings = 0

function Write-Pass([string]$Message) { Write-Host "PASS    $Message" -ForegroundColor Green }
function Write-WarningCheck([string]$Message) { $script:warnings += 1; Write-Host "WARNING $Message" -ForegroundColor Yellow }
function Write-Fail([string]$Message) { $script:failures += 1; Write-Host "FAIL    $Message" -ForegroundColor Red }

Write-Host "Hindi Voice Agent setup check" -ForegroundColor Cyan
Write-Host "Project: $(Get-ProjectRoot)"

try {
    if (Import-ProjectEnvironment) { Write-Pass ".env loaded (existing process variables kept their precedence)." }
    else { Write-WarningCheck ".env is absent; application defaults will be used." }
}
catch { Write-Fail $_.Exception.Message }

try {
    $python = Get-ProjectPython
    $version = (& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')").Trim()
    if ($LASTEXITCODE -eq 0 -and $version.StartsWith("3.11.")) { Write-Pass "Python $version is supported." }
    else { Write-Fail "Python 3.11 is required; found $version." }
}
catch { Write-Fail $_.Exception.Message; $python = $null }

if ($python) {
    & $python -c "import fastapi, uvicorn, multipart, pydantic, faster_whisper, ctranslate2, onnxruntime, piper, httpx"
    if ($LASTEXITCODE -eq 0) { Write-Pass "Required Python packages import successfully." }
    else { Write-Fail "One or more required Python packages could not be imported." }
}

if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { Write-Pass "FFmpeg is available on PATH." }
else { Write-Fail "FFmpeg was not found on PATH." }

if (Get-Command ollama -ErrorAction SilentlyContinue) { Write-Pass "Ollama is installed." }
else { Write-Fail "Ollama is not installed or not on PATH." }

$ollamaBaseUrl = if ($env:LLM_BASE_URL) { $env:LLM_BASE_URL.TrimEnd("/") } else { "http://127.0.0.1:11434" }
$ollamaModel = if ($env:LLM_MODEL) { $env:LLM_MODEL } else { "qwen3:4b-instruct" }
try {
    $tags = Invoke-RestMethod -Uri "$ollamaBaseUrl/api/tags" -TimeoutSec 3
    Write-Pass "Ollama is reachable on the configured loopback URL."
    $names = @($tags.models | ForEach-Object { if ($_.name) { $_.name } else { $_.model } })
    if ($names -contains $ollamaModel) { Write-Pass "Ollama model '$ollamaModel' is installed." }
    else { Write-Fail "Ollama model '$ollamaModel' is missing. Run: ollama pull $ollamaModel" }
}
catch { Write-Fail "Ollama is not reachable at the configured local URL." }

try {
    $piperModel = Resolve-PiperModelPath
    if (Test-Path -LiteralPath $piperModel -PathType Leaf) { Write-Pass "Piper ONNX voice model exists." }
    else { Write-Fail "Piper ONNX voice model is missing (see README.md)." }
    if (Test-Path -LiteralPath "$piperModel.json" -PathType Leaf) { Write-Pass "Piper voice configuration exists." }
    else { Write-Fail "Piper voice configuration is missing (see README.md)." }
}
catch { Write-Fail "Piper model configuration could not be resolved." }

$generatedDirectory = Join-Path (Get-ProjectRoot) "backend\generated_audio"
if (Test-Path -LiteralPath $generatedDirectory -PathType Container) {
    if ($python) {
        $env:HVA_CHECK_DIRECTORY = $generatedDirectory
        & $python -c "import os, sys; sys.exit(0 if os.access(os.environ['HVA_CHECK_DIRECTORY'], os.W_OK) else 1)"
        Remove-Item Env:HVA_CHECK_DIRECTORY -ErrorAction SilentlyContinue
        if ($LASTEXITCODE -eq 0) { Write-Pass "Generated-audio directory is writable." }
        else { Write-Fail "Generated-audio directory is not writable." }
    }
}
else { Write-Fail "backend/generated_audio does not exist." }

if ($python) {
    Push-Location (Join-Path (Get-ProjectRoot) "backend")
    try {
        & $python -c "from app.services.speech_to_text import WhisperSettings; s=WhisperSettings.from_environment(); print(f'{s.requested_device}/{s.requested_compute_type}')"
        if ($LASTEXITCODE -eq 0) { Write-Pass "Whisper configuration is valid." }
        else { Write-Fail "Whisper configuration is invalid." }

        $cudaCount = (& $python -c "import ctranslate2; print(ctranslate2.get_cuda_device_count())").Trim()
        if ($LASTEXITCODE -eq 0) {
            if (($env:WHISPER_DEVICE -eq "cuda") -and ([int]$cudaCount -lt 1)) { Write-Fail "CUDA was requested, but CTranslate2 detects no CUDA device." }
            elseif ($env:WHISPER_DEVICE -eq "cuda") { Write-Pass "CUDA requested; CTranslate2 detects $cudaCount device(s)." }
            else { Write-Pass "CTranslate2 CUDA device count: $cudaCount (CPU mode selected)." }
        }
        else { Write-Fail "CTranslate2 CUDA detection failed." }
    }
    finally { Pop-Location }
}

$portChecks = @(
    @{Port=8000; Name="backend"; Url="http://127.0.0.1:8000/"; Text="Hindi Voice Agent backend"},
    @{Port=5500; Name="frontend"; Url="http://127.0.0.1:5500/"; Text="Hindi Voice Agent"},
    @{Port=11434; Name="Ollama"; Url="http://127.0.0.1:11434/api/tags"; Text="models"}
)
foreach ($check in $portChecks) {
    if (-not (Test-LocalPortOpen -Port $check.Port)) { Write-Pass "Port $($check.Port) is available for $($check.Name)." }
    elseif (Test-ExpectedHttpService -Url $check.Url -ExpectedText $check.Text) { Write-Pass "Port $($check.Port) is already used by the expected $($check.Name) service." }
    else { Write-Fail "Port $($check.Port) is occupied by an unexpected service." }
}

Write-Host "`nResult: $failures failure(s), $warnings warning(s)."
if ($failures -gt 0) { exit 1 }
exit 0
