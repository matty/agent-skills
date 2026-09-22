#Requires -Version 7.0
<#
.SYNOPSIS
    Install, update and remove agent skills from this repo.

.DESCRIPTION
    Skills live in <repo>/skills/<name>/SKILL.md. This script exposes selected ones
    to Claude Code and Codex, either as directory junctions (default, no admin rights,
    edits in the repo are live) or as copies.

    Target roots:
        claude  ~/.claude/skills
        codex   ~/.codex/skills
        agents  ~/.agents/skills

    If a target root is itself a junction or symlink (e.g. ~/.claude/skills -> ~/.agents/skills),
    the script resolves it and installs into the real folder, then reports that it did so.
    Roots that resolve to the same place are visited once.

.PARAMETER Command
    list       Show repo skills and where each one is installed.
    install    Install the selected skills into the selected targets.
    update     git pull --ff-only, then refresh every already-installed skill.
    uninstall  Remove the selected skills from the selected targets.

.PARAMETER Skills
    Names or wildcards, e.g. -Skills vrchat-*,udon-performance. Default: all.

.PARAMETER Targets
    Any of claude, codex, agents. Default: claude, codex.

.PARAMETER Mode
    link (default) creates a junction to the repo, so edits in the repo are live.
    copy duplicates the files and records the source commit so `update` can refresh them.

.PARAMETER Prune
    On install/update, also remove managed skills that are no longer selected or that
    no longer exist in the repo.

.PARAMETER Force
    Replace an existing entry this repo does not manage (a real folder, or a link
    pointing somewhere else).

.PARAMETER NoPull
    update only: skip the git pull and just refresh from the working tree.

.EXAMPLE
    pwsh -File install.ps1 list

.EXAMPLE
    pwsh -File install.ps1 install -Skills vrchat-*

.EXAMPLE
    pwsh -File install.ps1 install -Targets agents -Mode copy

.EXAMPLE
    pwsh -File install.ps1 update -Prune
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Position = 0)]
    [ValidateSet('list', 'install', 'update', 'uninstall')]
    [string]$Command = 'list',

    [string[]]$Skills = @('*'),

    [ValidateSet('claude', 'codex', 'agents')]
    [string[]]$Targets = @('claude', 'codex'),

    [ValidateSet('link', 'copy')]
    [string]$Mode = 'link',

    [switch]$Prune,
    [switch]$Force,
    [switch]$NoPull
)

$ErrorActionPreference = 'Stop'

$RepoRoot   = $PSScriptRoot
$SkillsRoot = Join-Path $RepoRoot 'skills'
$MarkerName = '.agent-skills-source.json'

if (-not (Test-Path -LiteralPath $SkillsRoot)) {
    throw "No skills folder at $SkillsRoot - is install.ps1 still in the repo root?"
}

# --------------------------------------------------------------------------- helpers

function Write-Step { param([string]$Text) Write-Host $Text -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host "  $Text" -ForegroundColor Green }
function Write-Skip { param([string]$Text) Write-Host "  $Text" -ForegroundColor DarkGray }

function Test-ReparsePoint {
    param($Item)
    return $null -ne $Item -and ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint)
}

function Get-Entry {
    param([string]$Path)
    Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
}

# Deletes a junction/symlink without following it into the target. Plain folders are
# removed recursively, so callers must only pass folders this repo manages.
function Remove-Entry {
    param([string]$Path)
    $item = Get-Entry $Path
    if (-not $item) { return }
    if (Test-ReparsePoint $item) {
        [IO.Directory]::Delete($item.FullName, $false)
    }
    else {
        Remove-Item -LiteralPath $item.FullName -Recurse -Force
    }
}

function Resolve-TargetRoot {
    param([string]$Name)

    $path = switch ($Name) {
        'claude' { Join-Path $HOME '.claude/skills' }
        'codex'  { Join-Path $HOME '.codex/skills'  }
        'agents' { Join-Path $HOME '.agents/skills' }
    }

    $item = Get-Entry $path
    if (Test-ReparsePoint $item) {
        $real = ($item.Target | Select-Object -First 1)
        if ($real -and (Test-Path -LiteralPath $real)) {
            Write-Skip "$Name root $path is a link -> $real ; installing there"
            return [pscustomobject]@{ Name = $Name; Path = (Convert-Path $real) }
        }
    }
    return [pscustomobject]@{ Name = $Name; Path = $path }
}

function Get-TargetRoots {
    param([string[]]$Names)
    $seen = [ordered]@{}
    foreach ($name in $Names) {
        $root = Resolve-TargetRoot $name
        $key = $root.Path.TrimEnd('\', '/').ToLowerInvariant()
        if ($seen.Contains($key)) {
            $seen[$key].Name = "$($seen[$key].Name)+$($root.Name)"
            continue
        }
        $seen[$key] = $root
    }
    return @($seen.Values)
}

function Get-RepoSkills {
    Get-ChildItem -LiteralPath $SkillsRoot -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'SKILL.md') } |
        Sort-Object Name
}

