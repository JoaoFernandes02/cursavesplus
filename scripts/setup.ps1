# Bootstrap script: install uv + cursaves from this repo, then run interactive setup.
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "cursaves setup (bootstrap)"
Write-Host "================================"

function Find-Python {
    foreach ($cmd in @("py -3", "python3", "python")) {
        $parts = $cmd -split " "
        $exe = $parts[0]
        $args = @()
        if ($parts.Length -gt 1) { $args = $parts[1..($parts.Length - 1)] }
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        & $exe @args -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return $cmd }
    }
    return $null
}

$pythonCmd = Find-Python
if (-not $pythonCmd) {
    Write-Error "Python 3.10+ is required but was not found. Install from https://www.python.org/downloads/"
}
if ($pythonCmd -eq "py -3") {
    Write-Host "Python: $(py -3 --version)"
} elseif ($pythonCmd -eq "python3") {
    Write-Host "Python: $(python3 --version)"
} else {
    Write-Host "Python: $(python --version)"
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "git is required but not found. Install from https://git-scm.com/downloads"
}
Write-Host "Git: $(git --version)"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "GitHub CLI (gh) is not installed — needed for Login with GitHub."
    Write-Host "Install with: winget install GitHub.cli"
    Write-Host "You can still use manual git/SSH setup without gh."
    Write-Host ""
} else {
    Write-Host "GitHub CLI: $(gh --version)"
}

function Install-Uv {
    Write-Host ""
    Write-Host "uv is not installed."
    Write-Host "Install options:"
    Write-Host "  winget install astral-sh.uv"
    Write-Host "  powershell -ExecutionPolicy ByPass -c `"irm https://astral.sh/uv/install.ps1 | iex`""
    Write-Host ""
    $reply = Read-Host "Install uv now with the official script? [y/N]"
    if ($reply -match '^[yY]') {
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        $uvBin = Join-Path $env:USERPROFILE ".local\bin"
        if (Test-Path $uvBin) {
            $env:PATH = "$uvBin;$env:PATH"
        }
    } else {
        throw "Cannot continue without uv."
    }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Install-Uv
}
Write-Host "uv: $(uv --version)"

Write-Host ""
Write-Host "Installing cursaves from $Root ..."
uv tool install --force $Root

$cursaves = $null
if (Get-Command cursaves -ErrorAction SilentlyContinue) {
    $cursaves = "cursaves"
} else {
    $localBin = Join-Path $env:USERPROFILE ".local\bin\cursaves.exe"
    if (Test-Path $localBin) {
        $cursaves = $localBin
        $env:PATH = "$(Split-Path $localBin);$env:PATH"
    }
}

if (-not $cursaves) {
    Write-Error "cursaves not found on PATH. Run 'uv tool update-shell', restart the terminal, then run 'cursaves'."
}

Write-Host ""
Write-Host "Running: $cursaves setup $($args -join ' ')"
& $cursaves setup @args
$code = $LASTEXITCODE
Write-Host ""
Write-Host "Setup finished. Run 'cursaves' to open the app."
exit $code
