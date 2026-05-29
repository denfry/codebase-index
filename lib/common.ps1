# lib/common.ps1 — общие функции для PowerShell-инсталлятора codebase-index.
#
# Подключается через dot-sourcing (`. lib/common.ps1`) из install.ps1 и адаптеров.
# Работает в Windows PowerShell 5.1 и PowerShell 7+ (Core) на Windows/macOS/Linux.
#
# Идентификаторы и функции — на английском; комментарии — на русском.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# --------------------------------------------------------------------------
# Логирование (INFO / WARN / ERROR / OK)
# --------------------------------------------------------------------------
function Write-Info  { param([string]$Message) Write-Host "[INFO]  $Message"  -ForegroundColor Cyan }
function Write-Warn  { param([string]$Message) Write-Host "[WARN]  $Message"  -ForegroundColor Yellow }
function Write-ErrorMessage { param([string]$Message) Write-Host "[ERROR] $Message" -ForegroundColor Red }
function Write-Ok    { param([string]$Message) Write-Host "[OK]    $Message"  -ForegroundColor Green }
function Write-Debug2 { param([string]$Message) if ($script:Verbose) { Write-Host "[DEBUG] $Message" -ForegroundColor DarkGray } }

function Stop-WithError {
    param([string]$Message, [int]$Code = 1)
    Write-ErrorMessage $Message
    exit $Code
}

# --------------------------------------------------------------------------
# Проверка наличия команд и ОС
# --------------------------------------------------------------------------
function Test-Command {
    param([string]$Name)
    $null = Get-Command $Name -ErrorAction SilentlyContinue
    return $?
}

# Возвращает: windows | macos | linux | unknown
function Get-OSName {
    if ($IsWindows -or ($env:OS -eq "Windows_NT")) { return "windows" }
    if ($IsMacOS) { return "macos" }
    if ($IsLinux) { return "linux" }
    return "unknown"
}

