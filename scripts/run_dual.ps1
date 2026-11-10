$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv-dbt\Scripts\python.exe'
$dbtExe = Join-Path $projectRoot '.venv-dbt\Scripts\dbt.exe'
$previousDatabase = $env:DW_DATABASE
if (-not $env:DW_DATABASE) { $env:DW_DATABASE = 'recruitment_dw_dev_cd_v1' }
Push-Location $projectRoot
try {
    & $PSScriptRoot/run_cd.ps1
    & $pythonExe -m scripts.prepare_netease_input
    if ($LASTEXITCODE -ne 0) { throw 'NetEase input preparation failed' }
    & $pythonExe -m warehouse.load '.local/netease_input/data/netease/netease_20261101T044527Z_157cf969' --revision 0f862031ba07e5f46c3929818873dee7b9e05608 --init
    if ($LASTEXITCODE -ne 0) { throw 'NetEase load failed' }
    & $dbtExe build --project-dir dbt --profiles-dir dbt
    if ($LASTEXITCODE -ne 0) { throw 'Dual-source quality checks failed' }
    Write-Output "Dual-source integration passed in $env:DW_DATABASE"
} finally {
    Pop-Location
    $env:DW_DATABASE = $previousDatabase
}
