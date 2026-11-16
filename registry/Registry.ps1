#requires -Version 7.0
<#
.SYNOPSIS
  The model registry under this folder: list, index, resolve, verify, new-manifest. See README.md.
.EXAMPLE
  .\Registry.ps1 resolve qwen36-35b-a3b
  .\Registry.ps1 new-manifest .\hf\org\repo\abc123def456 -Format gguf -Repo org/repo -Revision abc123def456...
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)] [ValidateSet('list', 'index', 'resolve', 'verify', 'new-manifest')] [string] $Command = 'list',
    [Parameter(Position = 1)] [string] $Target,
    [switch] $Hash,
    [string] $Format,
    [string] $Repo,
    [string] $Revision,
    [string] $DerivedFrom,
    [string] $Notes
)
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$areas = 'hf', 'sub0llm', 'local'

function Get-Manifests {
    foreach ($a in $areas) {
        $dir = Join-Path $root $a
        if (-not (Test-Path $dir)) { continue }
        Get-ChildItem $dir -Recurse -Filter MANIFEST.json -File | ForEach-Object {
            $m = Get-Content $_.FullName -Raw | ConvertFrom-Json -AsHashtable
            $m['path'] = $_.DirectoryName
            $m
        }
    }
}

function Get-IdForFolder([string] $folder) {
    $rel = [System.IO.Path]::GetRelativePath($root, $folder) -replace '\\', '/'
    $parts = $rel -split '/'
    if ($parts.Count -lt 3) { throw "Not a version folder (needs <area>/.../<version>): $rel" }
    return (($parts[0..($parts.Count - 2)]) -join '/') + '@' + $parts[-1]
}

function Get-Aliases {
    $p = Join-Path $root 'aliases.json'
    if (Test-Path $p) { return Get-Content $p -Raw | ConvertFrom-Json -AsHashtable }
    return @{}
}

function Resolve-Ref([string] $ref) {
    $aliases = Get-Aliases
    if ($aliases.ContainsKey($ref)) { $ref = $aliases[$ref] }
    $file = $null
    if ($ref -match '^(.*)#(.+)$') { $ref = $Matches[1]; $file = $Matches[2] }
    $m = Get-Manifests | Where-Object { $_.id -eq $ref } | Select-Object -First 1
    if (-not $m) { throw "No registry entry: $ref" }
    if (-not $file) {
        $models = @($m.files | Where-Object { $_.name -notmatch 'mmproj' -and $_.name -match '\.gguf$' -and $_.name -notmatch '-0000[2-9]-of-' })
        if ($models.Count -ge 1) { $file = @($models | Sort-Object { $_.name })[0].name }
    }
    if ($file) { return Join-Path $m.path $file }
    return $m.path
}

switch ($Command) {
    'list' {
        Get-Manifests | Sort-Object id | ForEach-Object {
            $bytes = ($_.files | Measure-Object -Property bytes -Sum).Sum
            [pscustomobject]@{ Id = $_.id; Format = $_.format; GiB = [math]::Round($bytes / 1GB, 1); Files = @($_.files).Count }
        } | Format-Table -AutoSize
        $aliases = Get-Aliases
        if ($aliases.Count) { 'Aliases:'; $aliases.GetEnumerator() | Sort-Object Name | ForEach-Object { '  {0,-24} -> {1}' -f $_.Name, $_.Value } }
    }
    'index' {
        $entries = [ordered]@{}
        foreach ($m in (Get-Manifests | Sort-Object id)) {
            $expected = Get-IdForFolder $m.path
            if ($m.id -ne $expected) { Write-Warning "MANIFEST id '$($m.id)' does not match its folder ('$expected')" }
            $entries[$m.id] = $m
        }
        $aliases = Get-Aliases
        foreach ($k in $aliases.Keys) {
            $id = ($aliases[$k] -split '#')[0]
            if (-not $entries.Contains($id)) { Write-Warning "alias '$k' points at a missing entry: $id" }
        }
        $out = [ordered]@{ generated = (Get-Date -Format 's'); root = $root; aliases = $aliases; entries = $entries }
        $out | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $root 'registry.json') -Encoding utf8
        "registry.json: $($entries.Count) entries, $($aliases.Count) aliases"
    }
    'resolve' {
        if (-not $Target) { throw 'resolve needs an alias or id' }
        Resolve-Ref $Target
    }
    'verify' {
        $bad = 0
        foreach ($m in Get-Manifests) {
            $changed = $false
            foreach ($f in $m.files) {
                $p = Join-Path $m.path $f.name
                if (-not (Test-Path $p)) { Write-Warning "$($m.id): missing $($f.name)"; $bad++; continue }
                $len = (Get-Item $p).Length
                if ($len -ne $f.bytes) { Write-Warning "$($m.id): $($f.name) is $len bytes, manifest says $($f.bytes)"; $bad++ }
                if ($Hash) {
                    $h = (Get-FileHash $p -Algorithm SHA256).Hash.ToLowerInvariant()
                    if ($f.sha256 -and $f.sha256 -ne $h) { Write-Warning "$($m.id): $($f.name) sha256 mismatch"; $bad++ }
                    elseif (-not $f.sha256) { $f.sha256 = $h; $changed = $true }
                }
            }
            if ($changed) {
                $copy = [ordered]@{}; foreach ($k in $m.Keys) { if ($k -ne 'path') { $copy[$k] = $m[$k] } }
                $copy | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $m.path 'MANIFEST.json') -Encoding utf8
                "$($m.id): sha256 recorded"
            }
        }
        if ($bad) { throw "$bad problem(s)" } else { 'all manifests verified' }
    }
    'new-manifest' {
        if (-not $Target) { throw 'new-manifest needs a version folder' }
        $folder = (Resolve-Path $Target).Path
        $mf = Join-Path $folder 'MANIFEST.json'
        if (Test-Path $mf) { throw "Already has a manifest (versions are immutable; make a new version): $mf" }
        $files = Get-ChildItem $folder -File -Recurse | Where-Object { $_.Name -ne 'MANIFEST.json' -and $_.Extension -ne '.log' } |
            ForEach-Object { [ordered]@{ name = [System.IO.Path]::GetRelativePath($folder, $_.FullName); bytes = $_.Length; sha256 = $null } } |
            Sort-Object { $_.name }
        $m = [ordered]@{
            id          = Get-IdForFolder $folder
            format      = $(if ($Format) { $Format } else { 'unknown' })
            files       = @($files)
            source      = $(if ($Repo) { [ordered]@{ kind = 'hf'; repo = $Repo; revision = $(if ($Revision) { $Revision } else { $null }); url = $null } } else { $null })
            derivedFrom = $(if ($DerivedFrom) { $DerivedFrom } else { $null })
            tool        = $null
            created     = (Get-Date -Format 'yyyy-MM-dd')
            notes       = $(if ($Notes) { $Notes } else { '' })
        }
        $m | ConvertTo-Json -Depth 8 | Set-Content $mf -Encoding utf8
        "wrote $mf"
    }
}
