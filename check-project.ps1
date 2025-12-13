# ============================================================================
# PROPERTECH BACKEND - PROJECT STRUCTURE ANALYZER
# ============================================================================
# This script analyzes your project structure and identifies what you have
# ============================================================================

$projectPath = "C:\Users\Administrator\Desktop\PROPERTECH-Backend"

Write-Host ""
Write-Host ("=" * 80) -ForegroundColor Cyan
Write-Host "  PROPERTECH BACKEND - PROJECT ANALYSIS" -ForegroundColor Yellow
Write-Host ("=" * 80) -ForegroundColor Cyan
Write-Host ""

# Check if path exists
if (-not (Test-Path $projectPath)) {
    Write-Host "ERROR: Project path not found!" -ForegroundColor Red
    Write-Host "Path: $projectPath" -ForegroundColor Red
    exit 1
}

Set-Location $projectPath
Write-Host "Analyzing project at: " -NoNewline
Write-Host "$projectPath" -ForegroundColor Green
Write-Host ""

# ============================================================================
# 1. CHECK PROJECT TYPE
# ============================================================================
Write-Host "[1] PROJECT TYPE DETECTION" -ForegroundColor Cyan
Write-Host ("-" * 80)

$isPython = Test-Path "requirements.txt"
$isNode = Test-Path "package.json"
$hasPrisma = Test-Path "prisma"
$hasPrismaSchema = Test-Path "prisma\schema.prisma"

if ($isPython) {
    Write-Host "  Python Project: " -NoNewline -ForegroundColor Yellow
    Write-Host "DETECTED" -ForegroundColor Green
    Write-Host "    File: requirements.txt found" -ForegroundColor Gray
}

if ($isNode) {
    Write-Host "  Node.js Project: " -NoNewline -ForegroundColor Yellow
    Write-Host "DETECTED" -ForegroundColor Green
    Write-Host "    File: package.json found" -ForegroundColor Gray
}

if ($hasPrisma) {
    Write-Host "  Prisma ORM: " -NoNewline -ForegroundColor Yellow
    Write-Host "DETECTED" -ForegroundColor Green
    Write-Host "    Directory: prisma\ found" -ForegroundColor Gray
}

if ($hasPrismaSchema) {
    Write-Host "  Prisma Schema: " -NoNewline -ForegroundColor Yellow
    Write-Host "DETECTED" -ForegroundColor Green
    Write-Host "    File: prisma\schema.prisma found" -ForegroundColor Gray
}

# ============================================================================
# 2. CHECK CRITICAL FILES
# ============================================================================
Write-Host ""
Write-Host "[2] CRITICAL FILES CHECK" -ForegroundColor Cyan
Write-Host ("-" * 80)

$criticalFiles = @(
    @{Path="app\main.py"; Description="Main FastAPI application"},
    @{Path="app\database.py"; Description="Database configuration"},
    @{Path="app\core\config.py"; Description="Application settings"},
    @{Path=".env"; Description="Environment variables"},
    @{Path="requirements.txt"; Description="Python dependencies"},
    @{Path="run.py"; Description="Application runner"},
    @{Path="app\__init__.py"; Description="App package init"},
    @{Path="app\api\__init__.py"; Description="API package init"},
    @{Path="app\api\routes\__init__.py"; Description="Routes package init"}
)

foreach ($file in $criticalFiles) {
    $exists = Test-Path $file.Path
    Write-Host "  $($file.Description): " -NoNewline -ForegroundColor Yellow
    if ($exists) {
        Write-Host "EXISTS" -ForegroundColor Green
    } else {
        Write-Host "MISSING" -ForegroundColor Red
    }
    Write-Host "    $($file.Path)" -ForegroundColor Gray
}

# ============================================================================
# 3. PROJECT DIRECTORY STRUCTURE
# ============================================================================
Write-Host ""
Write-Host "[3] PROJECT DIRECTORY STRUCTURE (Top Level)" -ForegroundColor Cyan
Write-Host ("-" * 80)
Write-Host ""

$items = Get-ChildItem -Path $projectPath -Force | Where-Object {
    $_.Name -notmatch '^(__pycache__|\.git|node_modules|venv|\.pytest_cache|\.mypy_cache)$'
} | Sort-Object {$_.PSIsContainer}, Name -Descending

