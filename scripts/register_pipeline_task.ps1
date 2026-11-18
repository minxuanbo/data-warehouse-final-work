param([switch]$RunNow)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$taskName='RecruitmentDW-AcceptedBatch-2230'
$pythonExe=Join-Path $projectRoot '.venv-dbt\Scripts\pythonw.exe'
$configPath=Join-Path $projectRoot 'warehouse\pipeline.json'
$arguments='-X utf8 -m scripts.run_pipeline --config "'+$configPath+'"'
$identity=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$existing=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.Actions.Execute -ne $pythonExe -or $existing.Actions.Arguments -ne $arguments) {
        throw 'Existing task differs; refusing to overwrite another configuration'
    }
} else {
    $action=New-ScheduledTaskAction -Execute $pythonExe -Argument $arguments -WorkingDirectory $projectRoot
    $trigger=New-ScheduledTaskTrigger -Daily -At '22:30'
    $principal=New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
    $settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Accepted, versioned recruitment batches -> tested sample publication. Pending inputs remain pending.' | Out-Null
}
if ($RunNow) { Start-ScheduledTask -TaskName $taskName }
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object LastRunTime,LastTaskResult,NextRunTime
