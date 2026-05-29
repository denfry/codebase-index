<#
.SYNOPSIS
  Единый installer (PowerShell) для skill codebase-index.

.DESCRIPTION
  Раскладывает skill в несколько CLI-сред: Claude Code, Codex CLI, OpenCode.
  Архитектура: один entrypoint (этот файл) + адаптеры adapters/<target>.ps1.
  Источник правды — каталог skill/ в репозитории.

  Запуск (см. README):
    irm https://raw.githubusercontent.com/denfry/codebase-index/main/install.ps1 | iex
  или локально:
    pwsh ./install.ps1 -Target claude -DryRun

.NOTES
  Поддерживает Windows PowerShell 5.1 и PowerShell 7+ (Core).
#>
[CmdletBinding()]
param(
    [ValidateSet("claude", "codex", "opencode", "all", "auto")]
    [string]$Target = "auto",

    [string]$InstallDir = "",
    [string]$RepoUrl = "https://github.com/denfry/codebase-index",
    [string]$Branch = "main",

    [ValidateSet("global", "project")]
    [string]$Scope = "global",

    [switch]$DryRun,
    [switch]$Force,
    [switch]$NoPythonBootstrap,
    [switch]$Uninstall,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# --------------------------------------------------------------------------
# Константы skill (легко заменить под свой проект)
# --------------------------------------------------------------------------
$script:SkillName    = "codebase-index"   # placeholder: SKILL_NAME
$script:SkillVersion = "1.0.2"            # placeholder: SKILL_VERSION

# Прокидываем параметры в script-scope, чтобы их видели dot-source'нутые файлы.
$script:InstallDir         = $InstallDir
$script:RepoUrl            = $RepoUrl
$script:Branch             = $Branch
$script:Scope              = $Scope
$script:DryRun             = [bool]$DryRun
$script:Force              = [bool]$Force
$script:NoPythonBootstrap  = [bool]$NoPythonBootstrap
$script:Verbose            = $VerbosePreference -ne "SilentlyContinue"
$script:DoUninstall        = [bool]$Uninstall

function Show-Usage {
    @"
install.ps1 — установка skill codebase-index в Claude Code / Codex CLI / OpenCode.

ИСПОЛЬЗОВАНИЕ:
  pwsh ./install.ps1 [параметры]

ПАРАМЕТРЫ:
  -Target  claude|codex|opencode|all|auto   Куда ставить (по умолчанию: auto)
  -InstallDir PATH        Переопределить директорию установки
  -RepoUrl URL            URL репозитория-источника
  -Branch BRANCH          Ветка/тег для скачивания
  -Scope global|project   Глобально или в текущий проект
  -DryRun                 Ничего не менять, только показать действия
  -Force                  Перезаписывать существующую установку
  -NoPythonBootstrap      Не создавать venv и не запускать bootstrap.py
  -Verbose                Подробный вывод
  -Uninstall              Удалить ранее установленный skill (по manifest)
  -Help                   Показать эту справку

БЕЗОПАСНОСТЬ (pipe-to-shell): предпочтительно скачать и просмотреть скрипт:
  irm <URL>/install.ps1 -OutFile install.ps1
  Get-Content install.ps1 | more
  pwsh ./install.ps1
"@ | Write-Host
}

if ($Help) { Show-Usage; exit 0 }

# --------------------------------------------------------------------------
# Определение корня исходников: локальный clone или скачивание архива
# --------------------------------------------------------------------------
$script:TmpRoot = $null

function Resolve-SourceRoot {
    $selfDir = if ($PSScriptRoot) { $PSScriptRoot } else { "" }
    if ($selfDir -and (Test-Path (Join-Path $selfDir "lib/common.ps1")) -and (Test-Path (Join-Path $selfDir "skill"))) {
        Write-Host "[INFO]  Локальный источник: $selfDir"
        return $selfDir
    }
    Write-Host "[INFO]  Локальный источник не найден — скачиваю репозиторий."
    $script:TmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("cbx-installer-" + [System.Guid]::NewGuid().ToString("N").Substring(0,8))
    New-Item -ItemType Directory -Path $script:TmpRoot -Force | Out-Null
    $arc = Join-Path $script:TmpRoot "repo.zip"

    # Используем функции из common.ps1 — но он ещё не загружен.
    # Скачиваем минимально здесь, затем dot-source.
    $repo = $RepoUrl.TrimEnd('/'); if ($repo.EndsWith(".git")) { $repo = $repo.Substring(0, $repo.Length - 4) }
    $url = "$repo/archive/refs/heads/$Branch.zip"
    Write-Host "[INFO]  Источник (скачиваем архив): $url"
    Invoke-WebRequest -Uri $url -OutFile $arc -UseBasicParsing
    $extracted = Join-Path $script:TmpRoot "extracted"
    Expand-Archive -Path $arc -DestinationPath $extracted -Force
    $root = Get-ChildItem -Path $extracted -Directory | Where-Object { Test-Path (Join-Path $_.FullName "skill") } | Select-Object -First 1
    if (-not $root) { Write-Host "[ERROR] В архиве не найден каталог skill/."; exit 1 }
    Write-Host "[INFO]  Распаковано в: $($root.FullName)"
    return $root.FullName
}

function Get-AutoTargets {
    $found = @()
    if ((Test-Command "claude")   -or (Test-Path (Join-Path $HOME ".claude")))             { $found += "claude" }
    if ((Test-Command "codex")    -or (Test-Path (Join-Path $HOME ".codex")))              { $found += "codex" }
    if ((Test-Command "opencode") -or (Test-Path (Join-Path $HOME ".config/opencode")))    { $found += "opencode" }
    return $found
}

function Invoke-OneTarget {
    param([string]$TargetName, [string]$SourceRoot)
    $adapter = Join-Path $SourceRoot "adapters/$TargetName.ps1"
    if (-not (Test-Path $adapter)) { Write-ErrorMessage "Адаптер не найден: $adapter"; return $false }
    Write-Info "=== Target: $TargetName ==="
    $script:SkillSrcDir = Join-Path $SourceRoot "skill"
    # Dot-source адаптера: переопределяет Invoke-AdapterInstall / Invoke-AdapterUninstall.
    . $adapter
    try {
        if ($script:DoUninstall) { Invoke-AdapterUninstall } else { Invoke-AdapterInstall }
        return $true
    } catch {
        Write-ErrorMessage "Target '$TargetName' завершился с ошибкой: $_"
        return $false
    }
}

# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
try {
    if ($script:DryRun) { Write-Host "[INFO]  Режим dry-run: изменения НЕ применяются." }

    $sourceRoot = Resolve-SourceRoot
    . (Join-Path $sourceRoot "lib/common.ps1")

    if (-not (Test-SkillFrontmatter (Join-Path $sourceRoot "skill/SKILL.md"))) {
        Stop-WithError "SKILL.md в источнике невалиден — установка прервана." 2
    }

    $targets = @()
    switch ($Target) {
        "auto" {
            $targets = Get-AutoTargets
            if ($targets.Count -eq 0) {
                Write-Warn "Авто-определение: не найдено ни одного CLI."
                Write-Warn "Укажите цель явно: -Target claude|codex|opencode|all"
                exit 4
            }
            Write-Info "Авто-определены цели: $($targets -join ', ')"
        }
        "all" { $targets = @("claude", "codex", "opencode") }
        default { $targets = @($Target) }
    }

    $rc = 0
    foreach ($t in $targets) {
        if (-not (Invoke-OneTarget -TargetName $t -SourceRoot $sourceRoot)) { $rc = 5 }
    }

    if ($rc -eq 0) {
        if ($script:DoUninstall) { Write-Ok "Удаление завершено." }
        else { Write-Ok "Установка завершена. Skill: $($script:SkillName) v$($script:SkillVersion)" }
    } else {
        Write-ErrorMessage "Некоторые цели завершились с ошибкой."
    }
    exit $rc
}
finally {
    if ($script:TmpRoot -and (Test-Path $script:TmpRoot)) {
        Remove-Item $script:TmpRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
