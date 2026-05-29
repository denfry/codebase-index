<#
.SYNOPSIS
  Smoke-сценарий для install.ps1.
.DESCRIPTION
  Проверяет dry-run для всех целей, реальную установку в temp-директорию,
  наличие SKILL.md и install_manifest.json, затем uninstall.
  Запуск из корня репозитория:  pwsh tests/installer/smoke.ps1
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $here "../..")).Path
$install = Join-Path $root "install.ps1"

$script:Pass = 0; $script:Fail = 0
function Pass { param($m) $script:Pass++; Write-Host "  [PASS] $m" -ForegroundColor Green }
function Fail { param($m) $script:Fail++; Write-Host "  [FAIL] $m" -ForegroundColor Red }

function Run { param([string[]]$PassArgs)
    # ВАЖНО: параметр НЕ называть $Args — это автоматическая переменная PowerShell,
    # и splat @Args передал бы пустой массив (баг: nested-вызов терял все флаги).
    & pwsh -NoProfile -File $install @PassArgs *> $null
    return $LASTEXITCODE
}

Write-Host "== 1. dry-run для всех целей =="
foreach ($t in @("auto","claude","codex","opencode")) {
    $rc = Run @("-Target", $t, "-DryRun", "-NoPythonBootstrap")
    if ($rc -eq 0) { Pass "dry-run -Target $t" }
    elseif ($t -eq "auto" -and $rc -eq 4) { Pass "dry-run -Target auto (нет CLI — ожидаемо)" }
    else { Fail "dry-run -Target $t (rc=$rc)" }
}

Write-Host "== 2. установка claude в temp install-dir =="
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("cbx-smoke-" + [System.Guid]::NewGuid().ToString("N").Substring(0,8))
$skillDir = Join-Path $tmp "skills/codebase-index"
try {
    $rc = Run @("-Target","claude","-InstallDir",$skillDir,"-NoPythonBootstrap","-Force")
    if ($rc -eq 0) { Pass "установка claude в $skillDir" } else { Fail "установка claude (rc=$rc)" }

    Write-Host "== 3. проверка артефактов =="
    if (Test-Path (Join-Path $skillDir "SKILL.md")) { Pass "SKILL.md существует" } else { Fail "SKILL.md отсутствует" }
    $mf = Join-Path $skillDir "install_manifest.json"
    if (Test-Path $mf) {
        Pass "install_manifest.json существует"
        $json = Get-Content $mf -Raw | ConvertFrom-Json
        if ($json.skill_name) { Pass "manifest содержит skill_name" } else { Fail "manifest без skill_name" }
        if ($json.target -eq "claude") { Pass "manifest target=claude" } else { Fail "manifest target неверный" }
    } else { Fail "manifest отсутствует" }

    Write-Host "== 4. uninstall =="
    $rc = Run @("-Target","claude","-InstallDir",$skillDir,"-Uninstall")
    if ($rc -eq 0) { Pass "uninstall выполнен" } else { Fail "uninstall (rc=$rc)" }
    if (Test-Path (Join-Path $skillDir "SKILL.md")) { Fail "SKILL.md не удалён" } else { Pass "SKILL.md удалён" }
}
finally {
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
}

Write-Host ""
Write-Host "ИТОГО: PASS=$($script:Pass) FAIL=$($script:Fail)"
if ($script:Fail -ne 0) { exit 1 }
