<#
    Wrapper that locates the project virtualenv and forwards all arguments
    to cli.py.

    Usage:
        ./run.ps1 probe
        ./run.ps1 --segments credit_reporting,debt_collection its
#>
$ErrorActionPreference = 'Stop'

$home_dir = if ($env:CFPB_INSPECT_HOME) { $env:CFPB_INSPECT_HOME }
            else { Join-Path $HOME 'CFPB-Inspect' }
$venvPython = Join-Path $home_dir 'venv\Scripts\python.exe'

if (-not (Test-Path $venvPython)) {
    Write-Error @"
Virtualenv not found at: $venvPython

Create it with:
  python -m venv "$home_dir\venv"
  & "$venvPython" -m pip install -r "$PSScriptRoot\requirements.txt"
"@
}

& $venvPython (Join-Path $PSScriptRoot 'cli.py') @args
exit $LASTEXITCODE