function Select-RepoSkills {
    param($All, [string[]]$Patterns)

    $picked = foreach ($pattern in $Patterns) {
        $hits = @($All | Where-Object { $_.Name -like $pattern })
        if ($hits.Count -eq 0) { Write-Warning "no skill matches '$pattern'" }
        $hits
    }
    @($picked | Sort-Object Name -Unique)
}

function Get-RepoCommit {
    $sha = & git -C $RepoRoot rev-parse --short HEAD 2>$null
    if ($LASTEXITCODE -eq 0 -and $sha) { return "$sha".Trim() }
    return 'unknown'
}

# How an installed entry relates to this repo: Missing / Link / Copy / Foreign.
function Get-InstallState {
    param([string]$Root, [string]$SkillName)

    $path = Join-Path $Root $SkillName
    $item = Get-Entry $path
    if (-not $item) {
        return [pscustomobject]@{ Kind = 'Missing'; Path = $path; Detail = '' }
    }

    if (Test-ReparsePoint $item) {
        $target   = ($item.Target | Select-Object -First 1)
        $expected = Join-Path $SkillsRoot $SkillName
        if ($target -and $target.TrimEnd('\', '/') -ieq $expected.TrimEnd('\', '/')) {
            return [pscustomobject]@{ Kind = 'Link'; Path = $path; Detail = '' }
        }
        return [pscustomobject]@{ Kind = 'Foreign'; Path = $path; Detail = "link -> $target" }
    }

    $marker = Join-Path $path $MarkerName
    if (Test-Path -LiteralPath $marker) {
        $info = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
        return [pscustomobject]@{ Kind = 'Copy'; Path = $path; Detail = "from $($info.commit)" }
    }

    return [pscustomobject]@{ Kind = 'Foreign'; Path = $path; Detail = 'unmanaged folder' }
}

function Install-Skill {
    param($Skill, [string]$Root, [string]$InstallMode)

    $state = Get-InstallState -Root $Root -SkillName $Skill.Name
    $dest  = $state.Path

    if ($state.Kind -eq 'Foreign' -and -not $Force) {
        Write-Warning "  skip  $dest - $($state.Detail); pass -Force to replace"
        return
    }

    if ($InstallMode -eq 'link' -and $state.Kind -eq 'Link') {
        Write-Skip "ok    $dest"
        return
    }

    if (-not $PSCmdlet.ShouldProcess($dest, "install $($Skill.Name) ($InstallMode)")) { return }

    if (-not (Test-Path -LiteralPath $Root)) {
        New-Item -ItemType Directory -Path $Root -Force | Out-Null
    }
    Remove-Entry $dest

    if ($InstallMode -eq 'link') {
        New-Item -ItemType Junction -Path $dest -Target $Skill.FullName | Out-Null
        Write-Ok "link  $dest -> $($Skill.FullName)"
    }
    else {
        Copy-Item -LiteralPath $Skill.FullName -Destination $dest -Recurse -Force
        [pscustomobject]@{
            repo      = $RepoRoot
            skill     = $Skill.Name
            commit    = Get-RepoCommit
            installed = (Get-Date).ToString('o')
        } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dest $MarkerName) -Encoding utf8
        Write-Ok "copy  $dest"
    }
}

function Uninstall-Skill {
    param([string]$SkillName, [string]$Root)

    $state = Get-InstallState -Root $Root -SkillName $SkillName
    if ($state.Kind -eq 'Missing') { Write-Skip "none  $($state.Path)"; return }
    if ($state.Kind -eq 'Foreign' -and -not $Force) {
        Write-Warning "  skip  $($state.Path) - $($state.Detail); pass -Force to remove"
        return
    }
    if (-not $PSCmdlet.ShouldProcess($state.Path, "remove $SkillName")) { return }
    Remove-Entry $state.Path
    Write-Ok "rm    $($state.Path)"
}

# Managed entries under $Root whose skill is no longer in the repo at all.
function Remove-StaleEntries {
    param([string]$Root, [string[]]$RepoNames)

    if (-not (Test-Path -LiteralPath $Root)) { return }
    foreach ($entry in Get-ChildItem -LiteralPath $Root -Directory -Force) {
        if ($entry.Name -in $RepoNames) { continue }

        $managed = $false
        if (Test-ReparsePoint $entry) {
            $target = ($entry.Target | Select-Object -First 1)
            $managed = $target -and $target.StartsWith($SkillsRoot, 'OrdinalIgnoreCase')
        }
        elseif (Test-Path -LiteralPath (Join-Path $entry.FullName $MarkerName)) {
            $managed = $true
        }

        if ($managed -and $PSCmdlet.ShouldProcess($entry.FullName, 'prune skill removed from repo')) {
            Remove-Entry $entry.FullName
            Write-Ok "prune $($entry.FullName)"
        }
    }
}

