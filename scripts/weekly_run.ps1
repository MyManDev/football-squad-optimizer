<#
.SYNOPSIS
Start one weekly run on this PC the way the planner's Start button does: Tuesday settles,
Friday decides.
.DESCRIPTION
Windows PowerShell 5.1. The two wrappers, weekly_run_tuesday.ps1 and weekly_run_friday.ps1,
call this with -Kind. The script reads the open gameweek from the published fixtures
document, refuses a dirty checkout, a checkout that is not on develop, or a weekly run
already in progress, fast-forwards develop, and runs the weekly command with the
cadence's arguments, writing everything it prints to data\logs\weekly\<run id>.log. It
ends by printing the site pull request the run opened, the exact ship.sh line (the
release stays a person's act) and the VM sync that follows the release. Nothing here
publishes, tags, deploys or restarts anything.

  powershell -ExecutionPolicy Bypass -File scripts\weekly_run.ps1 -Kind friday
  powershell -ExecutionPolicy Bypass -File scripts\weekly_run.ps1 -Kind tuesday -DryRun
  powershell -ExecutionPolicy Bypass -File scripts\weekly_run.ps1 -Kind friday -Gameweek 8

The exit code is the weekly command's (0 when the run completed and the site pull request
is open), 2 for a refusal before anything ran. A Tuesday run is the next gameweek's run
carrying the settled week (the settled publish is not a separate run); its tag is
site-<season>-gw<settled>-settled, or the next fix tag when that one exists. A Friday run's
tag is site-<season>-gw<open>-decision, or the next fix tag.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('tuesday', 'friday')][string]$Kind,
    [string]$RepoRoot = '',
    [int]$Workers = 15,
    [int]$Gameweek = 0,
    [switch]$DryRun
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path

function Resolve-OpenGameweek([string]$fixturesPath, [datetime]$now) {
    # The first gameweek whose deadline is still ahead, from the published fixtures document.
    $document = Get-Content -LiteralPath $fixturesPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $ahead = @($document.payload.gameweeks | Where-Object {
        ([datetime]::Parse($_.deadline_utc, $null, [Globalization.DateTimeStyles]::AdjustToUniversal)) -gt $now
    } | Sort-Object { [int]$_.gameweek })
    if ($ahead.Count -eq 0) { throw "No gameweek deadline lies ahead of $($now.ToString('u')) in $fixturesPath." }
    return [int]$ahead[0].gameweek
}

function Weekly-Season([string]$fixturesPath) {
    $document = Get-Content -LiteralPath $fixturesPath -Raw -Encoding UTF8 | ConvertFrom-Json
    return [string]$document.payload.season
}

function Weekly-RunId([string]$kind, [string]$season, [int]$gameweek, [datetime]$now) {
    return ('{0}-gw{1:d2}-{2}-{3}' -f $season, $gameweek, $kind, $now.ToUniversalTime().ToString('yyyyMMddTHHmmZ'))
}

function Weekly-Suffix([string]$kind, [datetime]$now) {
    # The site branch is feature/gw<NN>-decision-site-<suffix>; the run refuses a used suffix.
    return ('{0}-{1}' -f $kind, $now.ToUniversalTime().ToString('yyyyMMdd'))
}

function Build-WeeklyArguments([string]$season, [int]$gameweek, [int]$workers, [string]$runId, [string]$suffix) {
    # The cadence's arguments, as the 10 and 14 October publishes ran them.
    return @(
        '-m', 'squadopt.platform.weekly_operations',
        '--season', $season,
        '--gameweek', [string]$gameweek,
        '--league-list', 'config/leagues.json',
        '--workers', [string]$workers,
        '--projection', 'component-only',
        '--rotation',
        '--record-advice',
        '--publish',
        '--publish-suffix', $suffix,
        '--run-id', $runId
    )
}

function Suggested-Tag([string]$kind, [string]$season, [int]$gameweek, [string[]]$existingTags) {
    # Tags are immutable and never reused: the first unused one under the cadence's naming.
    if ($kind -eq 'tuesday') {
        $week = $gameweek - 1
        $first = ('site-{0}-gw{1:d2}-settled' -f $season, $week)
    } else {
        $week = $gameweek
        $first = ('site-{0}-gw{1:d2}-decision' -f $season, $week)
    }
    if ($existingTags -notcontains $first) { return $first }
    $n = 1
    while ($existingTags -contains ('site-{0}-gw{1:d2}-fix{2}' -f $season, $week, $n)) { $n += 1 }
    return ('site-{0}-gw{1:d2}-fix{2}' -f $season, $week, $n)
}

