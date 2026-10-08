# Starts the Telegram approval bot and keeps it running.
#
# Run it by hand, from a PowerShell window (two lines):
#   cd C:\Users\rro\Documents\internship-hunter
#   .\start_bot.ps1
# If it says scripts are disabled, run this once in that window and try again:
#   Set-ExecutionPolicy -Scope Process Bypass
# Run it at every sign-in (once, in PowerShell):
#   $action  = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
#       -Argument "-ExecutionPolicy Bypass -WindowStyle Minimized -File `"$PWD\start_bot.ps1`""
#   $trigger = New-ScheduledTaskTrigger -AtLogOn
#   Register-ScheduledTask -TaskName "Internship Hunter bot" -Action $action -Trigger $trigger
# Remove that again:   Unregister-ScheduledTask -TaskName "Internship Hunter bot"
#
# The bot has to run on this PC (not in the cloud): approved applications
# open in a browser here for you to submit, and it uses your Gmail sign-in.

Set-Location -Path $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$log = Join-Path $PSScriptRoot "data\bot.log"

while ($true) {
    "$(Get-Date -Format s) starting bot" | Out-File -FilePath $log -Append -Encoding utf8
    & $python -u -m internship_hunter.approvals.cli bot *>> $log
    # If it ever exits (crash, network drop at startup), wait and start again.
    "$(Get-Date -Format s) bot stopped (exit $LASTEXITCODE); restarting in 30s" | Out-File -FilePath $log -Append -Encoding utf8
    Start-Sleep -Seconds 30
}
