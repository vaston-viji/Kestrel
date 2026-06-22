# Manual trigger for testing. Usage: .\scripts\run_once.ps1 -Slot morning
param([ValidateSet("morning","afternoon")][string]$Slot = "morning")
$root = (Resolve-Path "$PSScriptRoot\..").Path
& "$root\.venv\Scripts\python.exe" -m kestrel run --slot $Slot
