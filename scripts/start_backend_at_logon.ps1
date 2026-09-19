<#
.SYNOPSIS
Start the advice backend and its Cloudflare Tunnel connector for the logged-on user.

.DESCRIPTION
The piece docs/backend_free_hosting.md left to the owner: start the backend at logon after
logoff or reboot. This script starts what is not running and leaves alone what is.
It does not run on resume from sleep; the PC must stay awake to serve requests.
With -Watch, start missing components on the first pass, then check every 60 seconds
and start a missing component after three consecutive failures.
-DryRun checks once, prints status and planned starts, and changes nothing.

  powershell -ExecutionPolicy Bypass -File scripts\start_backend_at_logon.ps1
  powershell -ExecutionPolicy Bypass -File scripts\start_backend_at_logon.ps1 -Watch
  powershell -ExecutionPolicy Bypass -File scripts\start_backend_at_logon.ps1 -DryRun
  powershell -ExecutionPolicy Bypass -File scripts\start_backend_at_logon.ps1 -Register
  powershell -ExecutionPolicy Bypass -File scripts\start_backend_at_logon.ps1 -Unregister

-Register writes one shortcut into the user's own Startup folder. That needs no elevation,
touches no service and no registry key, and -Unregister removes exactly that shortcut. The
owner runs -Register; nothing in the repository runs it for them.

It does not replace the Windows service of the tunnel's documentation. A service keeps the
tunnel up with nobody logged on, and the backend would still be down then, so a service
buys nothing until the backend itself can run without a session.

Windows PowerShell 5.1 compatible on purpose (no &&, no ternary, ASCII only).
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$Workers = 6,
    [int]$Port = 8000,
    [string]$TunnelName = "squadopt-api",
    [string]$Cloudflared = "",
    [ValidatePattern('^[A-Za-z0-9_-]+$')]
    [string]$ConnectorLabel = "squadopt-logon",
    [switch]$Watch,
    [switch]$DryRun,
    [switch]$Register,
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$ShortcutName = "SquadOpt advice backend.lnk"
if ($DryRun -and ($Register -or $Unregister)) {
    throw "-DryRun cannot be combined with -Register or -Unregister."
}

function Get-StartupShortcut {
    Join-Path ([Environment]::GetFolderPath("Startup")) $ShortcutName
}

