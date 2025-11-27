#!/usr/bin/env python3
"""
PROPERTECH Backend Diagnostic Script
Run this to show your current backend setup
"""

import os
import sys
from pathlib import Path

def check_backend_setup():
    """Check backend configuration and structure"""
    
    print("\n" + "="*60)
    print("PROPERTECH BACKEND DIAGNOSTIC")
    print("="*60 + "\n")
    
    # 1. Framework Check
    print("1. FRAMEWORK CHECK:")
    try:
        import flask
        print(f"   ✅ Flask installed: {flask.__version__}")
        framework = "Flask"
    except:
        framework = None
        print("   ❌ Flask not found")
    
    try:
        import fastapi
        print(f"   ✅ FastAPI installed: {fastapi.__version__}")
        if not framework:
            framework = "FastAPI"
    except:
        print("   ❌ FastAPI not found")
    
    if not framework:
        print("   ⚠️  No web framework detected!")
    
    # 2. Database Check
    print("\n2. DATABASE CHECK:")
    db_type = None
    try:
        import psycopg2
        print(f"   ✅ PostgreSQL driver (psycopg2) installed")
        db_type = "PostgreSQL"
    except:
        print("   ❌ PostgreSQL driver not found")
    
    try:
        import sqlalchemy
        print(f"   ✅ SQLAlchemy installed: {sqlalchemy.__version__}")
    except:
        print("   ❌ SQLAlchemy not found")
    
    try:
        import supabase
        print(f"   ✅ Supabase client installed")
        db_type = "Supabase"
    except:
        print("   ❌ Supabase client not found")
    
    # 3. Authentication Check
    print("\n3. AUTHENTICATION CHECK:")
    try:
        import jwt
        print(f"   ✅ PyJWT installed: {jwt.__version__}")
        auth_type = "JWT"
    except:
        auth_type = None
        print("   ❌ PyJWT not found")
    
    try:
        from passlib.context import CryptContext
        print(f"   ✅ Passlib installed (password hashing)")
    except:
        print("   ❌ Passlib not found")
    
    # 4. Payment Libraries
    print("\n4. PAYMENT LIBRARIES CHECK:")
    try:
        import stripe
        print(f"   ✅ Stripe installed: {stripe.__version__}")
    except:
        print("   ❌ Stripe not installed")
    
    # 5. Environment Variables
    print("\n5. ENVIRONMENT VARIABLES:")
    env_vars = [
        'DATABASE_URL',
        'SECRET_KEY',
        'ALGORITHM',
        'ACCESS_TOKEN_EXPIRE_MINUTES',
        'FRONTEND_URL',
        'STRIPE_SECRET_KEY',
        'STRIPE_PUBLISHABLE_KEY',
        'SUPABASE_URL',
        'SUPABASE_KEY',
    ]
    
    found_vars = {}
    for var in env_vars:
        value = os.getenv(var)
        if value:
            masked = value[:10] + "..." if len(value) > 10 else value
            print(f"   ✅ {var}: {masked}")
            found_vars[var] = True
        else:
            print(f"   ❌ {var}: NOT SET")
            found_vars[var] = False
    
    # 6. Project Structure
    print("\n6. PROJECT STRUCTURE:")
    base_path = Path.cwd()
    
    required_dirs = {
        'app': 'Main application folder',
        'app/models': 'Database models',
        'app/schemas': 'Data schemas',
        'app/api': 'API routes',
        'app/core': 'Core configuration',
    }
    
    for dir_name, description in required_dirs.items():
        dir_path = base_path / dir_name
        if dir_path.exists():
            print(f"   ✅ {dir_name}: {description}")
        else:
            print(f"   ❌ {dir_name}: NOT FOUND")
    
    # 7. Key Files Check
    print("\n7. KEY FILES:")
    key_files = {
        'app/main.py': 'Main application entry',
        'app/config.py': 'Configuration',
        'app/database.py': 'Database setup',
        'pyproject.toml': 'Project config',
        '.env': 'Environment variables',
        'requirements.txt': 'Python dependencies',
    }
    
    for file_name, description in key_files.items():
        file_path = base_path / file_name
        if file_path.exists():
            print(f"   ✅ {file_name}: {description}")
        else:
            print(f"   ❌ {file_name}: NOT FOUND")
    
    # 8. API Routes Check
    print("\n8. API ROUTES:")
    api_file = base_path / 'app' / 'api' / 'routes.py'
    if api_file.exists():
        with open(api_file, 'r') as f:
            content = f.read()
            if '@router' in content or '@app.route' in content:
                # Count routes
                route_count = content.count('@')
                print(f"   ✅ Found approximately {route_count} routes")
    else:
        print("   ⚠️  No routes file found")
    
    # 9. Summary
    print("\n" + "="*60)
    print("SUMMARY:")
    print("="*60)
    print(f"Framework: {framework if framework else '❌ NOT DETECTED'}")
    print(f"Database: {db_type if db_type else '❌ NOT DETECTED'}")
    print(f"Authentication: {auth_type if auth_type else '❌ NOT DETECTED'}")
    print(f"Environment Variables Set: {sum(found_vars.values())}/{len(found_vars)}")
    print("\n" + "="*60 + "\n")
    
    return {
        'framework': framework,
        'database': db_type,
        'auth': auth_type,
        'env_vars': found_vars
    }

if __name__ == "__main__":
    check_backend_setup()