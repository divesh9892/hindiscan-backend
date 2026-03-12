import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import app # Adjust this import based on your actual main FastAPI file
from app.core.security import get_current_user
from app.db.models import User

client = TestClient(app)

# Create a mock user to bypass Clerk authentication during the test
mock_user = User(id=999, clerk_id="mock_auth_123", email="auth@test.com", credit_balance=10)

def override_get_current_user():
    return mock_user

# 🚀 FIX: Safely apply overrides per-test
@pytest.fixture(autouse=True)
def apply_auth_overrides():
    app.dependency_overrides[get_current_user] = override_get_current_user
    yield
    app.dependency_overrides.clear()

# 🚀 FIX: Isolate the Router from the Database by mocking the CRUD layer
@patch("app.api.v1.endpoints.billing.crud.get_user_transactions", new_callable=AsyncMock)
def test_billing_history_endpoint_structure(mock_get_tx):
    """
    Ensures the /history endpoint returns a 200 OK and the correct JSON dictionary layout
    that our Next.js frontend is expecting.
    """
    # 1. Instruct the mock to return an empty ledger (transactions, has_more, next_cursor)
    mock_get_tx.return_value = ([], False, None)
    
    # 2. Hit the endpoint
    response = client.get("/api/v1/billing/history?limit=5")
    
    # 3. Assert HTTP Status
    assert response.status_code == 200
    
    # 4. Assert JSON Structure
    json_data = response.json()
    assert "data" in json_data
    assert "pagination" in json_data
    
    pagination = json_data["pagination"]
    assert "has_more" in pagination
    assert "next_cursor" in pagination
    assert isinstance(json_data["data"], list)