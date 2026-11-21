param([switch]$CheckOnly)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$taskName='RecruitmentDW-Collect-FourSources-1118'
$pythonExe=Join-Path $projectRoot '.venv-dbt\Scripts\pythonw.exe'
$arguments='-X utf8 -m scripts.scheduled_collection'
$config=Get-Content -LiteralPath (Join-Path $projectRoot 'warehouse\collection_schedule.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ((Get-TimeZone).Id -ne 'China Standard Time') { throw 'The 11:18 task requires the verified Beijing machine time zone' }
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Project pythonw runtime missing' }
$identity=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$existing=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.Actions.Execute -ne $pythonExe -or $existing.Actions.Arguments -ne $arguments -or $existing.Actions.WorkingDirectory -ne $projectRoot) {
        throw 'Existing task differs; refusing to overwrite another configuration'
    }
} elseif (-not $CheckOnly) {
    $start=(Get-Date).Date.AddDays(1).AddHours(11).AddMinutes(18)
    $action=New-ScheduledTaskAction -Execute $pythonExe -Argument $arguments -WorkingDirectory $projectRoot
    $trigger=New-ScheduledTaskTrigger -Daily -At $start
    $principal=New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
    $settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Daily 11:18 four public recruitment sources; limited retries, real timestamps, pending review; no automatic approval or publication.' | Out-Null
}
$task=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) { throw 'Task has not been installed' }
$info=Get-ScheduledTaskInfo -TaskName $taskName
[PSCustomObject]@{
    TaskName=$taskName;State=[string]$task.State;NextRunTime=$info.NextRunTime.ToString('o');
    Execute=$task.Actions.Execute;Arguments=$task.Actions.Arguments;WorkingDirectory=$task.Actions.WorkingDirectory;
    LogonType=[string]$task.Principal.LogonType;RunLevel=[string]$task.Principal.RunLevel;
    MultipleInstances=[string]$task.Settings.MultipleInstances;StartWhenAvailable=$task.Settings.StartWhenAvailable;
    WakeToRun=$task.Settings.WakeToRun;ExecutionTimeLimit=$task.Settings.ExecutionTimeLimit
} | ConvertTo-Json -Depth 3
