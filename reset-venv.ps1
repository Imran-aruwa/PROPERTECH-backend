# Virtual Environment Reset Script
# Deactivate, clean up, and reinstall all dependencies

Write-Host "====================================" -ForegroundColor Cyan
Write-Host "VIRTUAL ENVIRONMENT RESET" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Deactivate current environment
Write-Host "[1/5] Deactivating current environment..." -ForegroundColor Yellow
deactivate 2>$null
Start-Sleep -Seconds 1

# Step 2: Remove venv folder
Write-Host "[2/5] Removing old venv folder..." -ForegroundColor Yellow
if (Test-Path "venv") {
    Remove-Item -Recurse -Force "venv" -ErrorAction SilentlyContinue
    Write-Host "  OK venv folder deleted" -ForegroundColor Green
} else {
    Write-Host "  INFO venv folder not found" -ForegroundColor Gray
}

# Step 3: Clear pip cache
Write-Host "[3/5] Clearing pip cache..." -ForegroundColor Yellow
python -m pip cache purge
Write-Host "  OK Cache cleared" -ForegroundColor Green

# Step 4: Create new venv
Write-Host "[4/5] Creating new virtual environment..." -ForegroundColor Yellow
python -m venv venv
Write-Host "  OK New venv created" -ForegroundColor Green

# Step 5: Activate venv and install dependencies
Write-Host "[5/5] Activating venv and installing dependencies..." -ForegroundColor Yellow
& ".\venv\Scripts\Activate.ps1"
Write-Host "  OK venv activated" -ForegroundColor Green

Write-Host ""
Write-Host "Installing packages (this may take a few minutes)..." -ForegroundColor Cyan
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt --no-cache-dir

Write-Host ""
Write-Host "====================================" -ForegroundColor Green
Write-Host "DONE Environment is ready" -ForegroundColor Green
Write-Host "====================================" -ForegroundColor Green
Write-Host ""
Write-Host "To verify, run:" -ForegroundColor Cyan
Write-Host "  python --version" -ForegroundColor White
Write-Host "  pip list" -ForegroundColor White
Write-Host ""
Write-Host "To start backend run:" -ForegroundColor Cyan
Write-Host "  python -m uvicorn app.main:app --reload --port 8000" -ForegroundColor White