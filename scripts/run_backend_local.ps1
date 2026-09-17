<#
.SYNOPSIS
Run the advice backend natively on this Windows machine: one api, N workers, one store.

.DESCRIPTION
The zero-cost deployment of docs/backend_free_hosting.md. No Docker and no cloud resource:
the api and the workers are ordinary Python processes from the repository's .venv, sharing
one file store on the local disk, reading the captures, handoffs and published tree the
weekly run already leaves in this checkout. Only the api listens, and only on loopback; a
Cloudflare Tunnel (deploy/cloudflared/config.example.yml) is what makes it reachable.

  powershell -ExecutionPolicy Bypass -File scripts\run_backend_local.ps1 -Workers 4
  powershell -ExecutionPolicy Bypass -File scripts\run_backend_local.ps1 -Status
  powershell -ExecutionPolicy Bypass -File scripts\run_backend_local.ps1 -Stop

It refuses to start while a previous start is still alive, records every process it
started in <store>\run\backend.pids.json, and -Stop stops exactly those: a recorded pid is
only touched when the live process has the recorded start time, so a pid Windows has since
handed to something else is left alone.

Windows PowerShell 5.1 compatible on purpose (no &&, no ternary, ASCII only).

.NOTES
Threads. CP-SAT runs one search worker per solve (optimization/optimizer.py,
configure_solver: num_search_workers = 1) and a worker computes one job at a time, so N
workers are N busy cores at most. The BLAS pools numpy and scipy bring are a separate
matter: left alone each process sizes its pool to the machine, so they are pinned to one
thread here and N workers cannot oversubscribe through them either.

Stopping. Windows has no SIGTERM to deliver, so -Stop terminates. A worker stopped in the
middle of a job leaves that job "running"; the next worker to start walks it back to
"queued" once its claim is older than the 300 s lease and computes it again. Nothing is
lost, but the member waits. Stop when the queue is empty (-Status shows it).

Run it from a console. Start-Process lets the children inherit this process's handles, so
a caller that captures the output through a pipe (a CI step, another script's $(...))
gets every line and then waits for as long as the backend lives. A console, a scheduled
task and a redirect to a file are not affected.

The processes belong to the logon session: they end at logoff or reboot, and nothing
restarts them. A scheduled task "at log on" that runs this script is the way to make that
automatic; the stale pid file a reboot leaves behind is recognised and removed.
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [int]$Workers = 2,
    # The checkout whose data is served. Defaults to the one this script lives in.
    [string]$RepoRoot = "",
    # The code that runs. Defaults to <RepoRoot>\src; a worktree passes its own.
    [string]$SourceRoot = "",
    [string]$Python = "",
    # data\runtime\ is git-ignored (.gitignore), so nothing here can be committed.
    [string]$StoreRoot = "",
    [string]$SiteDataRoot = "",
    [string]$SnapshotRoot = "",
    [string]$HandoffRoot = "",
    # Where the weekly run leaves the Top 100 export and the rotation table, and the
    # club-news source it codes from (the committed example fixture until a real host
    # is registered).
    [string]$ArtifactRoot = "",
    [string]$ClubNewsSource = "",
    # SITE_ORIGINS in src\squadopt\platform\backend_runtime.py, canonical first.
    [string]$AllowedOrigins = "https://squadopt.mymandev.com,https://squadopt.pages.dev",
    [int]$RateLimit = 30,
    [int]$RateWindowSeconds = 60,
    # 0 keeps the workers without a listener. Otherwise worker i serves /health and
    # /metrics on 127.0.0.1:<base + i>. Never route a tunnel to these ports.
    [int]$WorkerMetricsBasePort = 0,
    [int]$StartTimeoutSeconds = 60,
    [switch]$Stop,
    [switch]$Status
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not $SourceRoot) { $SourceRoot = Join-Path $RepoRoot "src" }
if (-not $Python) { $Python = Join-Path $RepoRoot ".venv\Scripts\python.exe" }
if (-not $StoreRoot) { $StoreRoot = Join-Path $RepoRoot "data\runtime\backend" }
if (-not $SiteDataRoot) { $SiteDataRoot = Join-Path $RepoRoot "web\public\data" }
if (-not $SnapshotRoot) { $SnapshotRoot = Join-Path $RepoRoot "data\snapshots" }
if (-not $HandoffRoot) { $HandoffRoot = Join-Path $RepoRoot "data\handoffs" }
if (-not $ArtifactRoot) { $ArtifactRoot = Join-Path $RepoRoot "artifacts" }
if (-not $ClubNewsSource) { $ClubNewsSource = Join-Path $RepoRoot "data\sample\club_news_v1.fixture.json" }

