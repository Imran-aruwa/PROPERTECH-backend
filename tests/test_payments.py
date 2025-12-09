
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_initialize_payment_unauthorized():
    response = client.post("/payments/initialize", json={
        "tenant_id": 1,
        "unit_id": 1,
        "amount": 8000.0,
        "payment_type": "rent"
    })
    assert response.status_code == 403

def test_verify_payment_invalid():
    response = client.post("/payments/verify/invalid-reference")
    assert response.status_code == 403