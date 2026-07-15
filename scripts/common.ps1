Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:ProjectRoot = Split-Path -Parent $PSScriptRoot

function Get-ProjectRoot {
    return $script:ProjectRoot
}

function Import-ProjectEnvironment {
    $envPath = Join-Path $script:ProjectRoot ".env"
    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
        return $false
    }

    foreach ($rawLine in Get-Content -LiteralPath $envPath) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }
        if ($line -notmatch '^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            throw "Invalid .env line: $rawLine"
        }

        $name = $Matches[1]
        $value = $Matches[2].Trim()
        if (
            $value.Length -ge 2 -and
            (($value.StartsWith('"') -and $value.EndsWith('"')) -or
             ($value.StartsWith("'") -and $value.EndsWith("'")))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        $existing = [Environment]::GetEnvironmentVariable($name, "Process")
        if ($null -eq $existing) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
    return $true
}

function Get-ProjectPython {
    $python = Join-Path $script:ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Python virtual environment not found at .venv. Follow README.md setup first."
    }
    return $python
}

function Test-LocalPortOpen {
    param([Parameter(Mandatory = $true)][int]$Port)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync("127.0.0.1", $Port)
        if (-not $task.Wait(500)) { return $false }
        return $client.Connected
    }
    catch { return $false }
    finally { $client.Dispose() }
}

function Test-ExpectedHttpService {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$ExpectedText
    )
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        return $response.StatusCode -eq 200 -and $response.Content.Contains($ExpectedText)
    }
    catch { return $false }
}

function Resolve-PiperModelPath {
    $rawModel = if ($env:TTS_MODEL) { $env:TTS_MODEL } else { "models/piper/hi_IN-priyamvada-medium.onnx" }
    if ([System.IO.Path]::IsPathRooted($rawModel)) {
        return [System.IO.Path]::GetFullPath($rawModel)
    }
    return [System.IO.Path]::GetFullPath((Join-Path (Join-Path $script:ProjectRoot "backend") $rawModel))
}
