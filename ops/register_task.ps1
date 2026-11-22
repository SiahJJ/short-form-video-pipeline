# Register a pipeline stage as a hidden, wake-capable, single-instance scheduled task.
#
#   .\register_task.ps1 -Name "Storage Guardian - Hourly" -Script "C:\pipeline\storage\guardian_run.py" `
#       -Arguments "--apply" -EveryMinutes 60 -LimitMinutes 30
#
# Paths are examples - point them at your own Python and scripts.
param(
    [Parameter(Mandatory)] [string] $Name,
    [Parameter(Mandatory)] [string] $Script,
    [string] $Arguments = "",
    [int] $EveryMinutes = 30,
    [int] $LimitMinutes = 20,
    [string] $Python = "$PSScriptRoot\..\.venv\Scripts\python.exe",
    [switch] $StayAwake            # wrap in run_awake.py for long jobs (renders, uploads)
)

$hidden = Join-Path $PSScriptRoot "run_hidden.vbs"
$target = if ($StayAwake) { "`"$Python`" `"$PSScriptRoot\run_awake.py`" -- `"$Python`" `"$Script`" $Arguments" }
          else            { "`"$Python`" `"$Script`" $Arguments" }

$action  = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\wscript.exe" -Argument "//B //Nologo `"$hidden`" $target"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(1) `
           -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes)
$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes $LimitMinutes) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Force |
    Select-Object TaskName, State
