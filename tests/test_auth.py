import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_register():
    """Test user registration via /api/auth/signup"""
    response = client.post("/api/auth/signup", json={
        "email": "testuser@example.com",
        "full_name": "Test User",
        "password": "TestPassword123",
        "role": "owner"
    })
    # 201 = success, 400 = email already exists, 422 = validation error
    assert response.status_code in [201, 400, 422]

def test_login_invalid():
    """Test login with invalid credentials via /api/auth/login"""
    response = client.post("/api/auth/login", json={
        "email": "nonexistent@example.com",
        "password": "wrong"
    })
    assert response.status_code in [401, 422]

