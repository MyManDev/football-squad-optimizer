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
    [switch]$Verify
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$source = Join-Path $repo 'data'
$trees = @('snapshots', 'ledger', 'handoffs', 'advice_records', 'entries')

function File-Hash([string]$path) {
    $stream = [IO.File]::OpenRead($path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '') }
    finally { $sha.Dispose(); $stream.Dispose() }
}
function Assert-NoLinks([string]$path) {
    while ($path) {
        if (Test-Path -LiteralPath $path) {
            $item = Get-Item -LiteralPath $path -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Refusing a reparse point in a backup path.'
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
                    throw "Refusing a source reparse point in $tree."
                }
                if ($item.PSIsContainer) { $pending.Push($item.FullName) }
                else { $item }
            }
        }
    }
}
try {
    if ($DryRun -and $Verify) { throw 'Choose -DryRun or -Verify, not both.' }
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
    $files = @(Source-Files)
    if ($Verify) {
        $latest = Get-ChildItem -LiteralPath $destinationRoot -Filter 'manifest-*.json' -File |
            Sort-Object Name -Descending | Select-Object -First 1
        if (-not $latest) { throw 'No backup manifest found.' }
        Assert-NoLinks $latest.FullName
        $manifest = Get-Content -LiteralPath $latest.FullName -Raw | ConvertFrom-Json
        $seen = @{}
        $differences = 0
        foreach ($record in $manifest.files) {
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
        Write-Output "Verified $($manifest.files.Count) files against $($latest.Name)."
        exit 0
    }
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ')
    $records = New-Object 'Collections.Generic.List[object]'
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
                $targetRelative = "$relative.conflict-$stamp"
                $target = Manifest-Path $destinationRoot $targetRelative
                Write-Output "CONFLICT $relative; preserving incoming content as $targetRelative"
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
    if (-not $DryRun) {
        $manifest = @{created_at_utc=$stamp; files=@($records.ToArray())} | ConvertTo-Json -Depth 4
        $path = Join-Path $destinationRoot "manifest-$stamp.json"
        $stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew)
        try {
            $writer = New-Object IO.StreamWriter($stream)
            try { $writer.WriteLine($manifest) } finally { $writer.Dispose() }
        } finally { $stream.Dispose() }
        Write-Output "Wrote manifest-$stamp.json"
    }
} catch {
    Write-Error $_
    exit 1
}
