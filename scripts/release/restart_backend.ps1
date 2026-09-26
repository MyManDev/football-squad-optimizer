<#
.SYNOPSIS
Verify the published site, fast-forward develop, and restart the recorded backend.
.DESCRIPTION
The owner runs this after ship.sh. -DryRun performs read-only checks and prints the
planned pull, stop and start. -AcceptedGeneratedAt is the exact generated_at_utc
stamp from the accepted publication; the legacy -LiveGeneratedAfter alias has the
same meaning. It fetches origin/develop and the release tag, but changes no
working-tree file or process. No tunnel is touched.
The backend runs the code of the live site release: the newest site-* tag whose
production deploy succeeded (read from the deploy workflow's runs with GitHub CLI), or
-ReleaseTag. The fetched develop and the pulled HEAD must equal that tag's commit in
src, scripts and docs/contracts; otherwise it refuses unless -Force, which also permits
open work.
Windows PowerShell 5.1, ASCII only. The launcher must include Stop -WhatIf support.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][Alias("LiveGeneratedAfter")][string]$AcceptedGeneratedAt,
    # The gameweek this release settles, asserted by the verifier rather than printed. Omit it
    # for a decision release, which settles nothing.
    [int]$SettledGameweek,
    # Defaults to the checkout this script lives in, resolved below: Windows PowerShell 5.1
    # leaves $PSScriptRoot empty while it binds these defaults under -File.
    [string]$RepoRoot = "",
    [string]$StoreRoot = "",
    [string]$SiteDataRoot = "",
    [string]$Python = "",
    [int]$ReadyTimeoutSeconds = 120,
    # The site release whose code the backend must run. Omitted, it is the newest site-* tag
    # whose production deploy succeeded.
    [string]$ReleaseTag = "",
    # GitHub CLI for that lookup; defaults to gh on PATH, then the usual Windows installation.
    [string]$GitHubCli = "",
    [switch]$Force,
    [switch]$DryRun
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
if (-not $RepoRoot) {
    $scriptDirectory = $PSScriptRoot
    if (-not $scriptDirectory) { $scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path }
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptDirectory)
}
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not $StoreRoot) { $StoreRoot = Join-Path $RepoRoot "data\runtime\backend" }
if (-not $SiteDataRoot) { $SiteDataRoot = Join-Path $RepoRoot "web\public\data" }
if (-not $Python) { $Python = Join-Path $RepoRoot ".venv\Scripts\python.exe" }
$SourceRoot = Join-Path $RepoRoot "src"
$launcher = Join-Path $RepoRoot "scripts\run_backend_local.ps1"
$registry = Join-Path $StoreRoot "run\backend.pids.json"
$publicRoot = "https://squadopt.mymandev.com"
$headers = @{"User-Agent" = "squadopt-backend-restart/1"}
$repository = "MyManDev/football-squad-optimizer"
# The tags deploy-pages.yml accepts for production.
$releasePattern = '^site-[0-9]{4}-[0-9]{2}-gw[0-9]{2}-(decision|settled|fix[0-9]+)$'
# The code the backend imports, the launcher that starts it, and the contracts it answers in.
$releasedPaths = @('src', 'scripts', 'docs/contracts')

