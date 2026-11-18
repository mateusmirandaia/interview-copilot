<#
.SYNOPSIS
    Runs Interview Copilot from the project's virtual environment.

.DESCRIPTION
    Activates .venv and runs "python -m interview_copilot <args>".
    Without arguments it runs the default command ("run": overlay + live audio).

.EXAMPLE
    .\scripts\run.ps1
.EXAMPLE
    .\scripts\run.ps1 simulate "Tell me about yourself."
.EXAMPLE
    .\scripts\run.ps1 run --profile profiles\me
#>
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Activate = Join-Path $RepoRoot '.venv\Scripts\Activate.ps1'

if (-not (Test-Path $Activate)) {
    Write-Host "Virtual environment not found (.venv)." -ForegroundColor Red
    Write-Host "Run the setup first, from the repository root:"
    Write-Host "  .\scripts\setup.ps1"
    exit 1
}

Set-Location $RepoRoot
. $Activate

$cliArgs = if ($args.Count -gt 0) { $args } else { @('run') }
python -m interview_copilot @cliArgs
exit $LASTEXITCODE
