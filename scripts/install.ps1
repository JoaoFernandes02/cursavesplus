# One-click install: uv + cursaves + desktop shortcut + launch GUI
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$GitHubUrl = "git+https://github.com/Callum-Ward/cursaves.git"

Write-Host "cursaves installer"
Write-Host "=================="

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
    Write-Error "Python 3.10+ is required. Install from https://www.python.org/downloads/"
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "git is required. Install from https://git-scm.com/downloads"
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "uv is not installed."
    $reply = Read-Host "Install uv now with the official script? [Y/n]"
    if ($reply -match '^[nN]') { throw "Cannot continue without uv." }
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $uvBin = Join-Path $env:USERPROFILE ".local\bin"
    if (Test-Path $uvBin) { $env:PATH = "$uvBin;$env:PATH" }
}

Write-Host "uv: $(uv --version)"

$installTarget = $Root
if (-not (Test-Path (Join-Path $Root "pyproject.toml"))) {
    $installTarget = $GitHubUrl
    Write-Host "Installing from GitHub..."
} else {
    Write-Host "Installing from local repo: $Root"
}

uv tool install --force $installTarget

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
    Write-Error "cursaves not found. Run 'uv tool update-shell', restart terminal, then run 'cursaves'."
}

Write-Host ""
Write-Host "Creating desktop shortcut..."
$desktop = Join-Path $env:USERPROFILE "Desktop"
$shortcutPath = Join-Path $desktop "Cursaves.lnk"
$cursavesExe = if ($cursaves -eq "cursaves") { (Get-Command cursaves).Source } else { $cursaves }
$psShortcut = @"
`$WshShell = New-Object -ComObject WScript.Shell
`$Shortcut = `$WshShell.CreateShortcut('$shortcutPath')
`$Shortcut.TargetPath = '$cursavesExe'
`$Shortcut.WorkingDirectory = '$(Split-Path $cursavesExe)'
`$Shortcut.Description = 'Cursaves - sync Cursor chats'
`$Shortcut.Save()
"@
powershell -NoProfile -ExecutionPolicy Bypass -Command $psShortcut

Write-Host ""
Write-Host "Launching cursaves..."
Start-Process $cursaves
Write-Host ""
Write-Host "Done. cursaves GUI should be opening."
Write-Host "You can also run 'cursaves' anytime or use the Desktop shortcut."
