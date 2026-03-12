import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock

from app.main import app
from app.db.database import get_db
from app.db.models import User

client = TestClient(app)

@pytest.fixture(autouse=True)
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()

@pytest.fixture
def mock_env_secret(monkeypatch):
    """Fakes the environment variable so the endpoint doesn't crash on startup."""
    # 🚀 FIX: Used a mathematically valid 16-character base64 string after whsec_
    monkeypatch.setenv("CLERK_WEBHOOK_SECRET", "whsec_testsecretkey123")

# 🚀 MOCK SVIX: We intercept the signature verifier so we don't have to generate real crypto hashes
@patch("app.api.v1.endpoints.webhooks.Webhook.verify")
def test_clerk_webhook_user_deleted_success(mock_verify, mock_env_secret):
    """Proves that a valid deletion webhook successfully wipes the user from the DB."""
    
    # 1. Setup Mock DB
    mock_db = AsyncMock()
    
    # 🚀 FIX: Create a dedicated Async Context Manager for the transaction
    mock_transaction = AsyncMock()
    mock_transaction.__aenter__.return_value = mock_transaction
    mock_transaction.__aexit__.return_value = None
    
    # Explicitly tell db.begin to be a normal function that returns the context manager
    mock_db.begin = MagicMock(return_value=mock_transaction)
    
    mock_user = User(id=1, clerk_id="user_123", email="target@hindiscan.com")
    mock_result = MagicMock()
    mock_result.scalars().first.return_value = mock_user
    mock_db.execute.return_value = mock_result
    
    app.dependency_overrides[get_db] = lambda: mock_db

    # 2. Tell the Svix mock to simulate a successful signature verification
    mock_verify.return_value = {
        "type": "user.deleted",
        "data": {"id": "user_123"}
    }

    # 3. Fire the Webhook Request with required Svix headers
    headers = {
        "svix-id": "msg_123",
        "svix-timestamp": "1614556800",
        "svix-signature": "v1,fake_signature"
    }
    
    response = client.post("/api/v1/webhooks/clerk", json={"dummy": "data"}, headers=headers)
    
    # 4. Assertions
    assert response.status_code == 200
    assert response.json() == {"success": True}
    # Ensure the database delete command was actually called!
    assert mock_db.delete.called


@patch("app.api.v1.endpoints.webhooks.Webhook.verify")
def test_clerk_webhook_invalid_signature(mock_verify, mock_env_secret):
    """Proves that a hacker sending a fake signature is instantly rejected (400)."""
    from svix.webhooks import WebhookVerificationError
    
    # Tell the Svix mock to throw a signature error
    mock_verify.side_effect = WebhookVerificationError("Invalid signature")

    headers = {
        "svix-id": "msg_123",
        "svix-timestamp": "1614556800",
        "svix-signature": "v1,hacked_signature"
    }
    
    response = client.post("/api/v1/webhooks/clerk", json={"hacked": "data"}, headers=headers)
    
    assert response.status_code == 400
    assert "Invalid webhook signature" in response.json()["detail"]


def test_clerk_webhook_missing_secret(monkeypatch):
    """Proves the server safely aborts if the environment variable is missing (500)."""
    # Explicitly remove the secret
    monkeypatch.delenv("CLERK_WEBHOOK_SECRET", raising=False)
    
    response = client.post("/api/v1/webhooks/clerk", json={}, headers={})
    
    assert response.status_code == 500
    assert "Server configuration error" in response.json()["detail"]