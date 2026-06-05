# Windows plugin wrapper around the venv-provisioned codebase-index CLI.
# Mirrors bin/cbx: whitelists subcommands, resolves the venv via the .venv-path pointer.
param(
    [Parameter(Mandatory = $true, Position = 0)] [string]$Subcommand,
    [Parameter(ValueFromRemainingArguments = $true)] [string[]]$Rest
)
$ErrorActionPreference = "Stop"
$allowed = @("search", "explain", "symbol", "refs", "impact", "graph", "stats", "update", "index")
if ($allowed -notcontains $Subcommand) {
    Write-Error "cbx: refusing subcommand '$Subcommand'. Allowed: $($allowed -join ', ')"
    exit 2
}

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pointer = Join-Path $here "..\.venv-path"
$venv = if (Test-Path $pointer) { (Get-Content $pointer -Raw).Trim() } else { "" }

if ($venv) {
    $winCli = Join-Path $venv "Scripts\codebase-index.exe"
    $nixCli = Join-Path $venv "bin\codebase-index"
    if (Test-Path $winCli) { & $winCli $Subcommand @Rest; exit $LASTEXITCODE }
    if (Test-Path $nixCli) { & $nixCli $Subcommand @Rest; exit $LASTEXITCODE }
}
$bin = Get-Command codebase-index -ErrorAction SilentlyContinue
if ($bin) { & $bin.Source $Subcommand @Rest; exit $LASTEXITCODE }
& python -m codebase_index $Subcommand @Rest
exit $LASTEXITCODE