# --------------------------------------------------------------------------
# Безопасность путей
# --------------------------------------------------------------------------
function Expand-HomePath {
    param([string]$Path)
    if ($Path -eq "~") { return $HOME }
    if ($Path.StartsWith("~/") -or $Path.StartsWith("~\")) {
        return (Join-Path $HOME $Path.Substring(2))
    }
    return $Path
}

# Запрет path traversal.
function Assert-NoTraversal {
    param([string]$Path)
    if ($Path -match '(^|[\\/])\.\.([\\/]|$)') {
        Stop-WithError "Небезопасный путь (path traversal запрещён): $Path" 2
    }
}

# Проверка, что target лежит внутри base.
function Test-PathWithin {
    param([string]$Base, [string]$Target)
    try {
        $b = [System.IO.Path]::GetFullPath($Base).TrimEnd('\','/')
        $t = [System.IO.Path]::GetFullPath($Target)
        return $t.StartsWith($b, [System.StringComparison]::OrdinalIgnoreCase)
    } catch { return $false }
}

# --------------------------------------------------------------------------
# Скачивание и безопасная распаковка архива
# --------------------------------------------------------------------------
function Invoke-DownloadArchive {
    param([string]$RepoUrl, [string]$Branch, [string]$OutFile)
    $repo = $RepoUrl.TrimEnd('/')
    if ($repo.EndsWith(".git")) { $repo = $repo.Substring(0, $repo.Length - 4) }
    $url = "$repo/archive/refs/heads/$Branch.zip"
    Write-Info "Источник (скачиваем архив): $url"
    Invoke-WebRequest -Uri $url -OutFile $OutFile -UseBasicParsing
    if (-not (Test-Path $OutFile) -or (Get-Item $OutFile).Length -eq 0) {
        Stop-WithError "Скачанный архив пуст: $url" 3
    }
}

function Expand-ArchiveSafe {
    param([string]$Archive, [string]$Destination)
    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
    # Проверяем записи на traversal до распаковки.
    $zip = [System.IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        foreach ($entry in $zip.Entries) {
            if ($entry.FullName -match '(^|/)\.\.(/|$)' -or $entry.FullName.StartsWith('/')) {
                Stop-WithError "Архив содержит небезопасные пути (traversal). Отказ." 2
            }
        }
    } finally { $zip.Dispose() }
    if (Test-Path $Destination) { Remove-Item $Destination -Recurse -Force }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Expand-Archive -Path $Archive -DestinationPath $Destination -Force
}

# Находит корень распакованного архива (содержащий skill/).
function Find-ExtractedRoot {
    param([string]$Destination)
    $dirs = Get-ChildItem -Path $Destination -Directory
    foreach ($d in $dirs) {
        if (Test-Path (Join-Path $d.FullName "skill")) { return $d.FullName }
    }
    if ($dirs.Count -ge 1) { return $dirs[0].FullName }
    return $Destination
}

# --------------------------------------------------------------------------
# Валидация SKILL.md (YAML frontmatter)
# --------------------------------------------------------------------------
function Test-SkillFrontmatter {
    param([string]$Path)
    if (-not (Test-Path $Path)) { Write-ErrorMessage "SKILL.md не найден: $Path"; return $false }
    $lines = Get-Content -Path $Path
    if ($lines.Count -lt 3 -or $lines[0].Trim() -ne "---") {
        Write-ErrorMessage "SKILL.md: нет открывающего frontmatter (---)"; return $false
    }
    $closeIdx = -1
    for ($i = 1; $i -lt $lines.Count; $i++) {
        if ($lines[$i].Trim() -eq "---") { $closeIdx = $i; break }
    }
    if ($closeIdx -lt 0) { Write-ErrorMessage "SKILL.md: нет закрывающего frontmatter"; return $false }
    $fm = $lines[1..($closeIdx - 1)]
    if (-not ($fm -match '^\s*name:\s*\S')) { Write-ErrorMessage "SKILL.md: нет поля name"; return $false }
    if (-not ($fm -match '^\s*description:\s*\S')) { Write-ErrorMessage "SKILL.md: нет поля description"; return $false }
    return $true
}

function Get-SkillField {
    param([string]$Path, [string]$Key)
    foreach ($line in (Get-Content -Path $Path)) {
        if ($line -match "^\s*$([regex]::Escape($Key)):\s*(.+)$") {
            return $Matches[1].Trim().Trim('"')
        }
        if ($line.Trim() -eq "---" -and $line -ne (Get-Content $Path)[0]) { break }
    }
    return ""
}

# --------------------------------------------------------------------------
# Резервные копии
# --------------------------------------------------------------------------
function Backup-Path {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    if ($script:DryRun) { Write-Info "[dry-run] создал бы backup: $Path"; return $null }
    $ts = Get-Date -Format "yyyyMMdd-HHmmss"
    $bak = "$Path.bak-$ts"
    if (Test-Path $bak) { $bak = "$bak.$PID" }
    Copy-Item -Path $Path -Destination $bak -Recurse -Force
    Write-Info "Создан backup: $bak"
    return $bak
}

# --------------------------------------------------------------------------
# Managed block (AGENTS.md и подобные)
# --------------------------------------------------------------------------
$script:ManagedBegin = "<!-- BEGIN MANAGED SKILL BLOCK: codebase-index -->"
$script:ManagedEnd   = "<!-- END MANAGED SKILL BLOCK: codebase-index -->"

function Update-ManagedBlock {
    param([string]$File, [string]$Content)
    if ($script:DryRun) { Write-Info "[dry-run] обновил бы managed block в: $File"; return }
    $dir = Split-Path -Parent $File
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

    $existing = ""
    if (Test-Path $File) {
        Backup-Path $File | Out-Null
        $existing = Get-Content -Path $File -Raw
        # Удаляем старый блок целиком.
        $pattern = [regex]::Escape($script:ManagedBegin) + "[\s\S]*?" + [regex]::Escape($script:ManagedEnd)
        $existing = [regex]::Replace($existing, $pattern, "").TrimEnd()
    }
    $block = "$($script:ManagedBegin)`n$Content`n$($script:ManagedEnd)`n"
    $out = if ($existing) { "$existing`n`n$block" } else { $block }
    Set-Content -Path $File -Value $out -Encoding UTF8 -NoNewline
    Write-Ok "Managed block записан в: $File"
}

function Remove-ManagedBlock {
    param([string]$File)
    if (-not (Test-Path $File)) { return }
    if ($script:DryRun) { Write-Info "[dry-run] удалил бы managed block из: $File"; return }
    $raw = Get-Content -Path $File -Raw
    if ($raw -notmatch [regex]::Escape($script:ManagedBegin)) { return }
    Backup-Path $File | Out-Null
    $pattern = "\s*" + [regex]::Escape($script:ManagedBegin) + "[\s\S]*?" + [regex]::Escape($script:ManagedEnd)
    $out = [regex]::Replace($raw, $pattern, "").TrimEnd() + "`n"
    Set-Content -Path $File -Value $out -Encoding UTF8 -NoNewline
    Write-Ok "Managed block удалён из: $File"
}

# --------------------------------------------------------------------------
# Копирование дерева с записью списка установленных файлов
# --------------------------------------------------------------------------
function Copy-Tree {
    param([string]$Source, [string]$Destination, [System.Collections.ArrayList]$FileList)
    if ($script:DryRun) { Write-Info "[dry-run] скопировал бы: $Source -> $Destination"; return }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $srcFull = (Resolve-Path $Source).Path
    Get-ChildItem -Path $Source -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($srcFull.Length).TrimStart('\','/')
        $to = Join-Path $Destination $rel
        $toDir = Split-Path -Parent $to
        if (-not (Test-Path $toDir)) { New-Item -ItemType Directory -Path $toDir -Force | Out-Null }
        Copy-Item -Path $_.FullName -Destination $to -Force
        if ($FileList -ne $null) { [void]$FileList.Add($to) }
    }
    Write-Ok "Скопировано: $Source -> $Destination"
}

# --------------------------------------------------------------------------
# Манифест установки
# --------------------------------------------------------------------------
function Write-Manifest {
    param(
        [string]$ManifestPath, [string]$Target, [string]$PythonVersion,
        [string]$BootstrapStatus, [System.Collections.ArrayList]$InstalledFiles
    )
    if ($script:DryRun) { Write-Info "[dry-run] записал бы manifest: $ManifestPath"; return }
    $manifest = [ordered]@{
        skill_name       = $script:SkillName
        version          = $script:SkillVersion
        installed_at     = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        target           = $Target
        os               = (Get-OSName)
        source_repo      = $script:RepoUrl
        branch           = $script:Branch
        installed_files  = @($InstalledFiles)
        python_version   = $PythonVersion
        bootstrap_status = $BootstrapStatus
    }
    $dir = Split-Path -Parent $ManifestPath
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -Path $ManifestPath -Encoding UTF8
    Write-Ok "Manifest записан: $ManifestPath"
}

function Remove-FromManifest {
    param([string]$ManifestPath)
    if (-not (Test-Path $ManifestPath)) { Write-Warn "Manifest не найден: $ManifestPath"; return }
    Write-Info "Читаю manifest: $ManifestPath"
    $data = Get-Content -Path $ManifestPath -Raw | ConvertFrom-Json
    foreach ($f in @($data.installed_files)) {
        if ($script:DryRun) { Write-Info "[dry-run] удалил бы: $f" }
        elseif (Test-Path $f) { Remove-Item $f -Force; Write-Ok "Удалён: $f" }
    }
    if (-not $script:DryRun) { Remove-Item $ManifestPath -Force; Write-Ok "Удалён manifest: $ManifestPath" }
}

# --------------------------------------------------------------------------
# Python runtime / bootstrap
# --------------------------------------------------------------------------
function Find-Python {
    foreach ($cand in @("py", "python", "python3")) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        # Пропускаем Windows Store «App execution alias» (WindowsApps) — его
        # stub блокирует выполнение и установка зависает. Реальный Python — нет.
        $src = ""
        try { $src = [string]$cmd.Source } catch { $src = "" }
        if ($src -and $src -match 'WindowsApps') { continue }
        try {
            $pyArgs = if ($cand -eq "py") { @("-3") } else { @() }
            & $cand @pyArgs -c "import sys; raise SystemExit(0 if sys.version_info[:2]>=(3,9) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return $cand }
        } catch { }
    }
    return $null
}

function Get-PythonVersion {
    param([string]$PyCmd)
    try {
        $args = if ($PyCmd -eq "py") { @("-3") } else { @() }
        return (& $PyCmd @args -c "import sys;print('%d.%d.%d'%sys.version_info[:3])" 2>$null)
    } catch { return "unknown" }
}

# Возвращает строку статуса: ok | skipped | no-python | failed
function Invoke-PythonBootstrap {
    param([string]$ResourceDir, [string]$ManifestPath, [string]$Target)
    if ($script:NoPythonBootstrap) { Write-Info "Python bootstrap пропущен (-NoPythonBootstrap)"; return "skipped" }
    $py = Find-Python
    if (-not $py) {
        Write-Warn "Python 3.9+ не найден на PATH."
        Write-Warn "Установите Python (https://www.python.org/downloads/) и перезапустите."
        return "no-python"
    }
    Write-Info "Python найден: $py ($(Get-PythonVersion $py))"
    if ($script:DryRun) { Write-Info "[dry-run] создал бы venv и запустил bootstrap.py в: $ResourceDir"; return "skipped" }
    $script = Join-Path $ResourceDir "scripts/bootstrap.py"
    if (-not (Test-Path $script)) { Write-Debug2 "bootstrap.py не найден — пропуск."; return "skipped" }
    Write-Info "Запуск bootstrap.py …"
    try {
        $args = if ($py -eq "py") { @("-3") } else { @() }
        & $py @args $script --skill-dir $ResourceDir --manifest $ManifestPath --target $Target
        if ($LASTEXITCODE -eq 0) { return "ok" } else { Write-Warn "bootstrap.py вернул код $LASTEXITCODE"; return "failed" }
    } catch {
        Write-Warn "bootstrap.py завершился с ошибкой: $_"
        return "failed"
    }
}
