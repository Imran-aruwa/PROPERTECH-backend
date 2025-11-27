# PROPERTECH Backend - Collect App Files for Review
# This script gathers all your app files so you can share them

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "PROPERTECH Backend File Collector" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# Define paths to check
$filesToCheck = @(
    "app/main.py",
    "app/config.py",
    "app/database.py",
    "app/models/payment.py",
    "app/models/user.py",
    "app/services/payment_gateways.py",
    "app/services/currency_detector.py",
    "app/schemas/payment.py",
    "app/api/payments.py",
    "app/api/webhooks.py",
    "app/api/auth.py",
    "app/api/properties.py",
    "app/core/security.py",
    "requirements.txt",
    ".env"
)

$foundFiles = @()
$missingFiles = @()

Write-Host "Scanning for files..." -ForegroundColor Yellow
Write-Host ""

foreach ($file in $filesToCheck) {
    if (Test-Path $file) {
        Write-Host "[FOUND] $file" -ForegroundColor Green
        $foundFiles += $file
    } else {
        Write-Host "[MISSING] $file" -ForegroundColor Red
        $missingFiles += $file
    }
}

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "SUMMARY" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "Found: $($foundFiles.Count) files" -ForegroundColor Green
Write-Host "Missing: $($missingFiles.Count) files" -ForegroundColor Red
Write-Host ""

if ($missingFiles.Count -gt 0) {
    Write-Host "Missing files:" -ForegroundColor Red
    foreach ($file in $missingFiles) {
        Write-Host "  - $file" -ForegroundColor Red
    }
    Write-Host ""
}

# Now display each file's content
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "FILE CONTENTS" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

foreach ($file in $foundFiles) {
    Write-Host "--- FILE: $file ---" -ForegroundColor Cyan
    Write-Host ""
    Get-Content $file
    Write-Host ""
    Write-Host ""
}

Write-Host "======================================" -ForegroundColor Green
Write-Host "Done! Copy all the above content to share with Claude" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Green