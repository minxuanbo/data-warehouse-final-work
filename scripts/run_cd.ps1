$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv-dbt\Scripts\python.exe'
$dbtExe = Join-Path $projectRoot '.venv-dbt\Scripts\dbt.exe'
$previousDatabase = $env:DW_DATABASE
if (-not $env:DW_DATABASE) { $env:DW_DATABASE = 'recruitment_dw_dev_cd_v1' }
Push-Location $projectRoot
try {
    & $pythonExe scripts/prepare_cd_input.py
    if ($LASTEXITCODE -ne 0) { throw 'C/D input preparation failed' }
    $batch = '.local/cd_input/data/tencent/tencent_20261031T093102Z_366ad0a4'
    $analysis = '.local/cd_input/reports/analysis/tencent_20261031T093102Z_366ad0a4'
    $dictionary = '.local/cd_input/etl/skills/dictionary.json'
    & $pythonExe -m warehouse.load $batch --revision 25b397bf846a8e7c39bbc249e0700428e89bc0c3 --init
    if ($LASTEXITCODE -ne 0) { throw 'Accepted batch load failed' }
    & $pythonExe -m warehouse.integrate_analysis --batch $batch --analysis $analysis --dictionary $dictionary
    if ($LASTEXITCODE -ne 0) { throw 'C/D integration failed' }
    & $dbtExe build --project-dir dbt --profiles-dir dbt
    if ($LASTEXITCODE -ne 0) { throw 'C/D dbt tests failed' }
    & $pythonExe -m warehouse.export_cd
    if ($LASTEXITCODE -ne 0) { throw 'C/D handoff export failed' }
    Write-Output "C/D integration passed in $env:DW_DATABASE"
} finally {
    Pop-Location
    $env:DW_DATABASE = $previousDatabase
}