function Find-Cloudflared {
    if ($Cloudflared -ne "") {
        if (Test-Path -LiteralPath $Cloudflared -PathType Leaf) { return $Cloudflared }
        return $null
    }
    $command = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($root in @(${env:ProgramFiles(x86)}, $env:ProgramFiles)) {
        if (-not $root) { continue }
        $candidate = Join-Path $root "cloudflared\cloudflared.exe"
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

if ($Unregister) {
    $shortcut = Get-StartupShortcut
    if (Test-Path $shortcut) {
        Remove-Item -Confirm:$false $shortcut
        Write-Output "Removed $shortcut"
    } else {
        Write-Output "Nothing registered at $shortcut"
    }
    exit 0
}

if ($Register) {
    $RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path.TrimEnd('\')
    $shortcut = Get-StartupShortcut
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($shortcut)
    $link.TargetPath = (Get-Command powershell.exe).Source
    $link.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`" -RepoRoot `"$RepoRoot`" -Workers $Workers -Port $Port -TunnelName `"$TunnelName`""
    $link.Arguments += " -Watch -ConnectorLabel `"$ConnectorLabel`""
    if ($Cloudflared -ne "") {
        $Cloudflared = (Resolve-Path -LiteralPath $Cloudflared).Path
        $link.Arguments += " -Cloudflared `"$Cloudflared`""
    }
    $link.WorkingDirectory = $RepoRoot
    $link.WindowStyle = 7
    $link.Description = "Starts the SquadOpt advice backend and its tunnel connector at logon"
    $link.Save()
    Write-Output "Registered $shortcut"
    Write-Output "It runs at the next logon. Run this script with -Watch to start and watch now."
    exit 0
}

$launcher = Join-Path $RepoRoot "scripts\run_backend_local.ps1"
if (-not (Test-Path $launcher)) { throw "No launcher at $launcher; pass -RepoRoot." }
$logRoot = Join-Path $RepoRoot "data\runtime\backend\logs"
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$own = Join-Path $logRoot "startup-$stamp.log"

function Write-Line([string]$text) {
    $line = "{0} {1}" -f (Get-Date).ToUniversalTime().ToString("s"), $text
    if (-not $DryRun) {
        try {
            New-Item -ItemType Directory -Force $logRoot | Out-Null
            $line | Out-File -FilePath $own -Append -Encoding utf8
        } catch { } # A locked or unavailable log directory must not end the watcher.
    }
    Write-Output $line
}

$conditions = @{}
function Write-Condition([string]$component, [string]$text) {
    if ($conditions[$component] -ne $text) {
        $conditions[$component] = $text
        Write-Line $text
    }
}

function Get-BackendBlocker {
    # Launcher-owned registry only. Never inspect queue/cache documents.
    $registry = Join-Path $RepoRoot "data\runtime\backend\run\backend.pids.json"
    try {
        if (-not (Test-Path -LiteralPath $registry)) { return $null }
        $state = Get-Content -LiteralPath $registry -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($null -eq $state.processes) { throw "invalid process registry" }
        foreach ($entry in $state.processes) {
            try { $live = Get-Process -Id ([int]$entry.pid) -ErrorAction Stop } catch {
                if ($_.FullyQualifiedErrorId -like 'NoProcessFoundForGivenId*') { continue }
                throw
            }
            if ($live.StartTime.ToUniversalTime().Ticks.ToString() -eq [string]$entry.start_ticks_utc) {
                return "backend unhealthy but recorded processes are alive; operator intervention needed"
            }
        }
    } catch { return "backend process identity unknown; leaving processes alone; operator intervention needed" }
    return $null
}

function Start-MissingBackend {
    $blocker = Get-BackendBlocker
    if ($blocker) { Write-Condition "backend" $blocker; return }
    if ($DryRun) {
        Write-Line "would ask the launcher to start the backend on 127.0.0.1:$Port; it refuses while recorded processes are alive"
        return
    }
    # Redirected to files: the launcher's children inherit its handles, and a pipe would
    # keep this script waiting for as long as the backend lives.
    $attempt = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ")
    try {
        New-Item -ItemType Directory -Force $logRoot | Out-Null
        Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -WorkingDirectory $RepoRoot `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$launcher`"", "-Workers", $Workers, "-Port", $Port, "-RepoRoot", "`"$RepoRoot`"") `
            -RedirectStandardOutput (Join-Path $logRoot "launcher-$attempt.out.log") `
            -RedirectStandardError (Join-Path $logRoot "launcher-$attempt.err.log") | Out-Null
        Write-Line "asked the launcher to start the backend with $Workers workers on port $Port"
    } catch { Write-Line "backend launch failed: $_" }
}

# The tunnel. Cloudflare accepts several connectors for one tunnel, so starting this one
# never cuts a connector somebody started by hand; the label tells them apart.
function Start-MissingConnector {
    $exe = Find-Cloudflared
    if (-not $exe) {
        Write-Condition "connector" "cloudflared not found; cannot start the tunnel connector"
        return
    }
    if ($DryRun) {
        Write-Line "would start tunnel $TunnelName with label $ConnectorLabel"
        return
    }
    $attempt = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ")
    try {
        New-Item -ItemType Directory -Force $logRoot | Out-Null
        Start-Process -FilePath $exe -WindowStyle Hidden `
            -ArgumentList @("tunnel", "--no-autoupdate", "--label", $ConnectorLabel, "run", "`"$TunnelName`"") `
            -RedirectStandardOutput (Join-Path $logRoot "cloudflared-$attempt.out.log") `
            -RedirectStandardError (Join-Path $logRoot "cloudflared-$attempt.err.log") | Out-Null
        Write-Line "started tunnel connector for $TunnelName with label $ConnectorLabel"
    } catch { Write-Line "tunnel launch failed: $_" }
}

$backendFailures = 0
$connectorFailures = 0
$threshold = 1
$labelPattern = '(?:^|\s)--label(?:=|\s+)"?' + [regex]::Escape($ConnectorLabel) + '"?(?=\s|$)'
$tunnelPattern = '(?:^|\s)run\s+"?' + [regex]::Escape($TunnelName) + '"?(?=\s|$)'
$mutex = $null
$ownsMutex = $false
try {
    if (-not $DryRun) {
        try {
            $mutex = New-Object System.Threading.Mutex($false, "Global\SquadOpt-backend-$Port-$ConnectorLabel")
            try { $ownsMutex = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] {
                $ownsMutex = $true
            }
        } catch [System.UnauthorizedAccessException] { $ownsMutex = $false }
        if (-not $ownsMutex) {
            Write-Line "watcher already active for port $Port and label $ConnectorLabel"
            exit 0
        }
    }
    do {
    try {
    $answers = $false
    try {
        $health = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://127.0.0.1:$Port/health"
        $answers = ($health.StatusCode -eq 200)
    } catch { }
    if ($answers) {
        $backendFailures = 0
        Write-Condition "backend" "backend healthy on 127.0.0.1:$Port"
    } else { $backendFailures++ }
    if ($backendFailures -ge $threshold) {
        Start-MissingBackend
        $backendFailures = 0
    }

    try {
        $connectors = @(Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction Stop)
        if (@($connectors | Where-Object { -not $_.CommandLine }).Count -gt 0) {
            throw "connector command line unavailable"
        }
        $mine = @($connectors |
            Where-Object { $_.CommandLine -match $labelPattern -and $_.CommandLine -match $tunnelPattern })
        if ($mine.Count -gt 0) {
            $connectorFailures = 0
            Write-Condition "connector" "tunnel connector healthy for $TunnelName with label $ConnectorLabel"
        } else { $connectorFailures++ }
    } catch {
        # Unknown is not missing. A failed process listing must not create duplicates.
        $connectorFailures = 0
        Write-Condition "connector" "connector check failed; leaving processes alone: $_"
    }
    if ($connectorFailures -ge $threshold) {
        Start-MissingConnector
        $connectorFailures = 0
    }
    $conditions.Remove("iteration")
    } catch { Write-Condition "iteration" "watch check failed; will retry: $_" }
    $threshold = 3
    if ($Watch -and -not $DryRun) { Start-Sleep -Seconds 60 }
    } while ($Watch -and -not $DryRun)
} finally {
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    if ($null -ne $mutex) { $mutex.Dispose() }
}
