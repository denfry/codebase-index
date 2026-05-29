# adapters/codex.ps1 — установка для Codex CLI (PowerShell).
#
# Для Codex это instruction package, а не «Claude Skill»:
#   * инструкции -> managed block в AGENTS.md (project) или $HOME/.codex/AGENTS.md (global);
#   * существующий AGENTS.md НЕ затирается (backup + патч только блока);
#   * ресурсы -> $HOME/.codex/skills/<skill-name>/.
#
# Dot-source'ится из install.ps1; использует функции lib/common.ps1.

function Get-CodexResourceDir {
    if ($script:InstallDir -and $script:Scope -eq "global") {
        return (Join-Path (Expand-HomePath $script:InstallDir) "skills/$($script:SkillName)")
    }
    return (Join-Path $HOME ".codex/skills/$($script:SkillName)")
}

function Get-CodexAgentsFile {
    if ($script:Scope -eq "project") { return (Join-Path (Get-Location).Path "AGENTS.md") }
    if ($script:InstallDir) { return (Join-Path (Expand-HomePath $script:InstallDir) "AGENTS.md") }
    return (Join-Path $HOME ".codex/AGENTS.md")
}

function Get-CodexBlockContent {
    param([string]$ResourceDir)
    $desc = Get-SkillField (Join-Path $script:SkillSrcDir "SKILL.md") "description"
    @"
## Skill: $($script:SkillName) (managed)

$desc

Ресурсы skill установлены в: ``$ResourceDir``
Подробная инструкция: ``$ResourceDir/SKILL.md``

Используйте CLI ``codebase-index`` (обёртка ``cbx``) для поиска по индексу
перед чтением файлов. Команды: ``search``, ``symbol``, ``refs``, ``impact``.
"@
}

function Invoke-AdapterInstall {
    $resdir = Get-CodexResourceDir
    $agents = Get-CodexAgentsFile
    Assert-NoTraversal $resdir
    Assert-NoTraversal $agents
    Write-Info "Codex CLI ресурсы:   $resdir"
    Write-Info "Codex CLI инструкции: $agents"

    if ((Test-Path $resdir) -and -not $script:Force -and -not $script:DryRun) {
        Stop-WithError "Ресурсы уже установлены: $resdir (используйте -Force)" 6
    }
    if (Test-Path $resdir) {
        Backup-Path $resdir | Out-Null
        if (-not $script:DryRun) { Remove-Item $resdir -Recurse -Force }
    }

    $files = [System.Collections.ArrayList]::new()
    Copy-Tree -Source $script:SkillSrcDir -Destination $resdir -FileList $files
    if (-not $script:DryRun) {
        if (-not (Test-SkillFrontmatter (Join-Path $resdir "SKILL.md"))) {
            Stop-WithError "SKILL.md невалиден после копирования" 2
        }
    }

    Update-ManagedBlock -File $agents -Content (Get-CodexBlockContent -ResourceDir $resdir)
    if (-not $script:DryRun) { [void]$files.Add($agents) }

    $mf = Join-Path $resdir "install_manifest.json"
    $status = Invoke-PythonBootstrap -ResourceDir $resdir -ManifestPath $mf -Target "codex"
    $pyver = "none"
    if (-not $script:NoPythonBootstrap) { $py = Find-Python; if ($py) { $pyver = Get-PythonVersion $py } }
    Write-Manifest -ManifestPath $mf -Target "codex" -PythonVersion $pyver -BootstrapStatus $status -InstalledFiles $files

    Write-Ok "Codex CLI: instruction package установлен."
}

function Invoke-AdapterUninstall {
    $resdir = Get-CodexResourceDir
    $agents = Get-CodexAgentsFile
    Remove-ManagedBlock $agents
    if (Test-Path $resdir) {
        if ($script:DryRun) { Write-Info "[dry-run] удалил бы ресурсы: $resdir" }
        else { Backup-Path $resdir | Out-Null; Remove-Item $resdir -Recurse -Force; Write-Ok "Codex CLI: удалены ресурсы $resdir" }
    } else {
        Write-Warn "Codex CLI: ресурсы не найдены: $resdir"
    }
}
