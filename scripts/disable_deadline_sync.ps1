$ErrorActionPreference = 'Stop'
$taskName = 'WeeklyScheduleWidgetHourlySync'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
$dataDir = if ($env:WEEKLY_SCHEDULE_DATA_DIR) { $env:WEEKLY_SCHEDULE_DATA_DIR } else { Join-Path $env:LOCALAPPDATA 'WeeklyScheduleWidgetPublic' }
$metadata = Join-Path $dataDir 'shad-background.json'
if (Test-Path -LiteralPath $metadata) {
    @{ enabled = $false; interval_seconds = 3600 } | ConvertTo-Json | Set-Content -LiteralPath $metadata -Encoding UTF8
}
Write-Output 'Background deadline synchronization disabled. Local account data was kept.'
