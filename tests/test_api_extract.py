import pytest
import json
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock, mock_open

from app.main import app
from app.core.security import get_current_user
from app.db.models import User, ExtractionTask
from app.db.database import get_db

# Create a test client that acts like a browser
client = TestClient(app)

# 🚀 SECURITY BYPASS: Fake the Clerk User
def mock_get_current_user():
    return User(id=999, clerk_id="test_robot_123", email="robot@hindiscan.com", credit_balance=10)

# 🚀 DATABASE BYPASS: Fake the Database Session for API routing
async def mock_get_db():
    mock_db = AsyncMock()
    # Tell the mock that .add() is synchronous, so it stops throwing warnings
    mock_db.add = MagicMock() 
    yield mock_db

# Safely apply overrides per-test so they don't break other files
@pytest.fixture(autouse=True)
def apply_auth_overrides():
    app.dependency_overrides[get_current_user] = mock_get_current_user
    app.dependency_overrides[get_db] = mock_get_db
    yield
    app.dependency_overrides.clear()

@pytest.fixture(autouse=True)
def bypass_billing_for_api_tests():
    with patch("app.api.v1.endpoints.extract.crud.log_and_bill_extraction", new_callable=AsyncMock) as mock_billing:
        yield mock_billing

@pytest.fixture
def mock_gemini_response():
    """The fake JSON dictionary the AI will 'return' instantly."""
    return {
        "recommended_filename": "Mock_Test_Report",
        "pages": [
            {
                "document": {
                    "tables": [
                        {
                            "headers": [{"column_name": "Test Header", "is_bold": True}],
                            "rows": [["Test Data 1"], ["Test Data 2"]]
                        }
                    ],
                    "main_title": {"text": "Test Title", "is_bold": True, "font_size": 14}
                }
            }
        ]
    }

# ==========================================
# 🚀 POST EXTRACTION TESTS
# ==========================================

# MOCKING: Intercept the AI, the init, AND the background database writer to keep tests purely isolated
@patch("app.api.v1.endpoints.extract.AIExtractor.process_document", new_callable=AsyncMock)
@patch("app.api.v1.endpoints.extract.AIExtractor.__init__", return_value=None) 
@patch("app.api.v1.endpoints.extract.update_task_state", new_callable=AsyncMock) 
def test_extract_endpoint_success(mock_update_state, mock_init, mock_process_document, mock_gemini_response):
    """
    Simulates a user uploading a valid JPEG.
    Ensures the API passes the Vault and returns a Ticket ID.
    """
    mock_process_document.return_value = mock_gemini_response

    # Inject genuine JPEG Magic Bytes so the Vault lets it through
    valid_jpeg_bytes = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00' + b'fake_data'
    files = {"file": ("test_upload.jpeg", valid_jpeg_bytes, "image/jpeg")}
    data = {
        "extract_tables_only": "false",
        "use_legacy_font": "false",
        "legacy_font_name": "Kruti Dev 010"
    }

    response = client.post("/api/v1/extract/", files=files, data=data)

    assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}. Detail: {response.text}"
    assert "task_id" in response.json()


def test_extract_endpoint_invalid_file_type():
    """
    Simulates a user uploading a random .txt file.
    The API should reject it immediately before touching the AI.
    """
    files = {"file": ("hacked_script.txt", b"print('hack')", "text/plain")}
    data = {"legacy_font_name": "Kruti Dev 010"}

    response = client.post("/api/v1/extract/", files=files, data=data)

    # Our vault now throws a strict 415 Unsupported Media Type
    assert response.status_code == 415

# ==========================================
# 🚀 GET JSON ENDPOINT TESTS
# ==========================================

# THE FIX: Intercept the new `get_secure_task` DB function to return a fake Postgres Row
@patch("app.api.v1.endpoints.extract.get_secure_task", new_callable=AsyncMock)
def test_get_extracted_json_success(mock_get_secure_task):
    """Proves the JSON endpoint successfully returns parsed data for an authorized user."""
    
    # 1. Setup a fake task row using the new SQLAlchemy model
    task_id = "fake-json-task-123"
    fake_task = ExtractionTask(
        id=task_id, 
        user_id=999, 
        status="completed", 
        json_path="/fake/path/data.json"
    )
    mock_get_secure_task.return_value = fake_task

    fake_data = {"document": {"title": "Hello HindiScan"}}

    # 2. Intercept the operating system commands so we don't need a real file
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=json.dumps(fake_data))):
            response = client.get(f"/api/v1/extract/json/{task_id}")

    # 3. Assertions
    assert response.status_code == 200
    assert response.json() == fake_data


@patch("app.api.v1.endpoints.extract.get_secure_task", new_callable=AsyncMock)
def test_get_extracted_json_not_ready(mock_get_secure_task):
    """Proves the JSON endpoint blocks access if the AI is still processing."""
    
    # Create a task that is still in the "processing" state
    task_id = "fake-processing-task"
    fake_task = ExtractionTask(
        id=task_id, 
        user_id=999, 
        status="processing"
    )
    mock_get_secure_task.return_value = fake_task

    response = client.get(f"/api/v1/extract/json/{task_id}")

    assert response.status_code == 400
    assert "not ready" in response.json()["detail"]