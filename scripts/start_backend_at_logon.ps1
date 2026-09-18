<#
.SYNOPSIS
Start the advice backend and its Cloudflare Tunnel connector for the logged-on user.

.DESCRIPTION
The piece docs/backend_free_hosting.md left to the owner: the backend's processes end at
logoff, sleep or reboot and nothing restarts them. This script starts what is not running
and leaves alone what is, so it can be run at every logon and by hand.

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
    [switch]$Register,
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$ShortcutName = "SquadOpt advice backend.lnk"
$ConnectorLabel = "squadopt-logon"

function Get-StartupShortcut {
    Join-Path ([Environment]::GetFolderPath("Startup")) $ShortcutName
}

function Find-Cloudflared {
    if ($Cloudflared -ne "") { return $Cloudflared }
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
    $shortcut = Get-StartupShortcut
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($shortcut)
    $link.TargetPath = (Get-Command powershell.exe).Source
    $link.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`" -RepoRoot `"$RepoRoot`" -Workers $Workers -Port $Port -TunnelName $TunnelName"
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
New-Item -ItemType Directory -Force $logRoot | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$own = Join-Path $logRoot "startup-$stamp.log"

function Write-Line([string]$text) {
    $line = "{0} {1}" -f (Get-Date).ToUniversalTime().ToString("s"), $text
    $line | Out-File -FilePath $own -Append -Encoding utf8
    Write-Output $line
}

# The backend. The launcher also refuses by itself while a recorded process is alive.
$answers = $false
try {
    $health = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://127.0.0.1:$Port/health"
    $answers = ($health.StatusCode -eq 200)
} catch {
    $answers = $false
}
if ($answers) {
    Write-Line "backend already answers on 127.0.0.1:$Port"
} else {
    Write-Line "starting the backend with $Workers workers"
    # Redirected to files: the launcher's children inherit its handles, and a pipe would
    # keep this script waiting for as long as the backend lives.
    Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -WorkingDirectory $RepoRoot `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcher, "-Workers", $Workers, "-Port", $Port) `
        -RedirectStandardOutput (Join-Path $logRoot "launcher-$stamp.out.log") `
        -RedirectStandardError (Join-Path $logRoot "launcher-$stamp.err.log") | Out-Null
}

# The tunnel. Cloudflare accepts several connectors for one tunnel, so starting this one
# never cuts a connector somebody started by hand; the label tells them apart.
$exe = Find-Cloudflared
if (-not $exe) {
    Write-Line "cloudflared not found; the backend is reachable on loopback only"
    exit 0
}
$mine = Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" |
    Where-Object { $_.CommandLine -like "*$ConnectorLabel*" -and $_.CommandLine -like "*$TunnelName*" }
if ($mine) {
    Write-Line ("tunnel connector already running, pid " + (($mine | ForEach-Object { $_.ProcessId }) -join ", "))
} else {
    Write-Line "starting the tunnel connector for $TunnelName"
    Start-Process -FilePath $exe -WindowStyle Hidden `
        -ArgumentList @("tunnel", "--no-autoupdate", "--label", $ConnectorLabel, "run", $TunnelName) `
        -RedirectStandardOutput (Join-Path $logRoot "cloudflared-$stamp.out.log") `
        -RedirectStandardError (Join-Path $logRoot "cloudflared-$stamp.err.log") | Out-Null
}
