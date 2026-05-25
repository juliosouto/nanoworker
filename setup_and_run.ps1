$ErrorActionPreference = "Stop"

Write-Host "Starting NanoWorker Windows Setup..." -ForegroundColor Cyan

# 1. System Dependencies via Winget
Write-Host "`n[1/5] Checking system dependencies..." -ForegroundColor Yellow

if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "Winget found. Installing/Updating dependencies..."
    
    # Python 3.13
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Host "Python not found. Installing Python 3.13..."
        winget install -e --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    } else {
        Write-Host "Python is already installed."
    }

    # Node.js
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Write-Host "Node.js not found. Installing Node.js..."
        winget install -e --id OpenJS.NodeJS --accept-source-agreements --accept-package-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    } else {
        Write-Host "Node.js is already installed."
    }

    # FFmpeg
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
        Write-Host "FFmpeg not found. Installing FFmpeg..."
        winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    } else {
        Write-Host "FFmpeg is already installed."
    }

} else {
    Write-Host "Winget not found! Please install Node.js, Python 3.13, and FFmpeg manually before continuing." -ForegroundColor Red
}

# 2. Python Environment
Write-Host "`n[2/5] Setting up Python Virtual Environment..." -ForegroundColor Yellow
if (-not (Test-Path ".venv")) {
    Write-Host "Creating .venv..."
    python -m venv .venv
}
Write-Host "Activating .venv..."
$env:VIRTUAL_ENV = "$PWD\.venv"
$env:Path = "$PWD\.venv\Scripts;$env:Path"

# 3. Python Dependencies
Write-Host "`n[3/5] Installing Python dependencies..." -ForegroundColor Yellow
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install

# 4. Node.js Dependencies
Write-Host "`n[4/5] Installing Node.js bridge dependencies..." -ForegroundColor Yellow
if (Test-Path "node_scripts") {
    Set-Location "node_scripts"
    npm install
    Set-Location ..
} else {
    Write-Host "Directory 'node_scripts' not found! Make sure you are in the project root." -ForegroundColor Red
    exit 1
}

# 5. Environment Variables
Write-Host "`n[5/5] Checking Environment Variables..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    Write-Host "Creating empty .env file..."
    New-Item -ItemType File -Name ".env" -Force | Out-Null
}

# 6. Run Application
Write-Host "`n[SUCCESS] Setup complete! Starting NanoWorker..." -ForegroundColor Green
python app.py
