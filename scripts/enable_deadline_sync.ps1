param([string]$Pythonw = '')
$ErrorActionPreference = 'Stop'
$appDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$dataDir = if ($env:WEEKLY_SCHEDULE_DATA_DIR) { $env:WEEKLY_SCHEDULE_DATA_DIR } else { Join-Path $env:LOCALAPPDATA 'WeeklyScheduleWidgetPublic' }
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
$taskName = 'WeeklyScheduleWidgetHourlySync'
if (-not $Pythonw) { $Pythonw = Join-Path $appDir '.venv\Scripts\pythonw.exe' }
$syncFile = Join-Path $appDir 'shad_background.py'
if (-not (Test-Path -LiteralPath $pythonw) -or -not (Test-Path -LiteralPath $syncFile)) {
    throw 'Missing SHAD synchronizer or Python runtime'
}
$userSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$firstRun = (Get-Date).AddHours(1).ToString('yyyy-MM-ddTHH:mm:ss')
$exeXml = [System.Security.SecurityElement]::Escape($pythonw)
$argsXml = [System.Security.SecurityElement]::Escape(('"{0}"' -f $syncFile))
$dirXml = [System.Security.SecurityElement]::Escape($appDir)
$taskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Refresh SHAD assignment deadlines hourly and after sign-in, independently of the weekly widget.</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition><Interval>PT1H</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
      <StartBoundary>$firstRun</StartBoundary><Enabled>true</Enabled>
    </TimeTrigger>
    <LogonTrigger><Enabled>true</Enabled><UserId>$userSid</UserId><Delay>PT30S</Delay></LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="CurrentUser"><UserId>$userSid</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled><Hidden>true</Hidden>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT3M</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure><Interval>PT10M</Interval><Count>3</Count></RestartOnFailure>
  </Settings>
  <Actions Context="CurrentUser"><Exec><Command>$exeXml</Command><Arguments>$argsXml</Arguments><WorkingDirectory>$dirXml</WorkingDirectory></Exec></Actions>
</Task>
"@
$task = Register-ScheduledTask -TaskName $taskName -Xml $taskXml -Force
$settings = [ordered]@{
    enabled = $true
    provider = 'Windows Task Scheduler'
    task_name = $taskName
    interval_seconds = 3600
    at_logon = $true
}
$target = Join-Path $dataDir 'shad-background.json'
$temporary = $target + '.tmp'
$settings | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding UTF8
Move-Item -LiteralPath $temporary -Destination $target -Force
Start-ScheduledTask -TaskName $taskName
Write-Output ('Installed: ' + $taskName + '; interval: 1 hour; also at sign-in')