foreach ($item in $items) {
    if ($item.PSIsContainer) {
        Write-Host "  [DIR]  " -NoNewline -ForegroundColor Cyan
        Write-Host $item.Name -ForegroundColor Cyan
    } else {
        Write-Host "  [FILE] " -NoNewline -ForegroundColor Gray
        
        $color = switch -Regex ($item.Extension) {
            '\.py$' { 'Green' }
            '\.(json|yaml|yml)$' { 'Yellow' }
            '\.(txt|md)$' { 'Gray' }
            '\.env' { 'Magenta' }
            default { 'White' }
        }
        
        Write-Host $item.Name -ForegroundColor $color
    }
}

# Show app directory structure
Write-Host ""
Write-Host "  app\ directory contents:" -ForegroundColor Yellow
if (Test-Path "app") {
    $appItems = Get-ChildItem -Path "app" -Force | Where-Object {
        $_.Name -notmatch '^(__pycache__|\.pytest_cache)$'
    } | Sort-Object {$_.PSIsContainer}, Name -Descending
    
    foreach ($item in $appItems) {
        if ($item.PSIsContainer) {
            Write-Host "    [DIR]  " -NoNewline -ForegroundColor Cyan
            Write-Host $item.Name -ForegroundColor Cyan
        } else {
            Write-Host "    [FILE] " -NoNewline -ForegroundColor Gray
            Write-Host $item.Name -ForegroundColor Green
        }
    }
}

# ============================================================================
# 4. CHECK DEPENDENCIES
# ============================================================================
Write-Host ""
Write-Host "[4] DEPENDENCIES CHECK" -ForegroundColor Cyan
Write-Host ("-" * 80)

if (Test-Path "requirements.txt") {
    Write-Host ""
    Write-Host "  Python Dependencies (requirements.txt):" -ForegroundColor Yellow
    
    $requirements = Get-Content "requirements.txt" | Where-Object { $_ -match '\S' -and $_ -notmatch '^#' }
    
    $keyPackages = @("fastapi", "uvicorn", "sqlalchemy", "prisma", "psycopg2", "pydantic", "python-dotenv", "passlib", "python-jose")
    
    foreach ($pkg in $keyPackages) {
        $found = $requirements | Where-Object { $_ -match "^$pkg" }
        Write-Host "    $pkg" -NoNewline -ForegroundColor Yellow
        Write-Host ": " -NoNewline
        if ($found) {
            Write-Host "FOUND ($found)" -ForegroundColor Green
        } else {
            Write-Host "NOT FOUND" -ForegroundColor Red
        }
    }
}

if (Test-Path "package.json") {
    Write-Host ""
    Write-Host "  Node.js Dependencies (package.json):" -ForegroundColor Yellow
    try {
        $packageJson = Get-Content "package.json" | ConvertFrom-Json
        if ($packageJson.dependencies) {
            Write-Host "    Dependencies: $($packageJson.dependencies.PSObject.Properties.Count)" -ForegroundColor Gray
        }
    } catch {
        Write-Host "    Could not parse package.json" -ForegroundColor Red
    }
}

# ============================================================================
# 5. CHECK ENVIRONMENT FILES
# ============================================================================
Write-Host ""
Write-Host "[5] ENVIRONMENT CONFIGURATION" -ForegroundColor Cyan
Write-Host ("-" * 80)

$envFiles = @(".env", ".env.example", ".env.local", ".env.production")

foreach ($envFile in $envFiles) {
    $exists = Test-Path $envFile
    Write-Host "  $envFile" -NoNewline -ForegroundColor Yellow
    Write-Host ": " -NoNewline
    if ($exists) {
        Write-Host "EXISTS" -ForegroundColor Green
        
        # Check for key variables
        $content = Get-Content $envFile -ErrorAction SilentlyContinue
        $hasDbUrl = $content | Where-Object { $_ -match "DATABASE.*URL" }
        $hasSecret = $content | Where-Object { $_ -match "SECRET_KEY" }
        
        if ($hasDbUrl) {
            Write-Host "    - DATABASE_URL: Found" -ForegroundColor Gray
        }
        if ($hasSecret) {
            Write-Host "    - SECRET_KEY: Found" -ForegroundColor Gray
        }
    } else {
        Write-Host "MISSING" -ForegroundColor Red
    }
}

# ============================================================================
# 6. CHECK DATABASE SETUP
# ============================================================================
Write-Host ""
Write-Host "[6] DATABASE CONFIGURATION" -ForegroundColor Cyan
Write-Host ("-" * 80)

