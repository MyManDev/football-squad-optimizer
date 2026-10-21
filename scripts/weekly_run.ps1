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
  powershell -ExecutionPolicy Bypass -File scripts\weekly_run.ps1 -Kind friday -ClubNewsSettings C:\private\club-news.settings.toml

Every Friday run first acquires the week's club news. Use -ClubNewsSettings (or the
SQUADOPT_CLUB_NEWS_SETTINGS environment variable) for the private settings file.
The script runs scripts.capture_club_news, which fetches the registered
club pages and codes them with the configured model, from the newest capture's
roster, and passes the new capture to the weekly command as --rotation-capture, so the
manager's word rides on real news instead of the committed fixture. -ClubNews does the same
with no file, from the shell's own SQUADOPT_LLM_PROVIDER, SQUADOPT_LLM_API_KEY and optional
SQUADOPT_LLM_MODEL (set them in the window that runs this script; the script never prints
them). A capture that produces no id is a refusal: the run does not fall back to the fixture
silently, because a published week without the word is exactly what the option exists to
prevent. Acquisition output is kept in <run id>.club-news.log, separately from the weekly
command's <run id>.log, so starting the weekly command cannot overwrite the news receipt.
Tuesday keeps its existing cadence; -ClubNews or -ClubNewsSettings opts it into acquisition.

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
    [string]$ClubNewsSettings = '',
    [switch]$ClubNews,
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

function Build-WeeklyArguments([string]$kind, [string]$season, [int]$gameweek, [int]$workers, [string]$runId, [string]$suffix, [string]$rotationCapture = '') {
    if ($kind -eq 'friday' -and -not $rotationCapture) {
        throw 'A Friday decision requires a real club-news capture; the example fixture cannot be published instead.'
    }
    # The cadence's arguments, as the 10 and 14 October publishes ran them; a club-news
    # capture, when one was acquired, is what the rotation stage reads instead of the fixture.
    $arguments = @(
        '-m', 'squadopt.platform.weekly_operations',
        '--season', $season,
        '--gameweek', [string]$gameweek,
        '--league-list', 'config/leagues.json',
        '--workers', [string]$workers,
        '--projection', 'component-only',
        '--rotation'
    )
    if ($rotationCapture) { $arguments += @('--rotation-capture', $rotationCapture) }
    $arguments += @(
        '--record-advice',
        '--publish',
        '--publish-suffix', $suffix,
        '--run-id', $runId
    )
    return $arguments
}

function Latest-Capture([string]$repo) {
    # The newest fpl-live capture on disk supplies the roster the club-news acquisition reads.
    $captures = @(Get-ChildItem -LiteralPath (Join-Path $repo 'data\snapshots') -Directory -Filter 'fpl-live-*' | Sort-Object Name)
    if ($captures.Count -eq 0) { throw "No fpl-live capture under data\snapshots to read a roster from." }
    return $captures[-1].Name
}

function Captured-NewsId([string[]]$lines) {
    # scripts.capture_club_news prints "Capture       club-news-<stamp>-<hash>" once it has written the week.
    foreach ($line in $lines) {
        if ($line -match '^Capture\s+(club-news-\S+)') { return $Matches[1] }
    }
    return ''
}

function Acquire-WeeklyNews([string]$python, [string]$repo, [string]$settings, [string]$newsLog) {
    $configuration = @('-m', 'scripts.capture_club_news', '--check-config')
    if ($settings) { $configuration += @('--settings-file', $settings) }
    $checkLines = @(& $python @configuration 2>&1 | ForEach-Object { [string]$_ })
    $checkExit = $LASTEXITCODE
    $checkLines | Set-Content -LiteralPath $newsLog -Encoding UTF8
    if ($checkExit -ne 0) {
        throw 'Club-news configuration failed its offline check; no news was requested. Read the club-news log.'
    }
    $roster = Latest-Capture $repo
    $arguments = @('-m', 'scripts.capture_club_news', '--roster-snapshot', $roster)
    if ($settings) { $arguments += @('--settings-file', $settings) }
    $newsLines = @(& $python @arguments 2>&1 | ForEach-Object { [string]$_ })
    $newsExit = $LASTEXITCODE
    $newsLines | Add-Content -LiteralPath $newsLog -Encoding UTF8
    if ($newsExit -ne 0) { throw 'Club-news acquisition failed; the weekly decision was not started. Read the club-news log.' }
    $capture = Captured-NewsId $newsLines
    if (-not $capture) { throw 'Club-news acquisition produced no capture id; the weekly decision was not started.' }
    return $capture
}

function Weekly-NewsCapture([string]$kind, [string]$python, [string]$repo, [string]$settings, [bool]$includeNews, [bool]$preview, [string]$newsLog) {
    if ($kind -ne 'friday' -and -not $includeNews -and -not $settings) { return '' }
    if (-not $settings) { $settings = $env:SQUADOPT_CLUB_NEWS_SETTINGS }
    if (-not $settings) { $settings = [Environment]::GetEnvironmentVariable('SQUADOPT_CLUB_NEWS_SETTINGS', 'User') }
    if ($settings -and -not (Test-Path -LiteralPath $settings)) { throw "Club-news settings file not found at $settings." }
    if ($preview) { return '<club-news capture>' }
    return (Acquire-WeeklyNews $python $repo $settings $newsLog)
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
$python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$logDirectory = Join-Path $RepoRoot 'data\logs\weekly'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$log = Join-Path $logDirectory ($runId + '.log')
$newsLog = Join-Path $logDirectory ($runId + '.club-news.log')
$env:PYTHONPATH = (Join-Path $RepoRoot 'src') + ';' + $RepoRoot
try { $rotationCapture = Weekly-NewsCapture $Kind $python $RepoRoot $ClubNewsSettings ([bool]$ClubNews) ([bool]$DryRun) $newsLog }
catch { Write-Output ("Refused: {0}" -f $_.Exception.Message); Write-Output ("club-news log: {0}" -f $newsLog); exit 2 }
if ($rotationCapture -and -not $DryRun) {
    Write-Output ("club news: capture {0}" -f $rotationCapture)
    Write-Output ("club-news log: {0}" -f $newsLog)
}
$arguments = Build-WeeklyArguments $Kind $season $Gameweek $Workers $runId $suffix $rotationCapture
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
if ($rotationCapture) {
    Write-Output ("The manager's word rode on club-news capture {0}; the football bundle must be sealed with it:" -f $rotationCapture)
    Write-Output ('  python -m scripts.prepare_football_bundle ... --news-capture-id ' + $rotationCapture + ' --rotation-table artifacts\rotation\<the rotation_evidence_v4 table this run wrote>')
}
exit 0
