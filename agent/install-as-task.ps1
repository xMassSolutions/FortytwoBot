param(
    [Parameter(Mandatory)] [string]$BotUrl,
    [Parameter(Mandatory)] [string]$AgentToken,
    [string]$TaskName = "FortytwoBotAgent",
    [string]$ScriptsRoot = "C:\Users\youruser\FortytwoCLI\fortytwo-p2p-inference-scripts-main"
)

$here   = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $here "push-agent.ps1"
if (-not (Test-Path $script)) { throw "push-agent.ps1 not found at $script" }

# Wrapper that sets env vars, logs to a rolling file, and restarts the agent if it dies
$wrapper = Join-Path $here "_agent-wrapper.ps1"
$logFile = Join-Path $here "agent.log"

$wrapperContent = @"
`$env:FORTYTWO_BOT_URL = '$BotUrl'
`$env:FORTYTWO_AGENT_TOKEN = '$AgentToken'
while (`$true) {
    try {
        & '$script' -ScriptsRoot '$ScriptsRoot' *>> '$logFile'
    } catch {
        ('agent died: ' + `$_.Exception.Message + ' — restarting in 10s') | Out-File -FilePath '$logFile' -Append
        Start-Sleep -Seconds 10
    }
}
"@
Set-Content -Path $wrapper -Value $wrapperContent -Encoding UTF8

$action    = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$wrapper`""
$trigger   = New-ScheduledTaskTrigger -AtLogOn
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Output "Scheduled Task '$TaskName' installed."
Write-Output "Wrapper: $wrapper"
Write-Output "Logs:    $logFile"
Write-Output ""
Write-Output "Starting now..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2
Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo | Format-List TaskName, LastRunTime, LastTaskResult, NextRunTime
