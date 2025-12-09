import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_register():
    response = client.post("/auth/register", json={
        "email": "testuser@example.com",
        "full_name": "Test User",
        "password": "TestPassword123"
    })
    assert response.status_code in [200, 422]

def test_login_invalid():
    response = client.post("/auth/login", json={
        "email": "nonexistent@example.com",
        "password": "wrong"
    })
    assert response.status_code in [401, 422]

