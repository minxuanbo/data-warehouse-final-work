param([string]$BatchPath = '', [string]$Revision = 'f6eccadec28a4a1132c5953bbd92470c1d794348')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv-dbt\Scripts\python.exe'
$dbtExe = Join-Path $projectRoot '.venv-dbt\Scripts\dbt.exe'
if (-not (Test-Path $pythonExe)) { throw 'Create .venv-dbt and install warehouse/requirements.lock.txt first.' }
Push-Location $projectRoot
try {
    if (-not $BatchPath) {
        & $pythonExe scripts/prepare_trial_input.py
        if ($LASTEXITCODE -ne 0) { throw 'Input preparation failed' }
        $BatchPath = '.local/pr1_input/data/tencent/tencent_20261031T093102Z_366ad0a4'
    }
    & $pythonExe -m warehouse.load $BatchPath --revision $Revision --init
    if ($LASTEXITCODE -ne 0) { throw 'Validation/load failed; dbt not started' }
    & $dbtExe build --project-dir dbt --profiles-dir dbt
    if ($LASTEXITCODE -ne 0) { throw 'dbt failed; trial not verified' }
    Write-Output 'Trial pipeline passed. Input remains pending; no production publication.'
} finally { Pop-Location }
