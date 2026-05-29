# Windows alias for cbx.ps1 (see bin/codebase-index).
param(
    [Parameter(Mandatory = $true, Position = 0)] [string]$Subcommand,
    [Parameter(ValueFromRemainingArguments = $true)] [string[]]$Rest
)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $here "cbx.ps1") $Subcommand @Rest
exit $LASTEXITCODE
