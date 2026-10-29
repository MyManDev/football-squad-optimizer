<#
.SYNOPSIS
Decide on a schedule whether a weekly run starts now: a morning run once a UTC day, and a
final run a fixed lead before each deadline (#1243).
.DESCRIPTION
Windows PowerShell 5.1. A Task Scheduler task calls this every 15 minutes. It reads the
deadlines from the public FPL bootstrap (cached under data\runtime\weekly-schedule for an
hour), takes the first gameweek whose deadline is still ahead, and starts at most one run
through weekly_run.ps1 for that gameweek:

- the final run, once per gameweek, from the deadline minus -FinalLeadHours;
- a morning run, once per UTC day, from -MorningUtc, unless the final run would start before
  a morning run could finish (-RunHours).

Deadlines decide, not weekdays, so a midweek deadline needs no exception. Each start leaves a
marker under data\runtime\weekly-schedule\started (morning-<date>.json or
final-<season>-gw<NN>.json) before weekly_run.ps1 runs, so a run that fails is not started
again by the next tick. Each run gets its own site suffix (morning-<stamp> or final-<stamp>),
so a morning run and a final run on the same day do not collide. The release after the run
is not part of this script (#1243, step 3).

The defaults are the proposal on #1243; its decisions D2 (the final run's lead) and D3 (club
news on every run) set them. A lead shorter than a run is refused: such a final run cannot be
live before its deadline (GW8: 3 h 34 min from capture to live).

  powershell -ExecutionPolicy Bypass -File scripts\weekly_schedule.ps1 -DryRun
  powershell -ExecutionPolicy Bypass -File scripts\weekly_schedule.ps1 -DryRun -Now 2026-10-31T07:05:00Z

-DryRun prints the decision and the command it would run; it writes nothing under data and
starts nothing. The exit code is 0 for a decision (starting nothing is one), the weekly run's
own exit code when one started, 3 when the final run's window was missed, and 2 for a
refusal: no deadline ahead, an unreadable bootstrap, or a lead shorter than a run.
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [string]$MorningUtc = '02:00',
    [double]$FinalLeadHours = 4.0,
    [double]$RunHours = 3.5,
    [ValidateSet('tuesday', 'friday')][string]$MorningKind = 'friday',
    [string]$BootstrapPath = '',
    [string]$Now = '',
    [switch]$DryRun
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$BootstrapUrl = 'https://fantasy.premierleague.com/api/bootstrap-static/'

function Parse-Utc([string]$text) {
    return [datetime]::Parse($text, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AdjustToUniversal)
}

function Format-Utc([datetime]$instant) {
    return $instant.ToString('yyyy-MM-ddTHH:mmZ', [Globalization.CultureInfo]::InvariantCulture)
}

function Say([string]$format) {
    # Numbers in messages read the same on every PC's culture (3.5, never 3,5).
    return [string]::Format([Globalization.CultureInfo]::InvariantCulture, $format, [object[]]$args)
}

function Schedule-Season([string]$fixturesPath) {
    # The season the published site serves, as weekly_run.ps1 reads it.
    $document = Get-Content -LiteralPath $fixturesPath -Raw -Encoding UTF8 | ConvertFrom-Json
    return [string]$document.payload.season
}

function Schedule-Events([string]$bootstrapPath) {
    # One row per gameweek from the bootstrap's events, in gameweek order.
    $document = Get-Content -LiteralPath $bootstrapPath -Raw -Encoding UTF8 | ConvertFrom-Json
    return @($document.events | ForEach-Object {
        [pscustomobject]@{ Gameweek = [int]$_.id; Deadline = (Parse-Utc ([string]$_.deadline_time)) }
    } | Sort-Object Gameweek)
}

function Save-Bootstrap([string]$path) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $partial = $path + '.partial'
    Invoke-WebRequest -Uri $BootstrapUrl -UserAgent 'squadopt-weekly-schedule' -OutFile $partial -UseBasicParsing -TimeoutSec 60
    Move-Item -LiteralPath $partial -Destination $path -Force
}

function Fresh-Bootstrap([string]$cache, [int]$maxAgeMinutes, [datetime]$now) {
    # Deadlines move rarely; one read an hour is enough for a gate that ticks every 15 minutes.
    if ((Test-Path -LiteralPath $cache) -and (($now - (Get-Item -LiteralPath $cache).LastWriteTimeUtc).TotalMinutes -lt $maxAgeMinutes)) {
        return $cache
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $cache) | Out-Null
    Save-Bootstrap $cache
    return $cache
}

function Schedule-Markers([string]$directory) {
    if (-not (Test-Path -LiteralPath $directory)) { return @() }
    return @(Get-ChildItem -LiteralPath $directory -Filter '*.json' -File | ForEach-Object { $_.BaseName })
}

function Morning-Start([datetime]$now, [string]$morningUtc) {
    if ($morningUtc -notmatch '^([01][0-9]|2[0-3]):([0-5][0-9])$') { throw "-MorningUtc must be HH:mm in UTC, not '$morningUtc'." }
    return ([datetime]::SpecifyKind($now.Date, 'Utc')).AddHours([int]$Matches[1]).AddMinutes([int]$Matches[2])
}