$RunDirectory = Join-Path $StoreRoot "run"
$LogDirectory = Join-Path $StoreRoot "logs"
$PidFile = Join-Path $RunDirectory "backend.pids.json"

function Read-PidFile {
    if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
    return (Get-Content -LiteralPath $PidFile -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Get-RecordedProcess($entry) {
    # The recorded process, or $null when that pid is gone or now belongs to another.
    try {
        $live = Get-Process -Id ([int]$entry.pid) -ErrorAction Stop
    } catch {
        return $null
    }
    try {
        $ticks = $live.StartTime.ToUniversalTime().Ticks.ToString()
    } catch {
        return $null
    }
    if ($ticks -ne [string]$entry.start_ticks_utc) { return $null }
    return $live
}

function Get-Descendants([int]$parentId) {
    # .venv\Scripts\python.exe is a launcher: the interpreter doing the work is its child.
    $found = @()
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$parentId")
    foreach ($child in $children) {
        if ($child.Name -eq "conhost.exe") { continue }
        $found += [int]$child.ProcessId
        $found += @(Get-Descendants ([int]$child.ProcessId))
    }
    return $found
}

function Get-Json([string]$url) {
    # @{ status; body } whatever the status code; $null when nothing answered.
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10
        return @{ status = [int]$response.StatusCode; body = $response.Content }
    } catch {
        $failed = $_.Exception.Response
        if ($null -eq $failed) { return $null }
        $reader = New-Object System.IO.StreamReader($failed.GetResponseStream())
        try { $text = $reader.ReadToEnd() } finally { $reader.Dispose() }
        return @{ status = [int]$failed.StatusCode; body = $text }
    }
}

function Stop-Recorded($state) {
    # api first, so nothing new is accepted while the workers go.
    $ordered = @($state.processes | Where-Object { $_.role -eq "api" }) +
        @($state.processes | Where-Object { $_.role -ne "api" })
    $targets = @()
    foreach ($entry in $ordered) {
        $live = Get-RecordedProcess $entry
        if ($null -eq $live) {
            Write-Host ("{0} (pid {1}): not running" -f $entry.role, $entry.pid)
            continue
        }
        # Children are read while the parent is still alive and verified, so a child
        # pid cannot be somebody else's.
        $targets += [int]$entry.pid
        $targets += @(Get-Descendants ([int]$entry.pid))
        Write-Host ("{0} (pid {1}): stopping" -f $entry.role, $entry.pid)
    }
    foreach ($id in $targets) {
        try { Stop-Process -Id $id -Force -ErrorAction Stop } catch { }
    }
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline) {
        $alive = @($targets | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
        if ($alive.Count -eq 0) { break }
        Start-Sleep -Milliseconds 250
    }
    $alive = @($targets | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
    if ($alive.Count -gt 0) {
        Write-Host ("Still alive after 15 s: {0}. The pid file is kept." -f ($alive -join ", "))
        return $false
    }
    Remove-Item -LiteralPath $PidFile -Force
    Write-Host ("Stopped {0} process(es); removed {1}" -f $targets.Count, $PidFile)
    return $true
}

# ---------------------------------------------------------------------------- -Stop
if ($Stop) {
    $state = Read-PidFile
    if ($null -eq $state) {
        Write-Host "Nothing to stop: no pid file at $PidFile"
        exit 0
    }
    if (Stop-Recorded $state) { exit 0 }
    exit 1
}

# -------------------------------------------------------------------------- -Status
if ($Status) {
    $state = Read-PidFile
    if ($null -eq $state) {
        Write-Host "Not running: no pid file at $PidFile"
        exit 1
    }
    $down = 0
    foreach ($entry in $state.processes) {
        $word = "running"
        if ($null -eq (Get-RecordedProcess $entry)) { $word = "NOT RUNNING"; $down += 1 }
        Write-Host ("{0,-10} pid {1,-7} {2}  log {3}" -f $entry.role, $entry.pid, $word, $entry.stdout)
    }
    $ready = Get-Json ("http://127.0.0.1:{0}/ready" -f $state.port)
    if ($null -eq $ready) {
        Write-Host ("/ready: no answer on port {0}" -f $state.port)
        exit 1
    }
    Write-Host ("/ready: HTTP {0} {1}" -f $ready.status, $ready.body)
    $metrics = Get-Json ("http://127.0.0.1:{0}/metrics" -f $state.port)
    if ($null -ne $metrics) {
        $depth = @($metrics.body -split "`n" | Where-Object { $_ -match "^advice_queue_depth" })
        if ($depth.Count -gt 0) { Write-Host $depth[0] }
    }
    if ($down -gt 0 -or $ready.status -ne 200) { exit 1 }
    exit 0
}

# ---------------------------------------------------------------------------- start
if ($Workers -lt 1) { throw "-Workers must be at least 1: an api with no worker queues jobs nobody computes." }
if ($Port -lt 1 -or $Port -gt 65535) { throw "-Port must be between 1 and 65535." }

$state = Read-PidFile
if ($null -ne $state) {
    $stillAlive = @($state.processes | Where-Object { $null -ne (Get-RecordedProcess $_) })
    if ($stillAlive.Count -gt 0) {
        Write-Host ("Refusing to start: {0} recorded process(es) are still running (see -Status). Use -Stop first." -f $stillAlive.Count)
        exit 1
    }
    Write-Host "Removing a stale pid file: none of its processes is alive."
    Remove-Item -LiteralPath $PidFile -Force
}

if (-not (Test-Path -LiteralPath $Python)) { throw "No interpreter at $Python. Create the .venv first (pip install -e "".[api]"")." }
foreach ($required in @($SourceRoot, $SiteDataRoot, $SnapshotRoot, $HandoffRoot)) {
    if (-not (Test-Path -LiteralPath $required -PathType Container)) { throw "Missing directory: $required" }
}

# A port somebody else holds would let uvicorn die after the workers are already up.
$listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
try {
    $listener.Start()
    $listener.Stop()
} catch {
    throw "127.0.0.1:$Port is already in use. Pick another -Port or stop what holds it."
}

# The backend never creates its own store root (docs/backend_runbook.md, "the store
# probe"); creating it is the operator's act, and running this script is that act.
foreach ($directory in @($StoreRoot, $RunDirectory, $LogDirectory)) {
    if (-not (Test-Path -LiteralPath $directory)) { New-Item -ItemType Directory -Force -Path $directory | Out-Null }
}

$commit = $env:SQUADOPT_REPOSITORY_COMMIT
if (-not $commit) {
    # Stamped once so the api and every worker file answers under one identity, even if
    # the checkout moves to another commit while they run.
    $codeRoot = Split-Path -Parent $SourceRoot
    try {
        $commit = (& git -C $codeRoot rev-parse HEAD 2>$null | Select-Object -First 1)
    } catch {
        $commit = ""
    }
    if ($commit) { $commit = $commit.Trim() }
}

$environment = [ordered]@{
    PYTHONPATH                           = $SourceRoot
    PYTHONUNBUFFERED                     = "1"
    PYTHONIOENCODING                     = "utf-8"
    SQUADOPT_BACKEND_STORE_ROOT          = $StoreRoot
    SQUADOPT_BACKEND_SITE_DATA_ROOT      = $SiteDataRoot
    SQUADOPT_BACKEND_SNAPSHOT_ROOT       = $SnapshotRoot
    SQUADOPT_BACKEND_HANDOFF_ROOT        = $HandoffRoot
    SQUADOPT_BACKEND_ALLOWED_ORIGINS     = $AllowedOrigins
    SQUADOPT_BACKEND_RATE_LIMIT          = [string]$RateLimit
    SQUADOPT_BACKEND_RATE_WINDOW_SECONDS = [string]$RateWindowSeconds
    # One thread per process for the numeric libraries; see .NOTES.
    OMP_NUM_THREADS                      = "1"
    OPENBLAS_NUM_THREADS                 = "1"
    MKL_NUM_THREADS                      = "1"
    # The per-capture inputs of the two member switches (#604): the week's Top 100 export
    # and rotation table are found under artifacts\ by name, and the club-news source is
    # the one the weekly run codes from. A week without them answers a switched request
    # with a named refusal; plain requests do not need them.
    SQUADOPT_BACKEND_ARTIFACT_ROOT       = $ArtifactRoot
    SQUADOPT_BACKEND_CLUB_NEWS_SOURCE    = $ClubNewsSource
}
if ($commit) { $environment["SQUADOPT_REPOSITORY_COMMIT"] = $commit }

$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$started = @()

function Start-Recorded([string]$role, [string[]]$arguments) {
    $stdout = Join-Path $LogDirectory ("{0}-{1}.out.log" -f $role, $stamp)
    $stderr = Join-Path $LogDirectory ("{0}-{1}.err.log" -f $role, $stamp)
    $process = Start-Process -FilePath $Python -ArgumentList $arguments -WorkingDirectory $RepoRoot `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
    return [ordered]@{
        role            = $role
        pid             = $process.Id
        start_ticks_utc = $process.StartTime.ToUniversalTime().Ticks.ToString()
        stdout          = $stdout
        stderr          = $stderr
    }
}

function Write-PidFile {
    $document = [ordered]@{
        started_at_utc    = $stamp
        port              = $Port
        store_root        = $StoreRoot
        source_root       = $SourceRoot
        repository_commit = $commit
        processes         = @($started)
    }
    $temporary = "$PidFile.tmp"
    $document | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $PidFile -Force
}

# Start-Process hands the child this process's environment, so the values are set here
# and put back afterwards: the calling shell is left as it was found.
$previous = @{}
foreach ($name in $environment.Keys) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    [Environment]::SetEnvironmentVariable($name, [string]$environment[$name], "Process")
}
try {
    # uvicorn trusts X-Forwarded-For only from these addresses, and takes the client
    # address from it: the rightmost entry that is not itself trusted. cloudflared
    # connects from loopback, and Cloudflare appends the visitor's address last, so the
    # rate limiter's per-address bucket is the visitor and not 127.0.0.1. (127.0.0.1 is
    # also uvicorn's default; it is spelled out because the limiter depends on it.)
    $started += Start-Recorded "api" @(
        "-m", "uvicorn", "--factory", "squadopt.api.runtime:build_app",
        "--host", "127.0.0.1", "--port", [string]$Port,
        "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"
    )
    Write-PidFile
    for ($index = 1; $index -le $Workers; $index += 1) {
        $arguments = @("-m", "squadopt.platform.advice_worker")
        if ($WorkerMetricsBasePort -gt 0) {
            $arguments += @("--metrics-host", "127.0.0.1", "--metrics-port", [string]($WorkerMetricsBasePort + $index))
        }
        $started += Start-Recorded ("worker-{0}" -f $index) $arguments
        Write-PidFile
    }
} finally {
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], "Process")
    }
}

function Stop-AfterFailedStart([string]$reason) {
    Write-Host "Start failed: $reason"
    foreach ($entry in $started) {
        foreach ($log in @($entry.stderr, $entry.stdout)) {
            if ((Test-Path -LiteralPath $log) -and ((Get-Item -LiteralPath $log).Length -gt 0)) {
                Write-Host "---- $log"
                Get-Content -LiteralPath $log -Tail 15 | ForEach-Object { Write-Host $_ }
            }
        }
    }
    Stop-Recorded (Read-PidFile) | Out-Null
    exit 1
}

$deadline = (Get-Date).AddSeconds($StartTimeoutSeconds)
$healthy = $false
while ((Get-Date) -lt $deadline) {
    $dead = @($started | Where-Object { $null -eq (Get-RecordedProcess $_) })
    if ($dead.Count -gt 0) { Stop-AfterFailedStart ("{0} exited during startup" -f $dead[0].role) }
    $health = Get-Json ("http://127.0.0.1:{0}/health" -f $Port)
    if ($null -ne $health -and $health.status -eq 200) { $healthy = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $healthy) { Stop-AfterFailedStart "/health did not answer within $StartTimeoutSeconds s" }

# A worker that cannot reach the store exits 1 within its first seconds; give it the
# chance to, so "started" below means started.
Start-Sleep -Seconds 3
$dead = @($started | Where-Object { $null -eq (Get-RecordedProcess $_) })
if ($dead.Count -gt 0) { Stop-AfterFailedStart ("{0} exited during startup" -f $dead[0].role) }

Write-Host ("api       http://127.0.0.1:{0} (pid {1})" -f $Port, $started[0].pid)
Write-Host ("workers   {0}" -f $Workers)
Write-Host ("code      {0} at {1}" -f $SourceRoot, $commit)
Write-Host ("store     {0}" -f $StoreRoot)
Write-Host ("logs      {0}" -f $LogDirectory)
Write-Host ("pid file  {0}" -f $PidFile)
$ready = Get-Json ("http://127.0.0.1:{0}/ready" -f $Port)
if ($null -ne $ready) { Write-Host ("/ready    HTTP {0} {1}" -f $ready.status, $ready.body) }
if ($null -eq $ready -or $ready.status -ne 200) {
    # Not a failed start. /ready is a statement about published data, and the processes
    # pick up a capture, its handoff or a league tree the moment ops publishes them.
    Write-Host "The backend is up but NOT READY; advice routes answer 503 until the false check above"
    Write-Host "holds. See docs/backend_free_hosting.md, 'What /ready needs on this machine'."
}
exit 0
