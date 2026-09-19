<#
.SYNOPSIS
Start the advice backend and its Cloudflare Tunnel connector for the logged-on user.

.DESCRIPTION
The piece docs/backend_free_hosting.md left to the owner: start the backend at logon after
logoff or reboot. This script starts what is not running and leaves alone what is.
It does not run on resume from sleep; the PC must stay awake to serve requests.
With -Watch, check every 60 seconds and start a missing component after three failures.
-DryRun checks once, prints what would start after that threshold, and changes nothing.

  powershell -ExecutionPolicy Bypass -File scripts\start_backend_at_logon.ps1
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
    Write-Output "It runs at the next logon. Run this script without -Register to start now."
    exit 0
}

$launcher = Join-Path $RepoRoot "scripts\run_backend_local.ps1"
if (-not (Test-Path $launcher)) { throw "No launcher at $launcher; pass -RepoRoot." }
$logRoot = Join-Path $RepoRoot "data\runtime\backend\logs"
if (-not $DryRun) { New-Item -ItemType Directory -Force $logRoot | Out-Null }
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$own = Join-Path $logRoot "startup-$stamp.log"

function Write-Line([string]$text) {
    $line = "{0} {1}" -f (Get-Date).ToUniversalTime().ToString("s"), $text
    if (-not $DryRun) { $line | Out-File -FilePath $own -Append -Encoding utf8 }
    Write-Output $line
}

function Start-MissingBackend {
    if ($DryRun) {
        Write-Line "would ask the launcher to start the backend on 127.0.0.1:$Port; it refuses while recorded processes are alive"
        return
    }
    # Redirected to files: the launcher's children inherit its handles, and a pipe would
    # keep this script waiting for as long as the backend lives.
    $attempt = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ")
    try {
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
        Write-Line "cloudflared not found; cannot start the tunnel connector"
        return
    }
    if ($DryRun) {
        Write-Line "would start tunnel $TunnelName with label $ConnectorLabel"
        return
    }
    $attempt = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ")
    try {
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
if ($Watch -and -not $DryRun) { $threshold = 3 }
$labelPattern = '(?:^|\s)--label(?:=|\s+)"?' + [regex]::Escape($ConnectorLabel) + '"?(?=\s|$)'
$tunnelPattern = '(?:^|\s)run\s+"?' + [regex]::Escape($TunnelName) + '"?(?=\s|$)'
do {
    $answers = $false
    try {
        $health = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://127.0.0.1:$Port/health"
        $answers = ($health.StatusCode -eq 200)
    } catch { }
    if ($answers) { $backendFailures = 0 } else { $backendFailures++ }
    if ($backendFailures -ge $threshold) {
        Start-MissingBackend
        $backendFailures = 0
    }

    try {
        $mine = @(Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction Stop |
            Where-Object { $_.CommandLine -match $labelPattern -and $_.CommandLine -match $tunnelPattern })
        if ($mine.Count -gt 0) { $connectorFailures = 0 } else { $connectorFailures++ }
    } catch {
        # Unknown is not missing. A failed process listing must not create duplicates.
        $connectorFailures = 0
        Write-Line "connector check failed; leaving processes alone: $_"
    }
    if ($connectorFailures -ge $threshold) {
        Start-MissingConnector
        $connectorFailures = 0
    }
    if ($Watch -and -not $DryRun) { Start-Sleep -Seconds 60 }
} while ($Watch -and -not $DryRun)
