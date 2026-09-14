# Reproducible demo of codebase-index on a real public repository (Flask).
#
#   pwsh examples/demo/run_demo.ps1                  # clones Flask into .\.tmp-demo
#   pwsh examples/demo/run_demo.ps1 C:\src\flask     # use an existing checkout
#
# Mirrors run_demo.sh. Nothing leaves the machine.
param([string]$WorkDir = ".tmp-demo\flask")
$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/pallets/flask.git"
$RepoSha = "d318b683471101618febed18996405ad26462110"
$env:CBX_NO_SKILL_AUTO_UPDATE = "1"

function Step { param([Parameter(ValueFromRemainingArguments)] [string[]]$Cmd)
    Write-Host "`n$ $($Cmd -join ' ')" -ForegroundColor Blue
    & $Cmd[0] @($Cmd[1..($Cmd.Length - 1)])
    if ($LASTEXITCODE -ne 0) { throw "command failed: $($Cmd -join ' ')" }
}

if (-not (Get-Command codebase-index -ErrorAction SilentlyContinue)) {
    Write-Error "codebase-index is not on PATH. Install it first:  pip install codebase-index"
}
if (-not (Test-Path (Join-Path $WorkDir ".git"))) {
    Write-Host "Cloning Flask into $WorkDir ..."
    git clone --quiet $RepoUrl $WorkDir
}
git -C $WorkDir checkout --quiet $RepoSha
Set-Location $WorkDir

Step codebase-index index
Step codebase-index search "where is the session cookie signed and saved" --limit 5
Step codebase-index refs open_session
Step codebase-index path wsgi_app dispatch_request
Step codebase-index impact SecureCookieSessionInterface --direction up --depth 2

$sessions = "src/flask/sessions.py"
(Get-Content $sessions -Raw) -replace "(?m)^    def open_session\(", "    def open_session(  # demo edit" |
    Set-Content $sessions -NoNewline -Encoding utf8
Step codebase-index diff-impact
git checkout --quiet -- $sessions

Step codebase-index --json search "where is the session cookie signed and saved" --limit 3
Write-Host "`nDone. Index lives in $WorkDir\.claude\cache\codebase-index\ and nothing was sent anywhere."
