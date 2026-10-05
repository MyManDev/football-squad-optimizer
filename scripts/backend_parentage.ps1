# Dot-sourced by scripts\run_backend_local.ps1 and scripts\release\restart_backend.ps1.
#
# A backend started from inside an application's own process tree lives only as long as
# that application keeps it: on 2026-10-04 a Microsoft Store update of the Codex app replaced
# its sandbox service, and the api and the six workers started from that sandbox the day
# before died with it, while the tunnel connector, started on 2026-09-30 by a watcher outside
# any application, kept running. So the backend is started only from a plain console or by
# the SquadOptBackendWatch task, and these scripts refuse to start it from an agent.
#
# Two signs, because one alone misses a case: an agent application among the ancestors
# (a start from an agent's shell), and an environment variable the agent sets for its
# shells, which a process started detached from that shell still inherits after the shell
# that started it has exited and the ancestry no longer leads back to the agent.
#
# Windows PowerShell 5.1 compatible on purpose (no &&, no ternary, ASCII only).

# The image names that count as an agent application: Claude, the Codex desktop app
# (ChatGPT.exe), its agent and its sandbox service. SQUADOPT_AGENT_APPLICATIONS replaces the
# list (comma separated) so a test can name a process its own tree really has; it is not a
# way to start a backend from an agent, which must never set it.
$BackendAgentApplications = @('claude.exe', 'ChatGPT.exe', 'codex.exe', 'codex-windows-sandbox-service.exe')
if ($null -ne $env:SQUADOPT_AGENT_APPLICATIONS) {
    $BackendAgentApplications = @($env:SQUADOPT_AGENT_APPLICATIONS -split ',' |
        ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

# The variables the agents set for the shells they run: Claude Code's, and the Codex
# sandbox's.
$BackendAgentMarkers = @('CLAUDECODE', 'CODEX_SANDBOX', 'CODEX_SANDBOX_NETWORK_DISABLED', 'CODEX_SESSION_ID')

# The first ancestor of $ProcessId whose image name is an agent application, or $null.
# $Table maps a pid to an object with Name, ParentProcessId and CreationDate (the shape of
# Win32_Process); without one the live process table is read. The walk stops at a missing
# parent, at a cycle, and at a parent created after its child, which is a pid Windows has
# handed to an unrelated process since the real parent ended.
function Find-AgentAncestor {
    param([int]$ProcessId, $Table = $null)
    if ($null -eq $Table) {
        $Table = @{}
        foreach ($process in @(Get-CimInstance Win32_Process -ErrorAction Stop)) {
            $Table[[int]$process.ProcessId] = $process
        }
    }
    $seen = @{}
    $child = $Table[$ProcessId]
    while ($null -ne $child -and -not $seen.ContainsKey([int]$child.ProcessId)) {
        $seen[[int]$child.ProcessId] = $true
        $parent = $Table[[int]$child.ParentProcessId]
        if ($null -eq $parent) { return $null }
        if ($null -ne $parent.CreationDate -and $null -ne $child.CreationDate -and
            $parent.CreationDate -gt $child.CreationDate) { return $null }
        # -contains compares without case, as Windows names images.
        if ($BackendAgentApplications -contains [string]$parent.Name) { return $parent }
        $child = $parent
    }
    return $null
}

# The first agent marker set in this process's environment, or $null.
function Find-AgentMarker {
    foreach ($name in $BackendAgentMarkers) {
        $value = [Environment]::GetEnvironmentVariable($name, 'Process')
        if (-not [string]::IsNullOrEmpty($value)) { return $name }
    }
    return $null
}

# Throw when this process runs under an agent application or with an agent's marker,
# naming which and the way out. A restart's way out is a console: the watch task starts a
# missing backend, it never replaces a running one.
function Assert-NotUnderAgentApplication {
    param([string]$Action)
    $source = $null
    $agent = Find-AgentAncestor -ProcessId $PID
    if ($null -ne $agent) { $source = "under {0} (pid {1})" -f $agent.Name, $agent.ProcessId }
    $marker = Find-AgentMarker
    if ($null -eq $source -and $null -ne $marker) {
        $source = "with {0} set, which an agent sets for the shells it runs" -f $marker
    }
    if ($null -eq $source) { return }
    $way = "Run it from a plain Windows PowerShell window."
    if ($Action -eq "start the backend") {
        $way = "Start it from a plain Windows PowerShell window, or let the SquadOptBackendWatch task start it."
    }
    $message = "Refusing to {0}: this runs {1}, and a backend started from an agent's process " +
        "tree dies when that application updates or closes, as it did on 2026-10-04. {2} " +
        "(docs/backend_free_hosting.md)"
    throw ($message -f $Action, $source, $way)
}
