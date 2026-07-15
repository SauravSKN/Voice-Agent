[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot "common.ps1")
$root = Get-ProjectRoot
$venv = Join-Path $root ".venv-indic-parler"
$python = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Write-Host "Creating isolated Indic Parler environment..." -ForegroundColor Cyan
    py -3.11 -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create .venv-indic-parler." }
}

& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }

Write-Host "Installing one official CUDA 13.0 PyTorch wheel set..." -ForegroundColor Cyan
& $python -m pip install torch==2.11.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu130
if ($LASTEXITCODE -ne 0) { throw "CUDA PyTorch installation failed." }

Write-Host "Installing the pinned Indic Parler worker dependencies..." -ForegroundColor Cyan
& $python -m pip install -r (Join-Path $root "backend\requirements-indic-parler.txt")
if ($LASTEXITCODE -ne 0) { throw "Indic Parler dependency installation failed." }

& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw "The isolated environment has dependency conflicts." }

& $python -c "import torch; import parler_tts; print('PyTorch:', torch.__version__); print('CUDA runtime:', torch.version.cuda); print('CUDA available:', torch.cuda.is_available()); print('CUDA devices:', torch.cuda.device_count())"
if ($LASTEXITCODE -ne 0) { throw "Indic Parler import/CUDA verification failed." }

Write-Host "`nDependencies are installed. The model is gated and is not downloaded by this script." -ForegroundColor Yellow
Write-Host "Accept its terms at: https://huggingface.co/ai4bharat/indic-parler-tts"
Write-Host "Then authenticate locally with:"
Write-Host "  & '$(Join-Path $venv 'Scripts\hf.exe')' auth login"
