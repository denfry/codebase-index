# SessionStart bootstrap (Windows) for the codebase-index plugin. Mirrors bootstrap.sh.
$ErrorActionPreference = "Stop"
$root = $env:CLAUDE_PLUGIN_ROOT
$data = $env:CLAUDE_PLUGIN_DATA
if (-not $root -or -not $data) { Write-Error "CLAUDE_PLUGIN_ROOT/DATA not set"; exit 0 }

$venv = Join-Path $data "venv"
$lockSrc = Join-Path $root "requirements.lock"
$lockDst = Join-Path $data "requirements.lock"

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
    Write-Error "codebase-index: Python 3.11+ was not found on PATH. Install Python, then restart Claude Code."
    exit 0
}

try {
    $useUv = ($env:CBX_NO_UV -ne "1") -and (Get-Command uv -ErrorAction SilentlyContinue)
    if ($useUv) {
        & uv venv $venv
        if ($env:CBX_INSTALL_SPEC) {
            & uv pip install --python (Join-Path $venv "Scripts\python.exe") $env:CBX_INSTALL_SPEC
        } else {
            & uv pip install --python (Join-Path $venv "Scripts\python.exe") -r $lockSrc
        }
    } else {
        & $py.Source -m venv $venv
        & (Join-Path $venv "Scripts\python.exe") -m pip install --upgrade pip
        if ($env:CBX_INSTALL_SPEC) {
            & (Join-Path $venv "Scripts\python.exe") -m pip install $env:CBX_INSTALL_SPEC
        } else {
            & (Join-Path $venv "Scripts\python.exe") -m pip install -r $lockSrc
        }
    }
    Copy-Item $lockSrc $lockDst -Force
} catch {
    Remove-Item $lockDst -ErrorAction SilentlyContinue
    Write-Error "codebase-index: bootstrap install failed; will retry next session."
    exit 0
}