# Check for database.py
if (Test-Path "app\database.py") {
    Write-Host "  Database Config: " -NoNewline -ForegroundColor Yellow
    Write-Host "EXISTS" -ForegroundColor Green
    
    $dbContent = Get-Content "app\database.py" -Raw -ErrorAction SilentlyContinue
    
    if ($dbContent -match "sqlalchemy") {
        Write-Host "    - ORM: SQLAlchemy detected" -ForegroundColor Gray
    }
    if ($dbContent -match "prisma") {
        Write-Host "    - ORM: Prisma detected" -ForegroundColor Gray
    }
    if ($dbContent -match "railway") {
        Write-Host "    - Host: Railway detected" -ForegroundColor Gray
    }
} else {
    Write-Host "  Database Config: " -NoNewline -ForegroundColor Yellow
    Write-Host "MISSING" -ForegroundColor Red
}

# Check for Prisma schema
if (Test-Path "prisma\schema.prisma") {
    Write-Host ""
    Write-Host "  Prisma Schema: " -NoNewline -ForegroundColor Yellow
    Write-Host "EXISTS" -ForegroundColor Green
    
    $schema = Get-Content "prisma\schema.prisma" -Raw -ErrorAction SilentlyContinue
    
    if ($schema -match 'provider\s*=\s*"postgresql"') {
        Write-Host "    - Database: PostgreSQL" -ForegroundColor Gray
    }
    
    # Count models
    $models = ([regex]::Matches($schema, 'model\s+\w+')).Count
    Write-Host "    - Models defined: $models" -ForegroundColor Gray
}

# ============================================================================
# 7. SUMMARY & RECOMMENDATIONS
# ============================================================================
Write-Host ""
Write-Host "[7] SUMMARY & RECOMMENDATIONS" -ForegroundColor Cyan
Write-Host ("-" * 80)

Write-Host ""
Write-Host "  PROJECT STATUS:" -ForegroundColor Yellow

if ($isPython -and $hasPrisma) {
    Write-Host "    >> Python FastAPI + Prisma (Hybrid Setup)" -ForegroundColor Magenta
    Write-Host "    >> WARNING: This is UNUSUAL - Prisma is typically for Node.js" -ForegroundColor Yellow
    Write-Host "    >> You may have both SQLAlchemy AND Prisma patterns" -ForegroundColor Yellow
}
elseif ($isPython) {
    Write-Host "    >> Python FastAPI + SQLAlchemy" -ForegroundColor Green
}
elseif ($isNode -and $hasPrisma) {
    Write-Host "    >> Node.js + Prisma" -ForegroundColor Green
}

Write-Host ""
Write-Host "  RECOMMENDATIONS:" -ForegroundColor Yellow

if ($isPython -and $hasPrisma) {
    Write-Host "    1. DECIDE: Use SQLAlchemy OR Prisma (not both)" -ForegroundColor Red
    Write-Host "       - SQLAlchemy: Native Python, mature, FastAPI-friendly" -ForegroundColor Gray
    Write-Host "       - Prisma Python Client: Newer, experimental" -ForegroundColor Gray
    Write-Host "    2. RECOMMENDED: Use SQLAlchemy for production" -ForegroundColor Yellow
    Write-Host "    3. Remove Prisma files if using SQLAlchemy" -ForegroundColor Yellow
}

if (-not (Test-Path ".env")) {
    Write-Host "    ! Create .env file with DATABASE_PUBLIC_URL" -ForegroundColor Red
}

if (-not (Test-Path "app\database.py")) {
    Write-Host "    ! Create app\database.py with database configuration" -ForegroundColor Red
}

Write-Host ""
Write-Host ("=" * 80) -ForegroundColor Cyan
Write-Host "  ANALYSIS COMPLETE" -ForegroundColor Yellow
Write-Host ("=" * 80) -ForegroundColor Cyan
Write-Host ""

# ============================================================================
# 8. EXPORT FULL TREE TO FILE
# ============================================================================
Write-Host "Exporting detailed tree to project-structure.txt..." -ForegroundColor Gray

$outputFile = "project-structure.txt"

@"
PROPERTECH BACKEND - PROJECT STRUCTURE
Generated: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Path: $projectPath

============================================================
FULL DIRECTORY TREE
============================================================

"@ | Out-File $outputFile -Encoding UTF8

tree /F /A | Out-File $outputFile -Append -Encoding UTF8

Write-Host "  Saved to: " -NoNewline -ForegroundColor Green
Write-Host "$projectPath\$outputFile" -ForegroundColor White
Write-Host ""

Write-Host "To view the full tree, run: " -NoNewline -ForegroundColor Yellow
Write-Host "notepad $outputFile" -ForegroundColor White
Write-Host ""

Write-Host "Please share the output above and/or the project-structure.txt file" -ForegroundColor Cyan
Write-Host ""