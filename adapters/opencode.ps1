# adapters/opencode.ps1 — установка для OpenCode (PowerShell).
#
# OpenCode использует markdown-команды и agent-файлы:
#   global:  $HOME/.config/opencode/commands/<name>.md  и  .../agents/<name>.md
#   project: .opencode/commands/<name>.md                и  .opencode/agents/<name>.md
#
# Запуск команды в OpenCode: /<command-name> (см. README).
# opencode.json/opencode.jsonc НЕ трогаем.
#
# Dot-source'ится из install.ps1; использует функции lib/common.ps1.

function Get-OpenCodeBaseDir {
    if ($script:InstallDir) { return (Expand-HomePath $script:InstallDir) }
    if ($script:Scope -eq "project") { return (Join-Path (Get-Location).Path ".opencode") }
    return (Join-Path $HOME ".config/opencode")
}

function Get-OpenCodeCommandFile { return (Join-Path (Get-OpenCodeBaseDir) "commands/$($script:SkillName).md") }
function Get-OpenCodeAgentFile   { return (Join-Path (Get-OpenCodeBaseDir) "agents/$($script:SkillName).md") }
function Get-OpenCodeResourceDir { return (Join-Path (Get-OpenCodeBaseDir) "skills/$($script:SkillName)") }

function Get-OpenCodeCommandContent {
    $desc = Get-SkillField (Join-Path $script:SkillSrcDir "SKILL.md") "description"
    @"
---
description: $desc
---

Используй локальный индекс кода вместо полного сканирования репозитория.

Выполни поиск по индексу и ответь с цитатами file:line:

``````bash
codebase-index search "`$ARGUMENTS" --json
``````

Подкоманды: ``search``, ``symbol <name>``, ``refs <name>``, ``impact <file|symbol>``.
Если индекс отсутствует — сначала выполни ``codebase-index index``.
"@
}

function Invoke-AdapterInstall {
    $cmd = Get-OpenCodeCommandFile
    $agent = Get-OpenCodeAgentFile
    $resdir = Get-OpenCodeResourceDir
    Assert-NoTraversal $cmd
    Assert-NoTraversal $resdir
    Write-Info "OpenCode команда:  $cmd"
    Write-Info "OpenCode agent:    $agent"
    Write-Info "OpenCode ресурсы:  $resdir"

    if ((Test-Path $cmd) -and -not $script:Force -and -not $script:DryRun) {
        Stop-WithError "Команда уже установлена: $cmd (используйте -Force)" 6
    }

    $files = [System.Collections.ArrayList]::new()

    if (Test-Path $resdir) {
        Backup-Path $resdir | Out-Null
        if (-not $script:DryRun) { Remove-Item $resdir -Recurse -Force }
    }
    Copy-Tree -Source $script:SkillSrcDir -Destination $resdir -FileList $files

    if ($script:DryRun) {
        Write-Info "[dry-run] записал бы команду: $cmd"
        Write-Info "[dry-run] записал бы agent: $agent"
    } else {
        $cmdDir = Split-Path -Parent $cmd
        if (-not (Test-Path $cmdDir)) { New-Item -ItemType Directory -Path $cmdDir -Force | Out-Null }
        if (Test-Path $cmd) { Backup-Path $cmd | Out-Null }
        Set-Content -Path $cmd -Value (Get-OpenCodeCommandContent) -Encoding UTF8
        [void]$files.Add($cmd); Write-Ok "Команда записана: $cmd"

        $agentDir = Split-Path -Parent $agent
        if (-not (Test-Path $agentDir)) { New-Item -ItemType Directory -Path $agentDir -Force | Out-Null }
        if (Test-Path $agent) { Backup-Path $agent | Out-Null }
        Copy-Item -Path (Join-Path $script:SkillSrcDir "SKILL.md") -Destination $agent -Force
        [void]$files.Add($agent); Write-Ok "Agent записан: $agent"
    }

    $mf = Join-Path $resdir "install_manifest.json"
    $status = Invoke-PythonBootstrap -ResourceDir $resdir -ManifestPath $mf -Target "opencode"
    $pyver = "none"
    if (-not $script:NoPythonBootstrap) { $py = Find-Python; if ($py) { $pyver = Get-PythonVersion $py } }
    Write-Manifest -ManifestPath $mf -Target "opencode" -PythonVersion $pyver -BootstrapStatus $status -InstalledFiles $files

    Write-Ok "OpenCode: команда установлена. Запуск: /$($script:SkillName)"
}

function Invoke-AdapterUninstall {
    $resdir = Get-OpenCodeResourceDir
    $mf = Join-Path $resdir "install_manifest.json"
    if (Test-Path $mf) { Remove-FromManifest $mf }

    foreach ($p in @((Get-OpenCodeCommandFile), (Get-OpenCodeAgentFile))) {
        if (Test-Path $p) {
            if ($script:DryRun) { Write-Info "[dry-run] удалил бы: $p" }
            else { Remove-Item $p -Force; Write-Ok "Удалён: $p" }
        }
    }
    if (Test-Path $resdir) {
        if ($script:DryRun) { Write-Info "[dry-run] удалил бы: $resdir" }
        else { Remove-Item $resdir -Recurse -Force; Write-Ok "Удалены ресурсы: $resdir" }
    }
}
