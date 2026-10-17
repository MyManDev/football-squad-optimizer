<#
.SYNOPSIS
The Tuesday settled run, as the planner's Start button runs it: weekly_run.ps1 -Kind tuesday.
.DESCRIPTION
Windows PowerShell 5.1. The settled publish is not a separate run: it is the next
gameweek's run carrying the settled week in its scoreboard, so this is the same weekly
command as Friday's with the settled tag at the end (site-<season>-gw<settled>-settled, or
the next fix tag). Every argument is passed through to scripts\weekly_run.ps1.

  powershell -ExecutionPolicy Bypass -File scripts\weekly_run_tuesday.ps1
  powershell -ExecutionPolicy Bypass -File scripts\weekly_run_tuesday.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [int]$Workers = 15,
    [int]$Gameweek = 0,
    [string]$ClubNewsSettings = '',
    [switch]$ClubNews,
    [switch]$DryRun
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'weekly_run.ps1'
$arguments = @{ Kind = 'tuesday'; Workers = $Workers; Gameweek = $Gameweek; ClubNewsSettings = $ClubNewsSettings }
if ($RepoRoot) { $arguments.RepoRoot = $RepoRoot }
if ($DryRun) { $arguments.DryRun = $true }
if ($ClubNews) { $arguments.ClubNews = $true }
& $script @arguments
exit $LASTEXITCODE
