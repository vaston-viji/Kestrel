# Registers Kestrel morning and afternoon scheduled tasks (Australia/Sydney).
# Run once from an elevated PowerShell in the project root, with the venv created.
param(
  [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
  [string]$Python = "$ProjectRoot\.venv\Scripts\python.exe"
)

function New-KestrelTask($name, $slot, $time) {
  $action  = New-ScheduledTaskAction -Execute $Python -Argument "-m kestrel run --slot $slot" -WorkingDirectory $ProjectRoot
  $trigger = New-ScheduledTaskTrigger -Daily -At $time
  # Wake the machine; run as soon as possible if a scheduled start was missed.
  $settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
  Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force -RunLevel Limited
  Write-Host "Registered $name at $time"
}

New-KestrelTask "Kestrel Morning Brief"   "morning"   "07:00"
New-KestrelTask "Kestrel Afternoon Brief" "afternoon" "11:30"
Write-Host "Done. Verify in Task Scheduler. Confirm the machine's timezone is Australia/Sydney."
