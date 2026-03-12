import os
import json
import uuid
import tempfile
import asyncio
import traceback
import shutil
import fitz  # 🚀 PyMuPDF Import
from urllib.parse import quote
from enum import Enum
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai_extractor import AIExtractor
from app.core.excel_builder import ExcelBuilder
from app.core.logger import log
from app.db.database import get_db
from app.db import crud
from app.core.security import get_current_user
from app.db.models import User

router = APIRouter()

# 🚀 1. IN-MEMORY TASK STORE (The Ticket System)
TASK_STORE = {}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB Strict Limit
MAX_PAGES_PER_UPLOAD = 15 # 🚀 AI Token Limit Protector

class LegacyFontEnum(str, Enum):
    KRUTI_DEV_010 = "Kruti Dev 010"
    DEVLYS_010 = "DevLys 010"

def cleanup_temp_dir(dir_path: str):
    """Safely deletes the entire temporary workspace after download."""
    try:
        if dir_path and os.path.exists(dir_path):
            shutil.rmtree(dir_path, ignore_errors=True)
            log.info(f"Cleaned up workspace: {dir_path}")
    except Exception as e:
        log.error(f"Failed to clean up workspace {dir_path}: {str(e)}")

def build_excel_sync(json_path: str, excel_path: str, use_legacy_font: bool, legacy_font_name: str):
    """Isolate the CPU-bound OpenPyXL Excel generation for a background thread"""
    try:
        builder = ExcelBuilder(
            json_path=json_path, 
            output_path=excel_path, 
            use_legacy_font=use_legacy_font,
            legacy_font_name=legacy_font_name
        )
        builder.build()
        return True
    except Exception as e:
        log.error(f"Excel generation failed: {str(e)}")
        raise e

async def validate_magic_bytes(file: UploadFile):
    """Deep Security Check: Verifies the file's raw Magic Bytes."""
    header = await file.read(4)
    await file.seek(0)  # Reset cursor for AI extraction
    
    is_pdf = header.startswith(b'%PDF')
    is_jpeg = header.startswith(b'\xff\xd8')
    is_png = header.startswith(b'\x89PNG')
    
    if not (is_pdf or is_jpeg or is_png):
        log.warning(f"Security Alert: Blocked invalid file signature for {file.filename}")
        raise HTTPException(
            status_code=415, 
            detail="Security Alert: Invalid file signature. This is not a genuine Image or PDF."
        )
    return file.content_type

def get_document_page_count(file_path: str, mime_type: str) -> int:
    """Instantly calculates the page count using PyMuPDF without using AI."""
    try:
        if mime_type in ["image/jpeg", "image/png"]:
            return 1 # Images are always 1 page
        elif mime_type == "application/pdf":
            doc = fitz.open(file_path)
            count = doc.page_count
            doc.close()
            return count
        return 1
    except Exception as e:
        log.error(f"Failed to read page count: {str(e)}")
        raise HTTPException(status_code=400, detail="Corrupted or unreadable document.")

# 🚀 2. THE BACKGROUND WORKER
async def process_extraction_task(
    task_id: str, 
    user_id: int, 
    doc_path: str, 
    content_type: str,
    original_filename: str,
    extract_tables_only: bool,
    use_legacy_font: bool,
    legacy_font_name: str,
    temp_dir: str
):
    extraction_success = False
    error_detail = None
    pages_processed = 0
    excel_path = None
    export_filename = None

    try:
        TASK_STORE[task_id]["progress"] = 10
        TASK_STORE[task_id]["message"] = "AI is analyzing document layout..."

        # Progress Callback for the AI
        def update_progress(current_page: int, total_pages: int):
            fraction = current_page / total_pages if total_pages > 0 else 0
            TASK_STORE[task_id]["progress"] = int(10 + (fraction * 75))
            TASK_STORE[task_id]["message"] = f"Processing page {current_page} of {total_pages}..."

        # Execute AI Extraction
        extractor = AIExtractor() 
        extracted_json = await extractor.process_document(
            doc_path, 
            content_type, 
            extract_tables_only,
            progress_callback=update_progress
        )

        pages_processed = len(extracted_json.get("pages", []))
        if "pages" not in extracted_json and "document" not in extracted_json:
            raise ValueError("AI Output Error: Missing valid root keys.")

        TASK_STORE[task_id]["progress"] = 90
        TASK_STORE[task_id]["message"] = "Building Smart Excel File..."

        json_path = os.path.join(temp_dir, "ai_output.json")
        ai_recommended_name = extracted_json.get("recommended_filename", "AI_Extracted_Report")
        safe_base_name = "".join(c for c in ai_recommended_name if c.isalnum() or c in (' ', '_', '-')).strip()
        export_filename = f"{safe_base_name.replace(' ', '_')}.xlsx"
        excel_path = os.path.join(temp_dir, export_filename)

        def save_json():
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(extracted_json, f)
        await asyncio.to_thread(save_json)

        # Execute Excel Build
        await asyncio.to_thread(
            build_excel_sync, 
            json_path, 
            excel_path, 
            use_legacy_font, 
            legacy_font_name
        )

        extraction_success = True

    except ValueError as ve:
        error_detail = str(ve)
        log.error(f"Task {task_id} failed: {traceback.format_exc()}")

    except Exception as e:
        error_detail = str(e)
        log.error(f"Task {task_id} failed: {traceback.format_exc()}")
        
    finally:
        # 🚀 BILLING RESOLUTION
        try:
            async for db_session in get_db():
                await crud.log_and_bill_extraction(
                    db=db_session,
                    user_id=user_id,
                    original_filename=original_filename,
                    pages=pages_processed,
                    success=extraction_success,
                    error_msg=error_detail if not extraction_success else None
                )
                break 
        except Exception as db_err:
            log.error(f"CRITICAL BILLING FAILURE: Could not log/deduct for task {task_id}. Error: {str(db_err)}")

        # 🚀 2. RELEASE TICKET TO FRONTEND (Only after DB is completely finished)
        if extraction_success:
            TASK_STORE[task_id]["status"] = "completed"
            TASK_STORE[task_id]["progress"] = 100
            TASK_STORE[task_id]["message"] = "Ready for download!"
            TASK_STORE[task_id]["excel_path"] = excel_path
            TASK_STORE[task_id]["export_filename"] = export_filename
        else:
            TASK_STORE[task_id]["status"] = "failed"
            TASK_STORE[task_id]["message"] = error_detail