function Read-Json([string]$path) {
    # The launcher registry is not a queue/cache document and is not written by workers.
    return (Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json)
}
function Get-Json([string]$url) {
    return ((Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 15 -Headers $headers).Content | ConvertFrom-Json)
}
function Git-Read([string[]]$arguments) {
    $output = & git --no-optional-locks -C $RepoRoot @arguments
    if ($LASTEXITCODE -ne 0) { throw "Git failed: $arguments" }
    return ($output -join "`n").Trim()
}
function Assert-Checkout {
    if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot '.git') -PathType Container)) {
        throw "Use the main checkout, not a linked worktree."
    }
    if ((Git-Read -arguments @('branch', '--show-current')) -ne 'develop') { throw "Checkout must be on develop." }
    if (Git-Read -arguments @('status', '--porcelain')) { throw "Checkout must be clean, including untracked files." }
}
function Published-Capture([switch]$Public, [string]$Ref = "") {
    if ($Public) { $members = Get-Json "$publicRoot/data/league/members.json" }
    elseif ($Ref) { $members = (Git-Read -arguments @('show', "${Ref}:web/public/data/league/members.json")) | ConvertFrom-Json }
    else { $members = Read-Json (Join-Path $SiteDataRoot 'league\members.json') }
    $identities = @()
    foreach ($member in $members.payload.members) {
        if ($member.member_kind -ne 'human') { continue }
        $entry = [string]$member.entry_id
        if ($entry -notmatch '^[1-9][0-9]*$') { throw "Invalid human entry id." }
        if ($Public) { $document = Get-Json "$publicRoot/data/league/entries/$entry.json" }
        elseif ($Ref) { $document = (Git-Read -arguments @('show', "${Ref}:web/public/data/league/entries/$entry.json")) | ConvertFrom-Json }
        else { $document = Read-Json (Join-Path $SiteDataRoot "league\entries\$entry.json") }
        $capture = [string]$document.payload.source_snapshot_id
        if ($capture -notmatch '^fpl-live-[A-Za-z0-9_-]+$') { throw "Entry $entry has no usable capture identity." }
        $identities += $capture
    }
    $agreed = @($identities | Select-Object -Unique)
    if ($agreed.Count -ne 1) { throw "Published human entries are empty or disagree on capture." }
    return $agreed[0]
}
function Queue-Depth([int]$port) {
    $body = (Invoke-WebRequest -Uri "http://127.0.0.1:$port/metrics" -UseBasicParsing -TimeoutSec 15).Content
    $rows = @($body -split "`n" | Where-Object { $_ -match '^advice_queue_depth\s+[0-9]+\s*$' })
    if ($rows.Count -ne 1) { throw "Queue depth is unavailable; refusing to stop." }
    return [long](($rows[0] -split '\s+')[1])
}
function Resolve-GitHubCli {
    $candidate = $GitHubCli
    if (-not $candidate) {
        $onPath = @(Get-Command gh -CommandType Application -ErrorAction SilentlyContinue)
        if ($onPath.Count -gt 0) { $candidate = $onPath[0].Path }
        else { $candidate = 'C:\Program Files\GitHub CLI\gh.exe' }
    }
    if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) {
        throw "GitHub CLI not found at $candidate; pass -GitHubCli, or name the release with -ReleaseTag."
    }
    return $candidate
}
function GitHub-Json([string[]]$arguments) {
    $output = & $script:gh @arguments
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "GitHub CLI failed: $arguments. Name the release with -ReleaseTag instead."
    }
    return (($output -join "`n") | ConvertFrom-Json)
}
function Latest-Release {
    # Production deploys share one FIFO queue, so the newest dispatch whose production job
    # succeeded is the release the site serves. That job is named "production <tag>".
    $runs = @(GitHub-Json -arguments @('run', 'list', '-R', $repository, '--workflow', 'deploy-pages.yml',
        '--event', 'workflow_dispatch', '--status', 'success', '--limit', '30', '--json', 'databaseId'))
    foreach ($run in @($runs | Sort-Object -Property databaseId -Descending)) {
        $id = [string]$run.databaseId
        $jobs = (GitHub-Json -arguments @('run', 'view', $id, '-R', $repository, '--json', 'jobs')).jobs
        foreach ($job in @($jobs)) {
            $name = [string]$job.name
            $isProduction = $name.StartsWith('production ', [StringComparison]::Ordinal)
            if ($job.conclusion -ne 'success' -or -not $isProduction) { continue }
            $tag = $name.Substring('production '.Length)
            if ($tag -cnotmatch $releasePattern) { throw "Deploy run $id names '$tag', which is not a site release tag." }
            return @($tag, $id)
        }
    }
    throw "No successful production deploy among the last 30 deploy runs; name the release with -ReleaseTag."
}
function Release-Commit([string]$tag) {
    if ($tag -cnotmatch $releasePattern) { throw "Release tag '$tag' is not a site release tag." }
    # A local tag that differs from origin's is refused by the fetch, not replaced.
    $null = & git -C $RepoRoot fetch --no-tags origin "refs/tags/${tag}:refs/tags/${tag}"
    if ($LASTEXITCODE -ne 0) { throw "Could not fetch release tag $tag from origin; backend left running." }
    if ((Git-Read -arguments @('cat-file', '-t', "refs/tags/$tag")) -ne 'tag') {
        throw "Release tag $tag is not annotated; backend left running."
    }
    return (Git-Read -arguments @('rev-parse', "refs/tags/${tag}^{commit}"))
}
function Assert-Released([string]$revision, [string]$label) {
    $listed = Git-Read -arguments (@('diff', '--name-only', '--no-renames', $releaseCommit, $revision, '--') + $releasedPaths)
    $changed = @($listed -split "`n" | Where-Object { $_ })
    if ($changed.Count -eq 0) {
        Write-Output "$label matches release $ReleaseTag in src, scripts and docs/contracts."
        return
    }
    Write-Output "$label differs from release $ReleaseTag in $($changed.Count) file(s) under src, scripts or docs/contracts:"
    foreach ($path in @($changed | Select-Object -First 20)) { Write-Output "  $path" }
    if ($Force) {
        Write-Output "FORCED: the backend will run code that no site release carries."
        return
    }
    throw "$label is not the code of release $ReleaseTag; backend left running. Wait for the next site release, or pass -Force to run it anyway."
}

