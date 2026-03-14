import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock
from contextlib import asynccontextmanager

from app.main import app 
from app.core.security import get_admin_user
from app.db.database import get_db
from app.db.models import User

client = TestClient(app)

mock_admin = User(id=888, clerk_id="admin_123", email="admin@hindiscan.com", credit_balance=100)

def override_get_admin_user_success():
    return mock_admin

def override_get_admin_user_forbidden():
    raise HTTPException(status_code=403, detail="Forbidden. Enterprise Admin access required.")

@pytest.fixture(autouse=True)
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()

@asynccontextmanager
async def mock_db_begin():
    yield

def test_god_mode_success():
    mock_target_user = User(id=1, email="target@hindiscan.com", credit_balance=5)
    
    mock_db = AsyncMock()
    mock_db.begin = mock_db_begin
    # 🚀 FIX: Force .add() to be synchronous so it doesn't throw the coroutine warning
    mock_db.add = MagicMock() 
    
    mock_result = MagicMock()
    mock_result.scalars().first.return_value = mock_target_user
    mock_db.execute.return_value = mock_result

    app.dependency_overrides[get_admin_user] = override_get_admin_user_success
    app.dependency_overrides[get_db] = lambda: mock_db

    payload = {"target_email": "target@hindiscan.com", "credits_to_add": 50}
    response = client.post("/api/v1/admin/grant-god-mode", json=payload)
    
    assert response.status_code == 200
    assert response.json()["new_balance"] == 55

def test_god_mode_user_not_found():
    mock_db = AsyncMock()
    mock_db.begin = mock_db_begin
    # 🚀 FIX: Apply the same sync mock here just in case
    mock_db.add = MagicMock() 
    
    mock_result = MagicMock()
    mock_result.scalars().first.return_value = None
    mock_db.execute.return_value = mock_result

    app.dependency_overrides[get_admin_user] = override_get_admin_user_success
    app.dependency_overrides[get_db] = lambda: mock_db

    payload = {"target_email": "ghost_user@hindiscan.com", "credits_to_add": 50}
    response = client.post("/api/v1/admin/grant-god-mode", json=payload)
    
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]

def test_god_mode_forbidden_access():
    app.dependency_overrides[get_admin_user] = override_get_admin_user_forbidden

    payload = {"target_email": "target@hindiscan.com", "credits_to_add": 50}
    response = client.post("/api/v1/admin/grant-god-mode", json=payload)
    
    assert response.status_code == 403