# --------------------------------------------------------------------------- commands

$allSkills = @(Get-RepoSkills)
if ($allSkills.Count -eq 0) { throw "no skills found under $SkillsRoot" }
$repoNames = @($allSkills.Name)
$roots     = Get-TargetRoots $Targets

function Invoke-List {
    Write-Host ""
    Write-Host "repo    $RepoRoot @ $(Get-RepoCommit)"
    foreach ($root in $roots) { Write-Host "target  $($root.Name.PadRight(14)) $($root.Path)" }
    Write-Host ""

    foreach ($skill in $allSkills) {
        Write-Host $skill.Name -ForegroundColor White
        foreach ($root in $roots) {
            $state  = Get-InstallState -Root $root.Path -SkillName $skill.Name
            $colour = switch ($state.Kind) {
                'Link'    { 'Green' }
                'Copy'    { 'Green' }
                'Foreign' { 'Yellow' }
                default   { 'DarkGray' }
            }
            $detail = if ($state.Detail) { " ($($state.Detail))" } else { '' }
            Write-Host ("  {0,-16} {1}{2}" -f $root.Name, $state.Kind, $detail) -ForegroundColor $colour
        }
    }
    Write-Host ""
}

function Invoke-Install {
    param($Selected)

    $keep = @($Selected.Name)
    foreach ($root in $roots) {
        Write-Step "$($root.Name)  ->  $($root.Path)"
        foreach ($skill in $Selected) {
            Install-Skill -Skill $skill -Root $root.Path -InstallMode $Mode
        }

        if ($Prune) {
            foreach ($skill in $allSkills) {
                if ($skill.Name -in $keep) { continue }
                $state = Get-InstallState -Root $root.Path -SkillName $skill.Name
                if ($state.Kind -eq 'Link' -or $state.Kind -eq 'Copy') {
                    Uninstall-Skill -SkillName $skill.Name -Root $root.Path
                }
            }
            Remove-StaleEntries -Root $root.Path -RepoNames $repoNames
        }
    }
}

function Invoke-Update {
    if (-not $NoPull) {
        Write-Step "git pull --ff-only"
        & git -C $RepoRoot pull --ff-only
        if ($LASTEXITCODE -ne 0) { throw "git pull failed - resolve it, then re-run" }
    }

    # Refresh whatever is already installed; -Skills is ignored so update never widens
    # or narrows what you have.
    foreach ($root in $roots) {
        Write-Step "$($root.Name)  ->  $($root.Path)"
        $installed = @($allSkills | Where-Object {
            $kind = (Get-InstallState -Root $root.Path -SkillName $_.Name).Kind
            $kind -eq 'Link' -or $kind -eq 'Copy'
        })

        if ($installed.Count -eq 0) {
            Write-Skip "nothing installed here"
        }
        else {
            foreach ($skill in $installed) {
                $state = Get-InstallState -Root $root.Path -SkillName $skill.Name
                if ($state.Kind -eq 'Link') {
                    Write-Skip "ok    $($state.Path) (junction - already current)"
                }
                else {
                    Install-Skill -Skill $skill -Root $root.Path -InstallMode 'copy'
                }
            }
        }

        if ($Prune) { Remove-StaleEntries -Root $root.Path -RepoNames $repoNames }
    }
}

switch ($Command) {
    'list' { Invoke-List }

    'install' {
        $selected = Select-RepoSkills -All $allSkills -Patterns $Skills
        if ($selected.Count -eq 0) { throw "nothing selected - see: install.ps1 list" }
        Invoke-Install -Selected $selected
        Write-Host ""
        Write-Host ("installed {0}: {1}" -f $selected.Count, ($selected.Name -join ', '))
        Write-Host "Restart Claude Code / Codex - both scan for skills at startup." -ForegroundColor Yellow
    }

    'update' {
        Invoke-Update
        Write-Host ""
        Write-Host "Restart Claude Code / Codex if anything changed." -ForegroundColor Yellow
    }

    'uninstall' {
        $selected = Select-RepoSkills -All $allSkills -Patterns $Skills
        if ($selected.Count -eq 0) { throw "nothing selected - see: install.ps1 list" }
        foreach ($root in $roots) {
            Write-Step "$($root.Name)  ->  $($root.Path)"
            foreach ($skill in $selected) { Uninstall-Skill -SkillName $skill.Name -Root $root.Path }
        }
    }
}