$lastReadyBody = "not queried"
$backendUp = $false
function Read-Readiness {
    $script:backendUp = $false
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$port/ready" -UseBasicParsing -TimeoutSec 15
        $script:backendUp = $true
        $script:lastReadyBody = $response.Content
        $report = $response.Content | ConvertFrom-Json
        return ($response.StatusCode -eq 200 -and $report.ready -eq $true -and
            $report.checks.league_tree_matches_capture -eq $true)
    } catch {
        $failed = $null
        if ($_.Exception.PSObject.Properties['Response']) { $failed = $_.Exception.Response }
        if ($null -ne $failed) {
            $script:backendUp = $true
            # Windows PowerShell may already have consumed the response stream.
            if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
                $script:lastReadyBody = $_.ErrorDetails.Message
            } else {
                $reader = New-Object IO.StreamReader($failed.GetResponseStream())
                try { $script:lastReadyBody = $reader.ReadToEnd() } finally { $reader.Dispose() }
            }
        } else { $script:lastReadyBody = "No readable readiness response: $_" }
        return $false
    }
}

Assert-Checkout
$parsed = [datetimeoffset]::MinValue
if ($AcceptedGeneratedAt -notmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$' -or
    -not [datetimeoffset]::TryParse($AcceptedGeneratedAt, [ref]$parsed)) {
    throw "AcceptedGeneratedAt must be an ISO UTC timestamp ending in Z."
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "Python not found: $Python" }

# The release comes first: it needs no running backend, and a develop that has moved past
# the release refuses before anything reads the backend or the public site.
& git -C $RepoRoot fetch origin develop
if ($LASTEXITCODE -ne 0) { throw "Fetch failed; backend left running." }
$releaseSource = "named by -ReleaseTag"
if (-not $ReleaseTag) {
    $gh = Resolve-GitHubCli
    $latest = Latest-Release
    $ReleaseTag = $latest[0]
    $releaseSource = "the newest successful production deploy, run $($latest[1])"
}
$releaseCommit = Release-Commit $ReleaseTag
if ($DryRun) {
    Write-Output "DryRun fetched origin/develop and tag ${ReleaseTag}: only Git refs updated; working tree and backend files unchanged."
}
Write-Output "Release $ReleaseTag at $releaseCommit, $releaseSource."
Assert-Released -revision 'origin/develop' -label 'Fetched origin/develop'

$state = Read-Json $registry
$port = [int]$state.port
if ($port -lt 1 -or $port -gt 65535) { throw "Invalid recorded port." }
if ([IO.Path]::GetFullPath($state.source_root) -ne [IO.Path]::GetFullPath($SourceRoot)) {
    throw "Recorded source root differs from this checkout's src."
}
if ([IO.Path]::GetFullPath($state.store_root) -ne [IO.Path]::GetFullPath($StoreRoot)) {
    throw "Recorded store root differs from the selected store."
}
$workers = @($state.processes | Where-Object { $_.role -match '^worker-[0-9]+$' }).Count
if ($workers -lt 1) { throw "No workers recorded; refusing to guess their count." }
$depth = Queue-Depth $port
Write-Output "Checkout=$RepoRoot source=$SourceRoot store=$StoreRoot site=$SiteDataRoot"
Write-Output "Recorded port=$port workers=$workers queue_depth=$depth force=$Force"
Write-Output "Current launcher-recorded commit=$($state.repository_commit)"
if ($depth -gt 0 -and -not $Force) { throw "Jobs are queued or running; drain them or explicitly use -Force." }

$verifier = Join-Path $RepoRoot 'scripts\release\verify_live.py'
$verifierArgs = @($verifier, $AcceptedGeneratedAt)
if ($PSBoundParameters.ContainsKey('SettledGameweek')) {
    $verifierArgs += @('--settled', "$SettledGameweek")
}
Write-Output "Verify public release: $Python $($verifierArgs -join ' ')"
& $Python @verifierArgs
if ($LASTEXITCODE -ne 0) { throw "Public release verification failed; backend left running." }
$publicCapture = Published-Capture -Public
try { $localCapture = Published-Capture } catch { $localCapture = "unavailable: $_" }
Write-Output "Public capture=$publicCapture pre-pull local capture=$localCapture (informational)"

$remoteCapture = Published-Capture -Ref 'origin/develop'
Write-Output "Fetched origin/develop capture=$remoteCapture"
if ($remoteCapture -ne $publicCapture) { throw "Public/origin capture mismatch; backend left running." }

$parameters = (Get-Command $launcher).Parameters
if (-not $parameters.ContainsKey('WhatIf')) { throw "Launcher must include D1 Stop -WhatIf before restart." }
$startArguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$launcher`"",
    '-RepoRoot', "`"$RepoRoot`"", '-StoreRoot', "`"$StoreRoot`"", '-SiteDataRoot', "`"$SiteDataRoot`"",
    '-Python', "`"$Python`"", '-Port', $port, '-Workers', $workers)
