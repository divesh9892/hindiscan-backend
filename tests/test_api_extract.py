import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
from app.core.security import get_current_user
from app.db.models import User
from app.db.database import get_db  

# Import your FastAPI app
from app.main import app
# Create a test client that acts like a browser
client = TestClient(app)

# 🚀 SECURITY BYPASS: Fake the Clerk User
def mock_get_current_user():
    return User(id=999, clerk_id="test_robot_123", email="robot@hindiscan.com", credit_balance=10)

# 🚀 DATABASE BYPASS: Fake the Database Session
async def mock_get_db():
    mock_db = AsyncMock()
    # Tell the mock that .add() is synchronous, so it stops throwing warnings!
    mock_db.add = MagicMock() 
    yield mock_db

# 🚀 FIX: Safely apply overrides per-test so they don't break other files
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

# 🚀 MOCKING: We intercept the AI Extractor before it talks to Google
@patch("app.api.v1.endpoints.extract.AIExtractor.process_document", new_callable=AsyncMock)
@patch("app.api.v1.endpoints.extract.AIExtractor.__init__", return_value=None) 
def test_extract_endpoint_success(mock_init, mock_process_document, mock_gemini_response):
    """
    Simulates a user uploading a valid JPEG.
    Ensures the API passes the Vault and returns a Ticket ID.
    """
    mock_process_document.return_value = mock_gemini_response

    # 🚀 FIX: Inject genuine JPEG Magic Bytes so the Vault lets it through
    valid_jpeg_bytes = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00' + b'fake_data'
    files = {"file": ("test_upload.jpeg", valid_jpeg_bytes, "image/jpeg")}
    data = {
        "extract_tables_only": "false",
        "use_legacy_font": "false",
        "legacy_font_name": "Kruti Dev 010"
    }

    response = client.post("/api/v1/extract/", files=files, data=data)

    # 🚀 FIX: We now expect a 200 OK and a task_id ticket, NOT the direct file!
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

    # 🚀 FIX: Our vault now throws a strict 415 Unsupported Media Type, not a generic 400
    assert response.status_code == 415