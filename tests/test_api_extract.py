import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

# Import your FastAPI app
from app.main import app
# Create a test client that acts like a browser
client = TestClient(app)

@pytest.fixture
def dummy_image_bytes():
    """Generates fake image bytes for testing without needing a real file."""
    return b"fake_jpeg_binary_data_12345"

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
@patch("app.api.v1.endpoints.extract.AIExtractor.__init__", return_value=None) # Bypass API Key check
def test_extract_endpoint_success(mock_init, mock_process_document, dummy_image_bytes, mock_gemini_response):
    """
    Simulates a user uploading a valid JPEG.
    Ensures the API returns an Excel file with the correct headers and cleans up.
    """
    
    # 1. Instruct the mock to return our fake JSON instead of hitting Gemini
    mock_process_document.return_value = mock_gemini_response

    # 2. Prepare the fake multipart form-data request
    files = {"file": ("test_upload.jpeg", dummy_image_bytes, "image/jpeg")}
    data = {
        "extract_tables_only": "false",
        "use_legacy_font": "false",
        "legacy_font_name": "Kruti Dev 010"
    }

    # 3. Fire the request at your local test server
    response = client.post("/api/v1/extract/", files=files, data=data)

    # 4. Assertions: Did the server do its job?
    assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}. Detail: {response.text}"
    
    # Check if the response is actually an Excel file
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in response.headers["content-type"]
    
    # Check if the filename from our mock JSON was used
    assert "MockTestReport.xlsx" in response.headers["content-disposition"]
    
    # Verify our mock was actually called
    mock_process_document.assert_called_once()

def test_extract_endpoint_invalid_file_type():
    """
    Simulates a user uploading a random .txt file. 
    The API should reject it immediately before touching the AI.
    """
    files = {"file": ("hacked_script.txt", b"print('hack')", "text/plain")}
    data = {"legacy_font_name": "Kruti Dev 010"}
    
    response = client.post("/api/v1/extract/", files=files, data=data)
    
    assert response.status_code == 400
    assert "Invalid file type" in response.json()["detail"]