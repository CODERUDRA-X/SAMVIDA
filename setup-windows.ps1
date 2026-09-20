$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "== SAMVIDA Windows setup ==" -ForegroundColor Cyan

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    throw "Python was not found on PATH. Install Python 3.11, 3.12, 3.13, or 3.14 and reopen PowerShell."
}

$pythonVersion = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')").Trim()
$parts = $pythonVersion.Split('.')
$major = [int]$parts[0]
$minor = [int]$parts[1]
if ($major -ne 3 -or $minor -lt 11 -or $minor -gt 14) {
    throw "Unsupported Python version $pythonVersion. SAMVIDA supports Python 3.11 through 3.14."
}
Write-Host "Python $pythonVersion detected." -ForegroundColor Green

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    throw "Node.js was not found on PATH. Install Node.js 22.12+ and reopen PowerShell."
}

$nodeVersion = (& node -p "process.versions.node").Trim()
$nodeMajor = [int]((& node -p "process.versions.node.split('.')[0]").Trim())
$nodeMinor = [int]((& node -p "process.versions.node.split('.')[1]").Trim())
if (($nodeMajor -lt 22) -or ($nodeMajor -eq 22 -and $nodeMinor -lt 12)) {
    throw "Unsupported Node.js version $nodeVersion. SAMVIDA needs Node.js 22.12+ for the current Vite toolchain."
}
Write-Host "Node.js $nodeVersion detected." -ForegroundColor Green

$venvPython = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating backend virtual environment..." -ForegroundColor Yellow
    & python -m venv (Join-Path $root 'backend\.venv')
}

Write-Host "Installing backend dependencies..." -ForegroundColor Yellow
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $root 'backend\requirements.txt')

Write-Host "Installing frontend dependencies..." -ForegroundColor Yellow
Push-Location (Join-Path $root 'frontend')
try {
    & npm install
} finally {
    Pop-Location
}

Write-Host "" 
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Backend:  .\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000" -ForegroundColor Cyan
Write-Host "Frontend: cd frontend; npm run dev" -ForegroundColor Cyan