# ==========================================
# 🚀 ENDPOINT 1: START EXTRACTION
# ==========================================
@router.post("/")
async def start_extraction(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    extract_tables_only: bool = Form(False),
    use_legacy_font: bool = Form(False),
    legacy_font_name: LegacyFontEnum = Form(LegacyFontEnum.KRUTI_DEV_010),
    user: User = Depends(get_current_user)
):
    # Quick fail-fast if completely empty
    if user.credit_balance < 1:
        raise HTTPException(status_code=402, detail="Insufficient credits. Please top up your balance.")

    if file.size and file.size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds the 5MB strict limit.")

    await validate_magic_bytes(file)

    task_id = str(uuid.uuid4())
    temp_dir = tempfile.mkdtemp(prefix=f"hs_{task_id}_")
    clean_original_filename = file.filename.replace(" ", "_")
    doc_path = os.path.join(temp_dir, clean_original_filename)

    with open(doc_path, "wb") as buffer:
        buffer.write(await file.read())

    # 🚀 PRE-FLIGHT CHECKS
    total_pages = get_document_page_count(doc_path, file.content_type)

    if total_pages > MAX_PAGES_PER_UPLOAD:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(
            status_code=400, 
            detail=f"Document has {total_pages} pages. To ensure high AI accuracy, the maximum allowed is {MAX_PAGES_PER_UPLOAD} pages per scan. Please split your file."
        )

    if user.credit_balance < total_pages:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(
            status_code=402, 
            detail=f"You are trying to extract {total_pages} pages, but you only have {user.credit_balance} credits available. Please top up your balance."
        )

    TASK_STORE[task_id] = {
        "status": "processing",
        "progress": 0,
        "message": "Initializing...",
        "temp_dir": temp_dir
    }

    background_tasks.add_task(
        process_extraction_task,
        task_id=task_id,
        user_id=user.id,
        doc_path=doc_path,
        content_type=file.content_type,
        original_filename=clean_original_filename,
        extract_tables_only=extract_tables_only,
        use_legacy_font=use_legacy_font,
        legacy_font_name=legacy_font_name.value,
        temp_dir=temp_dir
    )

    return {"task_id": task_id}

# ==========================================
# 🚀 ENDPOINT 2: STATUS CHECKER
# ==========================================
@router.get("/status/{task_id}")
async def get_task_status(task_id: str):
    task = TASK_STORE.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found or expired.")
    
    return {
        "status": task["status"],
        "progress": task["progress"],
        "message": task["message"]
    }

# ==========================================
# 🚀 ENDPOINT 3: DOWNLOAD & CLEANUP
# ==========================================
@router.get("/download/{task_id}")
async def download_extracted_file(task_id: str, background_tasks: BackgroundTasks):
    task = TASK_STORE.get(task_id)
    
    if not task or task.get("status") != "completed":
        raise HTTPException(status_code=400, detail="File is not ready yet.")

    excel_path = task["excel_path"]
    export_filename = task["export_filename"]
    temp_dir = task["temp_dir"]

    # Schedule complete workspace destruction AFTER file transmits
    background_tasks.add_task(cleanup_temp_dir, temp_dir)
    TASK_STORE.pop(task_id, None)

    encoded_filename = quote(export_filename)
    return FileResponse(
        path=excel_path, 
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={'Content-Disposition': f"attachment; filename*=utf-8''{encoded_filename}"}
    )