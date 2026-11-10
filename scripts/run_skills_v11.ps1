$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv-dbt\Scripts\python.exe'
$dbtExe = Join-Path $projectRoot '.venv-dbt\Scripts\dbt.exe'
$previousDatabase = $env:DW_DATABASE
if (-not $env:DW_DATABASE) { $env:DW_DATABASE = 'recruitment_dw_dev_cd_v1' }
Push-Location $projectRoot
try {
    & $PSScriptRoot/run_dual.ps1
    & $pythonExe -m scripts.prepare_skills_v11
    if ($LASTEXITCODE -ne 0) { throw 'Versioned skill input preparation failed' }
    $dictionary = '.local/skills_v11/etl/skills/dictionary.json'
    & $pythonExe -m warehouse.integrate_analysis --batch '.local/cd_input/data/tencent/tencent_20261031T093102Z_366ad0a4' --analysis '.local/skills_v11/reports/analysis/tencent_20261031T093102Z_366ad0a4/v1.1' --dictionary $dictionary
    if ($LASTEXITCODE -ne 0) { throw 'Tencent skill integration failed' }
    & $pythonExe -m warehouse.integrate_analysis --batch '.local/netease_input/data/netease/netease_20261101T044527Z_157cf969' --analysis '.local/skills_v11/reports/analysis/netease_20261101T044527Z_157cf969/v1.1' --dictionary $dictionary
    if ($LASTEXITCODE -ne 0) { throw 'NetEase skill integration failed' }
    & $dbtExe build --project-dir dbt --profiles-dir dbt
    if ($LASTEXITCODE -ne 0) { throw 'Three-field dbt checks failed' }
    & $pythonExe -X utf8 -m scripts.check_skills_v11 --activate
    if ($LASTEXITCODE -ne 0) { throw 'Skill reconciliation failed' }
} finally {
    Pop-Location
    $env:DW_DATABASE = $previousDatabase
}