function Schedule-Decision($events, [datetime]$now, [string]$season, [string[]]$markers, [string]$morningUtc, [double]$leadHours, [double]$runHours) {
    # Pure: the action for this tick, from the deadlines, the clock and the runs already started.
    if ($leadHours -lt $runHours) {
        throw (Say 'A final run {0} h before the deadline cannot be live before it: a run takes about {1} h.' $leadHours $runHours)
    }
    $ahead = @($events | Where-Object { $_.Deadline -gt $now })
    if ($ahead.Count -eq 0) { throw "No gameweek deadline lies ahead of $(Format-Utc $now) in the bootstrap." }
    $open = $ahead[0]
    $finalStart = $open.Deadline.AddHours(-$leadHours)
    $final = 'final-{0}-gw{1:d2}' -f $season, $open.Gameweek
    $morning = 'morning-{0}' -f $now.ToString('yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
    $morningStart = Morning-Start $now $morningUtc
    $decision = [pscustomobject]@{
        Action = 'none'; Gameweek = $open.Gameweek; Deadline = $open.Deadline
        FinalStart = $finalStart; Marker = ''; Reason = ''
    }
    if ($now -ge $finalStart) {
        if ($markers -contains $final) {
            $decision.Reason = "the final run for gameweek $($open.Gameweek) has already started"
        } elseif (($open.Deadline - $now).TotalHours -lt $runHours) {
            $decision.Action = 'missed'
            $decision.Reason = (Say 'the final run for gameweek {0} did not start: the deadline is {1:0} min away and a run takes about {2} h' $open.Gameweek ($open.Deadline - $now).TotalMinutes $runHours)
        } else {
            $decision.Action = 'final'; $decision.Marker = $final
            $decision.Reason = "the final run for gameweek $($open.Gameweek)"
        }
    } elseif ($now -lt $morningStart) {
        $decision.Reason = "today's morning run starts at $(Format-Utc $morningStart)"
    } elseif ($markers -contains $morning) {
        $decision.Reason = "today's morning run has already started"
    } elseif (($finalStart - $now).TotalHours -lt $runHours) {
        $decision.Reason = "the final run starts at $(Format-Utc $finalStart), before a morning run could finish"
    } else {
        $decision.Action = 'morning'; $decision.Marker = $morning
        $decision.Reason = "today's morning run for gameweek $($open.Gameweek)"
    }
    return $decision
}

function Run-Kind([string]$action, [string]$morningKind) {
    # The final run is the decision run with real club news; D3 on #1243 sets the morning's.
    if ($action -eq 'final') { return 'friday' }
    return $morningKind
}

function Run-Suffix([string]$action, [datetime]$now) {
    # weekly_run.ps1's own suffix is one per kind and day; two runs on a deadline day need two.
    return ('{0}-{1}' -f $action, $now.ToString('yyyyMMddTHHmm', [Globalization.CultureInfo]::InvariantCulture))
}

if ($MyInvocation.InvocationName -eq '.') { return }

$clock = if ($Now) { Parse-Utc $Now } else { (Get-Date).ToUniversalTime() }
$stateDirectory = Join-Path $RepoRoot 'data\runtime\weekly-schedule'
$startedDirectory = Join-Path $stateDirectory 'started'
$temporary = ''
$refusal = ''
try {
    $season = Schedule-Season (Join-Path $RepoRoot 'web\public\data\fixtures.json')
    $bootstrap = $BootstrapPath
    if (-not $bootstrap -and $DryRun) {
        $temporary = [IO.Path]::GetTempFileName()
        Save-Bootstrap $temporary
        $bootstrap = $temporary
    } elseif (-not $bootstrap) {
        $bootstrap = Fresh-Bootstrap (Join-Path $stateDirectory 'bootstrap.json') 60 $clock
    }
    $decision = Schedule-Decision (Schedule-Events $bootstrap) $clock $season (Schedule-Markers $startedDirectory) $MorningUtc $FinalLeadHours $RunHours
} catch {
    $refusal = $_.Exception.Message
} finally {
    if ($temporary -and (Test-Path -LiteralPath $temporary)) { Remove-Item -LiteralPath $temporary }
}
if ($refusal) { Write-Output "Refused: $refusal"; exit 2 }

Write-Output ('gate at {0}: {1} gameweek {2}, deadline {3}, final run from {4}' -f (Format-Utc $clock), $season, $decision.Gameweek, (Format-Utc $decision.Deadline), (Format-Utc $decision.FinalStart))
Write-Output ('decision: {0} ({1})' -f $decision.Action, $decision.Reason)
if ($decision.Action -eq 'missed') { exit 3 }
if ($decision.Action -eq 'none') { exit 0 }

$kind = Run-Kind $decision.Action $MorningKind
$suffix = Run-Suffix $decision.Action $clock
$script = Join-Path $RepoRoot 'scripts\weekly_run.ps1'
$arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $script, '-Kind', $kind, '-Gameweek', [string]$decision.Gameweek, '-Suffix', $suffix)
if ($DryRun) {
    Write-Output ('would run: powershell.exe {0}' -f ($arguments -join ' '))
    exit 0
}
New-Item -ItemType Directory -Force -Path $startedDirectory | Out-Null
[pscustomobject]@{
    action = $decision.Action; gameweek = $decision.Gameweek; deadline_utc = (Format-Utc $decision.Deadline)
    kind = $kind; suffix = $suffix; started_at_utc = (Format-Utc $clock)
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $startedDirectory ($decision.Marker + '.json')) -Encoding UTF8
Write-Output ('starting: powershell.exe {0}' -f ($arguments -join ' '))
& powershell.exe @arguments
exit $LASTEXITCODE
