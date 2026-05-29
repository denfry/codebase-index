# adapters/claude.ps1 — установка skill для Claude Code (PowerShell).
#
# Claude Code ищет skills в skills/<name>/SKILL.md:
#   global:  $HOME/.claude/skills/<skill-name>/
#   project: <project>/.claude/skills/<skill-name>/
#
# ВАЖНО: точный путь зависит от версии Claude Code. Переопределяется -InstallDir;
# дефолт вынесен в функцию Get-ClaudeTargetDir. См. README.
#
# Dot-source'ится из install.ps1; использует функции lib/common.ps1 и $script:* переменные.

function Get-ClaudeTargetDir {
    if ($script:InstallDir) { return (Expand-HomePath $script:InstallDir) }
    if ($script:Scope -eq "project") {
        return (Join-Path (Get-Location).Path ".claude/skills/$($script:SkillName)")
    }
    return (Join-Path $HOME ".claude/skills/$($script:SkillName)")
}

function Invoke-AdapterInstall {
    $dst = Get-ClaudeTargetDir
    Assert-NoTraversal $dst
    Write-Info "Claude Code skill-директория: $dst"

    if (-not $script:InstallDir) {
        if (-not (Test-PathWithin $HOME $dst) -and -not (Test-PathWithin (Get-Location).Path $dst)) {
            Stop-WithError "Путь вне HOME/проекта без -InstallDir: $dst" 2
        }
    }

    if ((Test-Path $dst) -and -not $script:Force -and -not $script:DryRun) {
        Stop-WithError "Уже установлено: $dst (используйте -Force)" 6
    }
    if (Test-Path $dst) {
        Backup-Path $dst | Out-Null
        if (-not $script:DryRun) { Remove-Item $dst -Recurse -Force }
    }

    $files = [System.Collections.ArrayList]::new()
    Copy-Tree -Source $script:SkillSrcDir -Destination $dst -FileList $files

    if (-not $script:DryRun) {
        if (-not (Test-SkillFrontmatter (Join-Path $dst "SKILL.md"))) {
            Stop-WithError "После копирования SKILL.md невалиден" 2
        }
    }

    $mf = Join-Path $dst "install_manifest.json"
    $status = Invoke-PythonBootstrap -ResourceDir $dst -ManifestPath $mf -Target "claude"
    $pyver = "none"
    if (-not $script:NoPythonBootstrap) { $py = Find-Python; if ($py) { $pyver = Get-PythonVersion $py } }
    Write-Manifest -ManifestPath $mf -Target "claude" -PythonVersion $pyver -BootstrapStatus $status -InstalledFiles $files

    Write-Ok "Claude Code: skill установлен в $dst"
    Write-Info "Активируйте через меню skills в Claude Code (имя: $($script:SkillName))."
}

function Invoke-AdapterUninstall {
    $dst = Get-ClaudeTargetDir
    $mf = Join-Path $dst "install_manifest.json"
    if (Test-Path $mf) { Remove-FromManifest $mf }
    if (Test-Path $dst) {
        if ($script:DryRun) { Write-Info "[dry-run] удалил бы директорию: $dst" }
        else { Backup-Path $dst | Out-Null; Remove-Item $dst -Recurse -Force; Write-Ok "Claude Code: удалена директория $dst" }
    } else {
        Write-Warn "Claude Code: директория не найдена: $dst"
    }
}
