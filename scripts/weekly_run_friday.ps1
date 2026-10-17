<#
.SYNOPSIS
The Friday decision run, as the planner's Start button runs it: weekly_run.ps1 -Kind friday.
.DESCRIPTION
Windows PowerShell 5.1. Every argument is passed through to scripts\weekly_run.ps1, which
reads the open gameweek from the published fixtures document, refuses a dirty or busy
checkout, runs the weekly command with the cadence's arguments and prints the site pull
request and the ship.sh line at the end. The release stays a person's act.

  powershell -ExecutionPolicy Bypass -File scripts\weekly_run_friday.ps1
  powershell -ExecutionPolicy Bypass -File scripts\weekly_run_friday.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [int]$Workers = 15,
    [int]$Gameweek = 0,
    [string]$ClubNewsSettings = '',
    [switch]$DryRun
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'weekly_run.ps1'
$arguments = @{ Kind = 'friday'; Workers = $Workers; Gameweek = $Gameweek; ClubNewsSettings = $ClubNewsSettings }
if ($RepoRoot) { $arguments.RepoRoot = $RepoRoot }
if ($DryRun) { $arguments.DryRun = $true }
& $script @arguments
exit $LASTEXITCODE
