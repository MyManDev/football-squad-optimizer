<#
.SYNOPSIS
Additively back up the five irreplaceable data trees, or verify the latest manifest.
.DESCRIPTION
Windows PowerShell 5.1. No source writes, deletion, overwrite, runtime or raw reads.
The destination must already exist outside this repository and every linked worktree.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Destination,
    [switch]$DryRun,
    [switch]$Verify,
    [string]$Manifest = '',
    [switch]$AcceptMissing
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$source = Join-Path $repo 'data'
$trees = @('snapshots', 'ledger', 'handoffs', 'advice_records', 'entries')
$skippedTransient = New-Object 'Collections.Generic.List[string]'

function File-Hash([string]$path) {
    $share = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
    $stream = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, $share)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '') }
    finally { $sha.Dispose(); $stream.Dispose() }
}
function Assert-NoLinks([string]$path) {
    while ($path) {
        if (Test-Path -LiteralPath $path) {
            $item = Get-Item -LiteralPath $path -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Refusing reparse point: $path"
            }
        }
        $path = Split-Path -Parent $path
    }
}
function Is-Within([string]$path, [string]$root) {
    $root = $root.TrimEnd('\', '/')
    return $path.Equals($root, [StringComparison]::OrdinalIgnoreCase) -or
        $path.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}
function Manifest-Path([string]$root, [string]$relative) {
    if ($relative -notmatch '^(snapshots|ledger|handoffs|advice_records|entries)/' -or
        $relative.Split('/') -contains '..' -or $relative.Contains('\')) {
        throw 'Invalid relative path in manifest.'
    }
    $path = [IO.Path]::GetFullPath((Join-Path $root $relative))
    if (-not (Is-Within $path $root)) { throw 'Manifest path escapes its root.' }
    Assert-NoLinks $path
    return $path
}
function Is-Transient([string]$relative) {
    foreach ($name in $relative.Split('/')) {
        if ($name.StartsWith('.')) { return $true }
    }
    return $false
}
function Source-Files {
    foreach ($tree in $trees) {
        $root = Join-Path $source $tree
        Assert-NoLinks $root
        if (-not (Test-Path -LiteralPath $root -PathType Container)) {
            throw "Missing source tree: $tree"
        }
        $pending = New-Object 'Collections.Generic.Stack[string]'
        $pending.Push($root)
        while ($pending.Count) {
            foreach ($item in Get-ChildItem -LiteralPath $pending.Pop() -Force) {
                if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                    throw "Refusing a source reparse point: $($item.FullName)"
                }
                if (Is-Transient $item.Name) {
                    $skippedTransient.Add($item.FullName.Substring($source.Length + 1).Replace('\', '/'))
                    continue
                }
                if ($item.PSIsContainer) { $pending.Push($item.FullName) }
                else { $item }
            }
        }
    }
}
function Check-DestinationTree([string]$root) {
    Assert-NoLinks $root
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { return }
    foreach ($item in Get-ChildItem -LiteralPath $root -Force) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Refusing reparse point: $($item.FullName)"
        }
        if ($item.PSIsContainer) { Check-DestinationTree $item.FullName }
    }
}
try {
    if ($DryRun -and $Verify) { throw 'Choose -DryRun or -Verify, not both.' }
    if ($AcceptMissing -and ($DryRun -or $Verify)) { throw '-AcceptMissing requires a copy run.' }
    if ($Manifest -and (-not $Verify -or $Manifest -notmatch '^manifest-[A-Za-z0-9_-]+\.json$')) {
        throw '-Manifest requires -Verify and a manifest-*.json name inside the destination.'
    }
    Assert-NoLinks ([IO.Path]::GetFullPath($Destination))
    if (-not (Test-Path -LiteralPath $Destination -PathType Container)) {
        throw 'Destination must be an existing directory.'
    }
    $destinationRoot = (Resolve-Path -LiteralPath $Destination).ProviderPath
    $worktrees = @(& git -c core.quotepath=false -C $repo worktree list --porcelain)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot establish repository worktree boundaries.' }
    foreach ($line in $worktrees) {
        if ($line.StartsWith('worktree ')) {
            $root = [IO.Path]::GetFullPath($line.Substring(9))
            if (Is-Within $destinationRoot $root) {
                throw 'Destination must be outside the repository and every worktree.'
            }
        }
    }
    foreach ($tree in $trees) { Check-DestinationTree (Join-Path $destinationRoot $tree) }
    $files = @(Source-Files | Sort-Object FullName)
    Write-Output "Ignored dot-named source paths: $($skippedTransient.Count)"
    foreach ($relative in ($skippedTransient | Sort-Object | Select-Object -First 20)) {
        Write-Output "TRANSIENT $relative"
    }
    if ($skippedTransient.Count -gt 20) { Write-Output 'Showing the first 20 transient paths.' }
    $latest = Get-ChildItem -LiteralPath $destinationRoot -Filter 'manifest-*.json' -File |
        Sort-Object Name -Descending | Select-Object -First 1
    if ($Manifest) { $latest = Get-Item -LiteralPath (Join-Path $destinationRoot $Manifest) }
    $previous = $null
    if ($latest) {
        Assert-NoLinks $latest.FullName
        $previous = Get-Content -LiteralPath $latest.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        $ignoredPrevious = @($previous.files | Where-Object { Is-Transient $_.path })
        if ($ignoredPrevious.Count) {
            Write-Output "Ignored transient entries in $($latest.Name): $($ignoredPrevious.Count)"
        }
    }
    if ($Verify) {
        if (-not $latest) { throw 'No backup manifest found.' }
        $manifestDocument = $previous
        $seen = @{}
        $differences = 0
        foreach ($record in $manifestDocument.files) {
            if (Is-Transient $record.path) { continue }
            $seen[$record.path] = $true
            $pair = @{
                source = (Manifest-Path $source $record.path)
                destination = (Manifest-Path $destinationRoot $record.destination_path)
            }
            foreach ($side in @('source', 'destination')) {
                $path = $pair[$side]
                if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
                    (Get-Item -LiteralPath $path).Length -ne $record.size -or
                    (File-Hash $path) -ne $record.sha256) {
                    Write-Output "DIFFERENT $side $($record.path)"
                    $differences++
                }
            }
        }
        foreach ($file in $files) {
            $relative = $file.FullName.Substring($source.Length + 1).Replace('\', '/')
            if (-not $seen.ContainsKey($relative)) {
                Write-Output "UNRECORDED source $relative"
                $differences++
            }
        }
        if ($differences) { throw "Verification found $differences differences." }
        Write-Output "Verified $($seen.Count) files against $($latest.Name)."
        exit 0
    }
    $missing = @()
    if ($previous) {
        $missing = @($previous.files | Where-Object {
            -not (Is-Transient $_.path) -and
                -not (Test-Path -LiteralPath (Manifest-Path $source $_.path) -PathType Leaf)
        })
        if ($missing.Count) {
            Write-Output "MISSING at source: $($missing.Count) files"
            foreach ($record in ($missing | Select-Object -First 20)) { Write-Output $record.path }
            if ($missing.Count -gt 20) { Write-Output 'Showing the first 20 missing paths.' }
        }
    }
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ')
    $records = New-Object 'Collections.Generic.List[object]'
    $newConflicts = New-Object 'Collections.Generic.List[string]'
    [long]$bytes = 0
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($source.Length + 1).Replace('\', '/')
        $targetRelative = $relative
        $target = Manifest-Path $destinationRoot $targetRelative
        $hash = File-Hash $file.FullName
        if (Test-Path -LiteralPath $target) {
            if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
                throw "Destination is not a file: $relative"
            }
            if ((File-Hash $target) -ne $hash) {
                $same = Get-ChildItem -LiteralPath (Split-Path -Parent $target) -File |
                    Where-Object { $_.Name.StartsWith($file.Name + '.conflict-') } |
                    Sort-Object Name | Where-Object { (File-Hash $_.FullName) -eq $hash } |
                    Select-Object -First 1
                if ($same) {
                    $targetRelative = $same.FullName.Substring($destinationRoot.Length + 1).Replace('\', '/')
                } else {
                    $targetRelative = "$relative.conflict-$stamp"
                    $newConflicts.Add($relative)
                    Write-Output "CONFLICT $relative; preserving incoming content as $targetRelative"
                }
                $target = Manifest-Path $destinationRoot $targetRelative
            }
        }
        if (-not (Test-Path -LiteralPath $target)) {
            Write-Output "COPY $relative -> $targetRelative ($($file.Length) bytes)"
            $bytes += $file.Length
            if (-not $DryRun) {
                $null = [IO.Directory]::CreateDirectory((Split-Path -Parent $target))
                [IO.File]::Copy($file.FullName, $target, $false)
            }
        }
        if (-not $DryRun -and (File-Hash $target) -ne $hash) {
            throw "Source changed during copy: $relative; no manifest written."
        }
        $records.Add(@{path=$relative; destination_path=$targetRelative; size=$file.Length; sha256=$hash})
    }
    Write-Output "Copy total: $bytes bytes; examined $($files.Count) files."
    if ($missing.Count -and -not $AcceptMissing) {
        if ($DryRun) { throw 'Source loss detected; dry run wrote no files or manifest.' }
        throw 'Source loss detected; additive copies retained, no manifest written. Restore or acknowledge with -AcceptMissing.'
    }
    if ($missing.Count) { Write-Output "ACCEPTED missing at source: $($missing.Count) files; old backups retained." }
    if (-not $DryRun) {
        $manifestDocument = @{created_at_utc=$stamp; files=@($records.ToArray())} | ConvertTo-Json -Depth 4
        $path = Join-Path $destinationRoot "manifest-$stamp.json"
        $stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew)
        try {
            $writer = New-Object IO.StreamWriter($stream)
            try { $writer.WriteLine($manifestDocument) } finally { $writer.Dispose() }
        } finally { $stream.Dispose() }
        Write-Output "Wrote manifest-$stamp.json"
    }
    if ($newConflicts.Count) {
        Write-Output "New conflicts: $($newConflicts.Count); inspect the named files."
        exit 1
    }
} catch {
    Write-Output $_.Exception.Message
    exit 1
}
