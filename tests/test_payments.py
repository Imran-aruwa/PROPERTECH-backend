import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_initialize_payment_unauthorized():
    """Test payment initiation without auth returns 401/403"""
    response = client.post("/api/payments/initiate", json={
        "amount": 8000.0,
        "currency": "KES",
        "payment_type": "rent"
    })
    # 401 = unauthorized (no auth), 403 = forbidden
    assert response.status_code in [401, 403]

def test_verify_payment_unauthorized():
    """Test payment verification without auth returns 401/403"""
    response = client.post("/api/payments/verify", json={
        "reference": "invalid-reference"
    })
    # 401 = unauthorized (no auth), 403 = forbidden
    assert response.status_code in [401, 403]