function Assert-RunnableCheckout([string]$repo) {
    $dirty = @(& git -C $repo status --porcelain)
    if ($dirty.Count -gt 0) { throw "Checkout is not clean ($($dirty.Count) changed path(s)); commit or set the work aside first." }
    $branch = (& git -C $repo branch --show-current).Trim()
    if ($branch -ne 'develop') { throw "Checkout must be on develop (it is on '$branch')." }
    $running = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq 'python.exe' -and $_.CommandLine -match 'squadopt\.platform\.weekly_operations'
    })
    if ($running.Count -gt 0) { throw "A weekly run is already in progress (pid $($running[0].ProcessId)); wait for it." }
}

function Published-PullRequest([string]$logPath) {
    $line = Select-String -LiteralPath $logPath -Pattern '^PR: (https://github\.com/\S+)' | Select-Object -First 1
    if ($null -eq $line) { return '' }
    return $line.Matches[0].Groups[1].Value
}

if ($MyInvocation.InvocationName -eq '.') { return }

$fixtures = Join-Path $RepoRoot 'web\public\data\fixtures.json'
if (-not (Test-Path -LiteralPath $fixtures)) { Write-Output "No published fixtures document at $fixtures."; exit 2 }
$now = (Get-Date).ToUniversalTime()
try {
    Assert-RunnableCheckout $RepoRoot
    if (-not $DryRun) { & git -C $RepoRoot pull -q --ff-only | Out-Null }
    $season = Weekly-Season $fixtures
    if ($Gameweek -le 0) { $Gameweek = Resolve-OpenGameweek $fixtures $now }
} catch {
    Write-Output "Refused: $($_.Exception.Message)"
    exit 2
}
$runId = Weekly-RunId $Kind $season $Gameweek $now
$suffix = Weekly-Suffix $Kind $now
$arguments = Build-WeeklyArguments $season $Gameweek $Workers $runId $suffix
$python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$logDirectory = Join-Path $RepoRoot 'data\logs\weekly'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$log = Join-Path $logDirectory ($runId + '.log')
$tags = @(& git -C $RepoRoot ls-remote --tags origin ('site-{0}-gw*' -f $season) | ForEach-Object { ($_ -split '\s+')[1] -replace '^refs/tags/', '' } | Where-Object { $_ -notmatch '\^\{\}$' })
$tag = Suggested-Tag $Kind $season $Gameweek $tags

Write-Output ("{0} run: {1} gameweek {2}, {3} workers, run id {4}, site suffix {5}" -f $Kind, $season, $Gameweek, $Workers, $runId, $suffix)
Write-Output ("log: {0}" -f $log)
if ($DryRun) {
    Write-Output ("would run: {0} {1}" -f $python, ($arguments -join ' '))
    Write-Output ("suggested tag: {0}" -f $tag)
    exit 0
}

$env:PYTHONPATH = (Join-Path $RepoRoot 'src') + ';' + $RepoRoot
$started = (Get-Date).ToUniversalTime()
$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $log -RedirectStandardError ($log + '.err') -NoNewWindow -Wait -PassThru
$minutes = [int](((Get-Date).ToUniversalTime() - $started).TotalMinutes)
if (Test-Path -LiteralPath ($log + '.err')) { Get-Content -LiteralPath ($log + '.err') | Add-Content -LiteralPath $log; Remove-Item -LiteralPath ($log + '.err') }
if ($process.ExitCode -ne 0) {
    Write-Output ("The weekly command exited {0} after {1} min; read {2}" -f $process.ExitCode, $minutes, $log)
    exit $process.ExitCode
}
$pullRequest = Published-PullRequest $log
Write-Output ("Run completed in {0} min." -f $minutes)
if ($pullRequest) { Write-Output ("Site pull request: {0}" -f $pullRequest) }
$number = if ($pullRequest) { ($pullRequest -split '/')[-1] } else { '<site PR>' }
$week = if ($Kind -eq 'tuesday') { $Gameweek - 1 } else { $Gameweek }
$settledArgument = if ($Kind -eq 'tuesday') { ' ' + $week } else { '' }
Write-Output ''
Write-Output 'Next, a person: once the site pull request is merged through the queue, read the accepted'
Write-Output 'stamp (data/leagues.json generated_at_utc in the preview) and release from Git Bash:'
Write-Output ("  sh scripts/release/ship.sh {0} {1} release/{2} <accepted generated-at ISO> '<summary>'{3}" -f $number, $tag, ($tag -replace '^site-[0-9]{4}-[0-9]{2}-', ''), $settledArgument)
Write-Output ('Then move the VM to the release: bash scripts/vm_push.sh ' + $tag)
exit 0
