# Windows PowerShell wrapper around the installed `codebase-index` CLI.
# Mirrors scripts/cbx: whitelists safe subcommands, falls back to `python -m codebase_index`.
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Subcommand,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"
$allowed = @("search", "explain", "symbol", "refs", "impact", "graph", "stats", "update", "index")

if ($allowed -notcontains $Subcommand) {
    Write-Error "cbx: refusing subcommand '$Subcommand'. Allowed: $($allowed -join ', ')"
    exit 2
}

& python -c "import codebase_index" 2>$null
if ($LASTEXITCODE -eq 0) {
    & python -m codebase_index $Subcommand @Rest
    exit $LASTEXITCODE
}
$bin = Get-Command codebase-index -ErrorAction SilentlyContinue
if ($bin) { & $bin.Source $Subcommand @Rest }
exit $LASTEXITCODE