$startLine = 'powershell.exe ' + ($startArguments -join ' ')
$logs = [IO.Path]::GetFullPath((Join-Path $StoreRoot 'logs'))

Write-Output "Pull: git -C $RepoRoot pull --ff-only"
Write-Output "Then require the pulled HEAD to match release $ReleaseTag in src, scripts and docs/contracts, unless -Force."
Write-Output "Stop: $launcher -RepoRoot $RepoRoot -StoreRoot $StoreRoot -Stop"
Write-Output "Start: $startLine"
Write-Output "Then require /ready and league_tree_matches_capture; compare launcher-recorded commit with pulled HEAD."
if ($DryRun) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $launcher -RepoRoot $RepoRoot -StoreRoot $StoreRoot -Stop -WhatIf
    if ($LASTEXITCODE -ne 0) { throw "Stop preview failed; backend left running." }
    Write-Output "DryRun: no pull, stop, start or working-tree/backend files changed."
    exit 0
}

& git -C $RepoRoot pull --ff-only
if ($LASTEXITCODE -ne 0) { throw "Fast-forward pull failed; backend left running." }
Assert-Checkout
$commit = Git-Read -arguments @('rev-parse', 'HEAD')
# The pull fetches again, so it can bring a commit newer than the one checked above.
Assert-Released -revision $commit -label 'Pulled HEAD'
# Pull may replace published data; check it again before stopping anything.
$pulledCapture = Published-Capture
Write-Output "Public capture=$publicCapture pulled local capture=$pulledCapture"
if ($pulledCapture -ne $publicCapture) { throw "Pulled capture differs from live publication; backend left running." }
if ((Queue-Depth $port) -gt 0 -and -not $Force) { throw "New work arrived; backend left running." }
$previousPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $SourceRoot
    & $Python -c "import squadopt.api.runtime, squadopt.platform.advice_worker"
    if ($LASTEXITCODE -ne 0) { throw "Pulled code import failed; backend left running." }
} finally { $env:PYTHONPATH = $previousPath }

$stopFailed = $true
$revisionMismatch = ""
try {
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $launcher -RepoRoot $RepoRoot -StoreRoot $StoreRoot -Stop
if ($LASTEXITCODE -ne 0) { throw "Stop failed; not starting another backend." }
$stopFailed = $false
# Let the launcher independently resolve its code identity, ignoring a shell override.
$previousCommit = $env:SQUADOPT_REPOSITORY_COMMIT
try {
    $env:SQUADOPT_REPOSITORY_COMMIT = $null
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssfffZ')
    $start = Start-Process powershell.exe -WindowStyle Hidden -PassThru -ArgumentList $startArguments `
        -RedirectStandardOutput (Join-Path $logs "restart-$stamp.out.log") `
        -RedirectStandardError (Join-Path $logs "restart-$stamp.err.log")
    # Start-Process -Wait waits for descendants too; the backend is meant to stay alive.
    $null = $start.Handle
    if (-not $start.WaitForExit(180000)) { throw "Launcher may still be starting; inspect restart-$stamp logs before retrying." }
    if ($start.ExitCode -ne 0) { throw "Backend start failed; see restart-$stamp logs." }
} finally { $env:SQUADOPT_REPOSITORY_COMMIT = $previousCommit }

$deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
$ready = $false
do {
    $ready = Read-Readiness
    if ($ready) { break }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)
if (-not $ready) { throw "Backend did not become ready with a matching published week." }
$started = Read-Json $registry
Write-Output "Launcher-recorded commit=$($started.repository_commit) expected=$commit"
if ($started.repository_commit -ne $commit) {
    $revisionMismatch = "recorded=$($started.repository_commit) expected=$commit"
    throw "Launcher-recorded commit differs from pulled HEAD."
}
Write-Output "Backend ready on port $port with $workers workers; tunnel untouched."
} catch {
    $failure = $_
    try { $null = Read-Readiness } catch { }
    if ($backendUp -and $revisionMismatch) { Write-Output "BACKEND UP, WRONG REVISION: $revisionMismatch" }
    elseif ($backendUp) { Write-Output "BACKEND UP, NOT READY" }
    else { Write-Output "BACKEND DOWN" }
    if ($stopFailed) {
        Write-Output "Recovery stop: powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$launcher`" -RepoRoot `"$RepoRoot`" -StoreRoot `"$StoreRoot`" -Stop"
    }
    Write-Output ('Recovery start (after inspecting any remaining processes): $env:SQUADOPT_REPOSITORY_COMMIT=$null; ' + $startLine)
    Write-Output "Logs: $logs"
    Write-Output "Last /ready body: $lastReadyBody"
    throw $failure
}
