<#
.SYNOPSIS
Release one completed weekly run with no person in the loop: what weekly_run.ps1 prints for a
person, in order, stopping at the first step that fails (#1243, step 3).
.DESCRIPTION
Windows PowerShell 5.1. weekly_schedule.ps1 -Release calls this after a run it started exits
0. From the run's log, and its journal and preview under data\runtime\weekly\<run id>, it reads
the site pull request and the accepted stamp (generated_at_utc in the preview's
data\leagues.json), runs scripts.check_league_tree on the preview, waits for the pull request's
required checks, enqueues it with the GraphQL enqueuePullRequest mutation at the commit the run
published (develop merges only through its queue), waits until it has merged, runs ship.sh with
the first unused tag and that stamp (ship.sh verifies the live site), runs vm_push.sh, and on a
run that rode on club news seals the football bundle, once the forecast it seals exists.

Each step writes one line to data\logs\weekly\<run id>.release.log; the commands' output goes
to <run id>.release-commands.log. The release log is the run's marker too: a run that has one
is never released again, because a release that stopped part-way may already be public and
only a person can tell (docs/deployment_runbook.md, "The release window is closed to develop").
A refusal before the enqueue changes nothing, and the last accepted publication stays live.

  powershell -ExecutionPolicy Bypass -File scripts\weekly_release.ps1 -RunId 2026-27-gw10-friday-20261106T1430Z

The exit code is 0 when every step completed, 2 for a refusal before the enqueue, and 1 for a
stop after it, which a person reconciles from the two logs.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$')][string]$RunId,
    [string]$RepoRoot = '',
    [ValidatePattern('^[^"]+$')][string]$Summary = 'Publish the tree the scheduled weekly run recorded (#1243).',
    [int]$WaitMinutes = 60
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
# Published-PullRequest and Suggested-Tag, the reads behind the lines weekly_run.ps1 prints.
. (Join-Path $PSScriptRoot 'weekly_run.ps1') -Kind friday -RepoRoot $RepoRoot
# The expected head makes the queue refuse a pull request that moved after the run published it.
$EnqueueMutation = 'mutation($id: ID!, $head: GitObjectID) { enqueuePullRequest(input: {pullRequestId: $id, expectedHeadOid: $head}) { mergeQueueEntry { position } } }'

function Say([string]$format) {
    # Numbers in messages read the same on every PC's culture.
    return [string]::Format([Globalization.CultureInfo]::InvariantCulture, $format, [object[]]$args)
}

function Invoke-External([string]$name, [string[]]$arguments) {
    # The one door to every outside command, so a test can put a fake in its place.
    $command = $name
    if ($name -eq 'python') { $command = Join-Path $RepoRoot '.venv\Scripts\python.exe' }
    if ($name -in 'sh', 'bash') {
        # Git for Windows' own shell, never another bash.exe on PATH such as WSL's.
        $git = (Get-Command git.exe).Source -replace '\\(cmd|mingw64\\bin)\\git\.exe$', ''
        $command = Join-Path $git ('bin\' + $name + '.exe')
    }
    # A missing command would leave the previous command's exit code behind as its own.
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { return [pscustomobject]@{ Exit = 127; Lines = @("$command not found") } }
    $ErrorActionPreference = 'Continue'  # a native command's stderr is output here, not a throw
    $lines = @(& $command @arguments 2>&1 | ForEach-Object { [string]$_ })
    $code = $LASTEXITCODE
    if ($lines.Count -gt 0) { Add-Content -LiteralPath $script:CommandsLog -Value $lines -Encoding UTF8 }
    return [pscustomobject]@{ Exit = $code; Lines = $lines }
}

function Pause-Release([int]$seconds) { Start-Sleep -Seconds $seconds }

function Release-Line([string]$path, [string]$text) {
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ', [Globalization.CultureInfo]::InvariantCulture)
    Add-Content -LiteralPath $path -Value ('{0} {1}' -f $stamp, $text) -Encoding UTF8
}

function Release-Inputs([string]$repo, [string]$runId) {
    # What the run left behind: its journal, its preview and the pull request its log names.
    $directory = Join-Path $repo ('data\runtime\weekly\' + $runId)
    $journal = Get-Content -LiteralPath (Join-Path $directory 'run.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($journal.status -ne 'completed') { throw "Run $runId is $($journal.status), not completed." }
    if ($runId -notmatch '-gw[0-9]{2}-(tuesday|friday)-') { throw "Run id $runId names no tuesday or friday run." }
    $kind = $Matches[1]
    $stages = @{}
    foreach ($stage in @($journal.stages)) { $stages[$stage.name] = $stage }
    $preview = Join-Path $directory 'preview\data'
    if (-not (Test-Path -LiteralPath (Join-Path $preview 'leagues.json'))) { throw 'The preview has no data\leagues.json to read the accepted stamp from.' }
    $pullRequest = Published-PullRequest (Join-Path $repo ('data\logs\weekly\' + $runId + '.log'))
    if (-not $pullRequest) { throw "The run's log names no site pull request." }
    $news = [string]$journal.request.request.rotation_capture
    $retained = @($stages['handoff'].outputs | Where-Object { $_.path -match '[\\/]by-capture[\\/]' } | ForEach-Object { [string]$_.path })
    return [pscustomobject]@{
        Kind = $kind; Season = [string]$journal.request.request.season; Gameweek = [int]$journal.request.request.gameweek
        PullRequest = $pullRequest; Number = ($pullRequest -split '/')[-1]; Preview = $preview
        Stamp = [string](Get-Content -LiteralPath (Join-Path $preview 'leagues.json') -Raw -Encoding UTF8 | ConvertFrom-Json).generated_at_utc
        Commit = [string]$stages['publish'].value.publication_commit; News = $news
        Capture = [string]$stages['capture'].value.snapshot_id; Snapshots = [string]$journal.request.paths.snapshots
        Handoff = if ($retained.Count -gt 0) { $retained[0] } else { [string]$stages['handoff'].value.path }
        Rotation = if ($news) { [string]$stages['rotation'].value.table } else { '' }
    }
}

function Release-Tag([string]$repo, $run) {
    $listed = Invoke-External 'git' @('-C', $repo, 'ls-remote', '--tags', 'origin', ('site-{0}-gw*' -f $run.Season))
    if ($listed.Exit -ne 0) { throw (Say 'git ls-remote exited {0}; the next unused tag is unknown.' $listed.Exit) }
    $tags = @($listed.Lines | ForEach-Object { ($_ -split '\s+')[1] -replace '^refs/tags/', '' } | Where-Object { $_ -notmatch '\^\{\}$' })
    return (Suggested-Tag $run.Kind $run.Season $run.Gameweek $tags)
}

function Ship-Arguments($run, [string]$tag, [string]$summary) {
    # The ship.sh line weekly_run.ps1 prints; a Tuesday run states the week it settles.
    $arguments = @('scripts/release/ship.sh', $run.Number, $tag, ('release/' + ($tag -replace '^site-[0-9]{4}-[0-9]{2}-', '')), $run.Stamp, $summary)
    if ($run.Kind -eq 'tuesday') { $arguments += [string]($run.Gameweek - 1) }
    return $arguments
}

function Bundle-Root([string]$repo) {
    # The root the backend reads and the forecast is built in (docs/backend_runbook.md).
    $selection = Join-Path $repo 'artifacts\backend-artifact-root.json'
    if (-not (Test-Path -LiteralPath $selection)) { return (Join-Path $repo 'artifacts') }
    $root = [string](Get-Content -LiteralPath $selection -Raw -Encoding UTF8 | ConvertFrom-Json).artifact_root
    if ([IO.Path]::IsPathRooted($root)) { return $root }
    return (Join-Path $repo $root)
}

function Wait-Checks([string]$number, [int]$minutes) {
    # gh pr checks exits 8 while a check is pending, and reports none before CI has started.
    for ($minute = 0; $minute -lt $minutes; $minute++) {
        $checks = Invoke-External 'gh' @('pr', 'checks', $number, '--required')
        if ($checks.Exit -ne 8 -and @($checks.Lines -match 'no (required )?checks reported').Count -eq 0) { return $checks.Exit }
        Pause-Release 60
    }
    return 8
}

function Wait-Merged([string]$number, [int]$minutes) {
    $state = ''
    for ($minute = 0; $minute -lt $minutes; $minute++) {
        $state = (Invoke-External 'gh' @('pr', 'view', $number, '--json', 'state', '--jq', '.state')).Lines -join ''
        if ($state -in 'MERGED', 'CLOSED') { return $state }
        Pause-Release 60
    }
    return $state
}

function Release-Run([string]$repo, [string]$runId, [string]$summary, [int]$minutes) {
    # Every step in order; the first that fails stops the chain. Returns the exit code.
    $logs = Join-Path $repo 'data\logs\weekly'
    $log = Join-Path $logs ($runId + '.release.log')
    $script:CommandsLog = Join-Path $logs ($runId + '.release-commands.log')
    if (Test-Path -LiteralPath $log) {
        Release-Line $log 'refused: this run was released before; a release is attempted once, and one that stopped is reconciled by hand'
        return 2
    }
    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    try {
        $run = Release-Inputs $repo $runId
        $tag = Release-Tag $repo $run
    } catch {
        Release-Line $log ('refused: ' + $_.Exception.Message)
        return 2
    }
    Release-Line $log ('run {0}: site pull request {1}, accepted stamp {2}, tag {3}' -f $runId, $run.PullRequest, $run.Stamp, $tag)
    $tree = Invoke-External 'python' @('-m', 'scripts.check_league_tree', $run.Preview)
    if ($tree.Exit -ne 0) { Release-Line $log (Say 'refused: check_league_tree exited {0}; nothing was enqueued' $tree.Exit); return 2 }
    Release-Line $log 'check_league_tree: ALL GOOD'
    $checks = Wait-Checks $run.Number $minutes
    if ($checks -ne 0) { Release-Line $log (Say 'refused: the required checks of #{0} did not pass (gh pr checks exited {1}); nothing was enqueued' $run.Number $checks); return 2 }
    $node = Invoke-External 'gh' @('pr', 'view', $run.Number, '--json', 'id', '--jq', '.id')
    if ($node.Exit -ne 0) { Release-Line $log 'refused: the pull request could not be read; nothing was enqueued'; return 2 }
    $queued = Invoke-External 'gh' @('api', 'graphql', '-f', ('query=' + $EnqueueMutation), '-f', ('id=' + ($node.Lines -join '')), '-f', ('head=' + $run.Commit))
    if ($queued.Exit -ne 0) { Release-Line $log (Say 'stopped: the enqueue exited {0}; read the pull request before anything else' $queued.Exit); return 1 }
    Release-Line $log ('enqueued at ' + $run.Commit)
    $state = Wait-Merged $run.Number $minutes
    if ($state -ne 'MERGED') { Release-Line $log (Say 'stopped: #{0} is {1}, not merged within {2} min; nothing was released' $run.Number $state $minutes); return 1 }
    Release-Line $log 'merged into develop'
    $ship = Invoke-External 'sh' (Ship-Arguments $run $tag $summary)
    if ($ship.Exit -ne 0) { Release-Line $log (Say 'stopped: ship.sh exited {0}; after "release PR #N merged" recover by hand as docs/deployment_runbook.md says, never by running ship.sh again' $ship.Exit); return 1 }
    Release-Line $log ('live: ' + $tag)
    $vm = Invoke-External 'bash' @('scripts/vm_push.sh', $tag)
    if ($vm.Exit -ne 0) { Release-Line $log (Say 'stopped: vm_push.sh exited {0}; the site is live, the VM is not on {1}' $vm.Exit $tag); return 1 }
    Release-Line $log ('vm: ' + $tag)
    if (-not $run.News) { Release-Line $log 'bundle: none, the run read no club-news capture'; return 0 }
    # The seal records its attempt before it reads the forecast, and a refused attempt turns the
    # manager's word off for the capture, so it is not attempted without the forecast.
    $root = Bundle-Root $repo
    $forecast = Join-Path $root ('football\' + $run.Capture)
    if (-not ((Test-Path -LiteralPath ($forecast + '.json')) -and (Test-Path -LiteralPath ($forecast + '.components.json')))) {
        Release-Line $log ('stopped: no football forecast for {0} under {1}; the seal was not attempted' -f $run.Capture, $root)
        return 1
    }
    $bundle = Invoke-External 'python' @('-m', 'scripts.prepare_football_bundle', '--artifact-root', $root,
        '--snapshot-root', $run.Snapshots, '--snapshot-id', $run.Capture, '--handoff', $run.Handoff,
        '--site-data-root', $run.Preview, '--news-capture-id', $run.News, '--rotation-table', $run.Rotation)
    if ($bundle.Exit -ne 0) { Release-Line $log (Say 'stopped: prepare_football_bundle exited {0}; retry only with the identical inputs' $bundle.Exit); return 1 }
    Release-Line $log ('bundle: sealed for {0} with club news {1}' -f $run.Capture, $run.News)
    return 0
}

if ($MyInvocation.InvocationName -eq '.') { return }

$env:PYTHONPATH = (Join-Path $RepoRoot 'src') + ';' + $RepoRoot
Set-Location -LiteralPath $RepoRoot
$code = Release-Run $RepoRoot $RunId $Summary $WaitMinutes
Get-Content -LiteralPath (Join-Path $RepoRoot ('data\logs\weekly\' + $RunId + '.release.log')) -Encoding UTF8
exit $code
