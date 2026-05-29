# SessionStart bootstrap (Windows) for the codebase-index plugin. Mirrors bootstrap.sh.
$ErrorActionPreference = "Stop"
$root = $env:CLAUDE_PLUGIN_ROOT
$data = $env:CLAUDE_PLUGIN_DATA
if (-not $root -or -not $data) { Write-Error "CLAUDE_PLUGIN_ROOT/DATA not set"; exit 0 }

$venv = Join-Path $data "venv"
$lockSrc = Join-Path $root "requirements.lock"
$lockDst = Join-Path $data "requirements.lock"
$spec = if ($env:CBX_INSTALL_SPEC) { $env:CBX_INSTALL_SPEC } else { "codebase-index==0.1.0" }

New-Item -ItemType Directory -Force -Path $data | Out-Null
Set-Content -Path (Join-Path $root ".venv-path") -Value $venv

$cli = Join-Path $venv "Scripts\codebase-index.exe"
if ((Test-Path $cli) -and (Test-Path $lockDst) -and
    ((Get-Content $lockSrc -Raw) -eq (Get-Content $lockDst -Raw))) {
    exit 0
}

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) {
    Write-Error "codebase-index: Python 3.10+ was not found on PATH. Install Python, then restart Claude Code."
    exit 0
}

try {
    $useUv = ($env:CBX_NO_UV -ne "1") -and (Get-Command uv -ErrorAction SilentlyContinue)
    if ($useUv) {
        & uv venv $venv
        & uv pip install --python (Join-Path $venv "Scripts\python.exe") $spec
    } else {
        & $py.Source -m venv $venv
        & (Join-Path $venv "Scripts\python.exe") -m pip install --upgrade pip
        & (Join-Path $venv "Scripts\python.exe") -m pip install $spec
    }
    Copy-Item $lockSrc $lockDst -Force
} catch {
    Remove-Item $lockDst -ErrorAction SilentlyContinue
    Write-Error "codebase-index: bootstrap install failed; will retry next session."
    exit 0
}
