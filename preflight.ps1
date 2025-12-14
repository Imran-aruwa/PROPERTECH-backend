Write-Host "=== PROPERTECH Backend Preflight ===`n"

# 1) Python version
Write-Host "[1/3] Python version:"
python --version
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Python not available." -ForegroundColor Red
    exit 1
}

# 2) Import FastAPI app
Write-Host "`n[2/3] Importing FastAPI app..."
python -c "from app.main import app; print('OK: app imported, routes:', len(app.routes))"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to import app.main:app" -ForegroundColor Red
    exit 1
}

# 3) Test DB connection
Write-Host "`n[3/3] Testing database connection..."
python -c "from app.database import test_connection; print('DB test:', 'OK' if test_connection() else 'FAILED')"
if ($LASTEXITCODE -ne 0) {
    Write-Host 'ERROR: Database test raised an exception.' -ForegroundColor Red
    exit 1
}

Write-Host "`n=== Preflight finished. If no errors above, you are safe to commit & push. ==="
