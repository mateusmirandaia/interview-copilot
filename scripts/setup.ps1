<#
.SYNOPSIS
    Creates the virtual environment and installs Interview Copilot for development.

.DESCRIPTION
    1. Finds Python 3.11 or newer (tries "py -3.12", then "py -3", then "python").
    2. Creates .venv in the repository root (reuses it if it already exists).
    3. Upgrades pip and installs the package in editable mode with the dev extras (pytest, ruff).
    4. With -Whisper, also installs the optional local speech-to-text engine (faster-whisper).
    5. Creates .env from .env.example if it does not exist yet, and prints the next steps.

.PARAMETER Whisper
    Also install faster-whisper for local transcription (no Deepgram key needed).

.EXAMPLE
    .\scripts\setup.ps1
.EXAMPLE
    .\scripts\setup.ps1 -Whisper
#>
[CmdletBinding()]
param(
    [switch]$Whisper
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$MinMajor = 3
$MinMinor = 11

# Repository root = parent of the scripts folder, regardless of where the script is called from.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    # Runs a native command and stops on a non-zero exit code
    # ($ErrorActionPreference does not apply to native commands in Windows PowerShell 5.1).
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit code $LASTEXITCODE): $Exe $($Arguments -join ' ')"
    }
}

function Get-PythonVersion {
    # Returns "major.minor" for a candidate interpreter, or $null if it cannot run.
    param([string]$Exe, [string[]]$PrefixArgs)
    if (-not (Get-Command $Exe -ErrorAction SilentlyContinue)) { return $null }
    try {
        $out = & $Exe @PrefixArgs -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        return ($out | Select-Object -First 1).ToString().Trim()
    } catch {
        return $null
    }
}

# ---------------------------------------------------------------------------
# 1. Find a suitable Python
# ---------------------------------------------------------------------------
Write-Step "Looking for Python $MinMajor.$MinMinor or newer"

$candidates = @(
    @{ Exe = 'py';     Args = @('-3.12') },
    @{ Exe = 'py';     Args = @('-3') },
    @{ Exe = 'python'; Args = @() }
)

$python = $null
$found = @()
foreach ($c in $candidates) {
    $version = Get-PythonVersion -Exe $c.Exe -PrefixArgs $c.Args
    if (-not $version) { continue }
    $label = ("{0} {1}" -f $c.Exe, ($c.Args -join ' ')).Trim()
    $found += "$label -> $version"
    $parts = $version.Split('.')
    $major = [int]$parts[0]; $minor = [int]$parts[1]
    if ($major -gt $MinMajor -or ($major -eq $MinMajor -and $minor -ge $MinMinor)) {
        $python = $c
        Write-Host "Using '$label' (Python $version)"
        break
    }
}

if (-not $python) {
    Write-Host ""
    if ($found.Count -gt 0) {
        Write-Host "Found only older interpreters:" -ForegroundColor Yellow
        $found | ForEach-Object { Write-Host "  $_" }
    }
    Write-Host "Python $MinMajor.$MinMinor+ was not found." -ForegroundColor Red
    Write-Host "Install Python 3.12 from https://www.python.org/downloads/ (check 'Add python.exe to PATH'),"
    Write-Host "then open a new PowerShell window and run this script again."
    exit 1
}

# ---------------------------------------------------------------------------
# 2. Create (or reuse) the virtual environment
# ---------------------------------------------------------------------------
$VenvDir = Join-Path $RepoRoot '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'

if (Test-Path $VenvPython) {
    Write-Step "Reusing existing virtual environment (.venv)"
} else {
    Write-Step "Creating virtual environment (.venv)"
    Invoke-Checked -Exe $python.Exe -Arguments ($python.Args + @('-m', 'venv', $VenvDir))
}

# ---------------------------------------------------------------------------
# 3. Install the package
# ---------------------------------------------------------------------------
Write-Step "Upgrading pip"
Invoke-Checked -Exe $VenvPython -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip')

$extras = if ($Whisper) { '.[dev,whisper]' } else { '.[dev]' }
Write-Step "Installing interview-copilot in editable mode ($extras)"
Invoke-Checked -Exe $VenvPython -Arguments @('-m', 'pip', 'install', '-e', $extras)

if ($Whisper) {
    Write-Host ""
    Write-Host "faster-whisper installed. For an NVIDIA GPU (CUDA 12) also run, inside the venv:" -ForegroundColor Yellow
    Write-Host '  pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"'
}

# ---------------------------------------------------------------------------
# 4. .env file for the API keys (optional alternative to setx)
# ---------------------------------------------------------------------------
$EnvFile = Join-Path $RepoRoot '.env'
$EnvExample = Join-Path $RepoRoot '.env.example'
if (-not (Test-Path $EnvFile) -and (Test-Path $EnvExample)) {
    Copy-Item $EnvExample $EnvFile
    Write-Step "Created .env from .env.example (fill in your keys there, or use setx)"
}

# ---------------------------------------------------------------------------
# 5. Next steps
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host @"

Next steps:
  1. Activate the environment:
       .\.venv\Scripts\Activate.ps1
  2. Set your API keys, either in .env or as environment variables
     (after setx, open a NEW terminal):
       setx ANTHROPIC_API_KEY "sk-ant-..."
       setx DEEPGRAM_API_KEY "your-deepgram-key"
  3. Check everything and try it:
       python -m interview_copilot check
       python -m interview_copilot simulate "Tell me about yourself."
       python -m interview_copilot test-audio
       python -m interview_copilot run

Docs: README.md, docs\CUSTOMIZING.md, docs\TROUBLESHOOTING.md
"@
