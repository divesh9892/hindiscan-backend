import os
import json
import uuid
import tempfile
import asyncio
import traceback
import shutil
import fitz
import secrets
from urllib.parse import quote
from datetime import datetime, timedelta, timezone
from enum import Enum
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends, Header, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.ai_extractor import AIExtractor
from app.core.excel_builder import ExcelBuilder
from app.core.logger import log
from app.db.database import get_db
from app.db import crud
from app.core.security import get_current_user
from app.db.models import User, ExtractionTask # 🚀 Imported the new DB model

router = APIRouter()

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB Strict Limit
MAX_PAGES_PER_UPLOAD = 15 

class LegacyFontEnum(str, Enum):
    KRUTI_DEV_010 = "Kruti Dev 010"
    DEVLYS_010 = "DevLys 010"

def cleanup_temp_dir(dir_path: str):
    """Safely deletes the entire temporary workspace."""
    try:
        if dir_path and os.path.exists(dir_path):
            shutil.rmtree(dir_path, ignore_errors=True)
            log.info(f"Cleaned up workspace: {dir_path}")
    except Exception as e:
        log.error(f"Failed to clean up workspace {dir_path}: {str(e)}")

def build_excel_sync(json_path: str, excel_path: str, use_legacy_font: bool, legacy_font_name: str):
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
    await file.seek(0)
    is_pdf = header.startswith(b'%PDF')
    is_jpeg = header.startswith(b'\xff\xd8')
    is_png = header.startswith(b'\x89PNG')
    if not (is_pdf or is_jpeg or is_png):
        raise HTTPException(status_code=415, detail="Security Alert: Invalid file signature. This is not a genuine Image or PDF.")
    return file.content_type

def get_document_page_count(file_path: str, mime_type: str) -> int:
    """Instantly calculates the page count using PyMuPDF without using AI."""
    try:
        if mime_type in ["image/jpeg", "image/png"]: return 1 
        elif mime_type == "application/pdf":
            doc = fitz.open(file_path)
            count = doc.page_count
            doc.close()
            return count
        return 1
    except Exception as e:
        log.error(f"Failed to read page count: {str(e)}")
        raise HTTPException(status_code=400, detail="Corrupted or unreadable document.")

# 🚀 DB HELPER: Updates task state independently of the main thread
async def update_task_state(task_id: str, **kwargs):
    async for db in get_db():
        result = await db.execute(select(ExtractionTask).where(ExtractionTask.id == task_id))
        task = result.scalars().first()
        if task:
            for key, value in kwargs.items():
                setattr(task, key, value)
            await db.commit()
        break # Ensures we only use one session

# 🚀 2. THE BACKGROUND WORKER
async def process_extraction_task(
    task_id: str, 
    user_id: int, 
    doc_path: str, 
    content_type: str,
    original_filename: str,
    total_pages: int,
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
    json_path = os.path.join(temp_dir, "ai_output.json") 

    try:
        await update_task_state(task_id, progress=10, message="AI is analyzing document layout...")

        # Fire-and-forget DB updates so the AI isn't slowed down
        def update_progress(current_page: int, total_pages: int):
            fraction = current_page / total_pages if total_pages > 0 else 0
            prog = int(10 + (fraction * 75))
            msg = f"Processing page {current_page} of {total_pages}..."
            asyncio.create_task(update_task_state(task_id, progress=prog, message=msg))

        extractor = AIExtractor() 
        extracted_json = await extractor.process_document(
            doc_path, content_type, extract_tables_only, progress_callback=update_progress
        )

        pages_processed = len(extracted_json.get("pages", []))
        if "pages" not in extracted_json and "document" not in extracted_json:
            raise ValueError("AI Output Error: Missing valid root keys.")

        await update_task_state(task_id, progress=90, message="Building Smart Excel File...")

        ai_recommended_name = extracted_json.get("recommended_filename", "AI_Extracted_Report")
        safe_base_name = "".join(c for c in ai_recommended_name if c.isalnum() or c in (' ', '_', '-')).strip()
        export_filename = f"{safe_base_name.replace(' ', '_')}.xlsx"
        excel_path = os.path.join(temp_dir, export_filename)

        def save_json():
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(extracted_json, f)
        await asyncio.to_thread(save_json)

        await asyncio.to_thread(build_excel_sync, json_path, excel_path, use_legacy_font, legacy_font_name)
        extraction_success = True

    except Exception as e:
        error_detail = str(e)
        log.error(f"Task {task_id} failed: {traceback.format_exc()}")
        
    finally:
        # 🚀 ENTERPRISE BILLING RESOLUTION
        try:
            async for db_session in get_db():
                if extraction_success:
                    await crud.log_successful_extraction(db_session, user_id, original_filename, total_pages)
                else:
                    await crud.refund_credits(db_session, user_id, total_pages, original_filename, error_detail)
                break 
        except Exception as db_err:
            log.error(f"BILLING RESOLUTION FAILURE for task {task_id}: {str(db_err)}")

        # 🚀 THE FIX: We update the Postgres row with the TTL. No more sleep()!
        expiration_time = datetime.now(timezone.utc) + timedelta(minutes=15)
        
        if extraction_success:
            await update_task_state(
                task_id, status="completed", progress=100, 
                message="Ready for download! (Expires in 15 mins)",
                excel_path=excel_path, json_path=json_path, 
                export_filename=export_filename, expires_at=expiration_time
            )
        else:
            await update_task_state(
                task_id, status="failed", message=error_detail, 
                error_detail=error_detail, expires_at=datetime.now(timezone.utc)
            )
            cleanup_temp_dir(temp_dir) 

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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if file.size and file.size > MAX_FILE_SIZE: 
        raise HTTPException(status_code=413, detail="File exceeds 5MB limit.")

    await validate_magic_bytes(file)

    task_id = str(uuid.uuid4())
    temp_dir = tempfile.mkdtemp(prefix=f"hs_{task_id}_")
    
    # 🚀 PATH TRAVERSAL FIX: Strip malicious folder paths from the filename
    safe_filename = os.path.basename(file.filename)
    clean_original_filename = safe_filename.replace(" ", "_")
    doc_path = os.path.join(temp_dir, clean_original_filename)

    with open(doc_path, "wb") as buffer: 
        buffer.write(await file.read())
        
    total_pages = get_document_page_count(doc_path, file.content_type)

    if total_pages > MAX_PAGES_PER_UPLOAD:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Maximum allowed is {MAX_PAGES_PER_UPLOAD} pages per scan.")

    # 🚀 DOUBLE-SPEND FIX: Lock row and deduct credits UPFRONT
    charged_successfully = await crud.charge_credits_upfront(db, user.id, total_pages, clean_original_filename)
    
    if not charged_successfully:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=402, detail=f"Insufficient credits. This document requires {total_pages} credits.")

    # Create Task in DB
    new_task = ExtractionTask(
        id=task_id, user_id=user.id, temp_dir=temp_dir,
        status="processing", progress=0, message="Initializing..."
    )
    db.add(new_task)
    await db.commit()

    # Pass the total_pages parameter we added earlier to the background task
    background_tasks.add_task(
        process_extraction_task, task_id, user.id, doc_path, file.content_type,
        clean_original_filename, total_pages, extract_tables_only, use_legacy_font, legacy_font_name.value, temp_dir
    )

    return {"task_id": task_id}

# ==========================================
# 🚀 ENDPOINT 2, 3, 4: AUTHENTICATED FETCH
# ==========================================
async def get_secure_task(task_id: str, user_id: int, db: AsyncSession):
    """Loophole Closed: Enforces database ownership before returning files."""
    result = await db.execute(select(ExtractionTask).where(ExtractionTask.id == task_id))
    task = result.scalars().first()
    
    if not task: raise HTTPException(status_code=404, detail="Task not found.")
    if task.user_id != user_id: raise HTTPException(status_code=403, detail="Unauthorized.")
    
    # Check if the cron job missed it, but it mathematically expired
    if task.expires_at and task.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This file has expired and been securely shredded.")
        
    return task

@router.get("/status/{task_id}")
async def get_task_status(task_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    task = await get_secure_task(task_id, user.id, db)
    return {"status": task.status, "progress": task.progress, "message": task.message}

@router.get("/json/{task_id}")
async def get_extracted_json(task_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    task = await get_secure_task(task_id, user.id, db)
    if task.status != "completed": raise HTTPException(status_code=400, detail="Data is not ready.")
    if not task.json_path or not os.path.exists(task.json_path): raise HTTPException(status_code=404, detail="JSON not found.")

    def read_json():
        with open(task.json_path, 'r', encoding='utf-8') as f: return json.load(f)
    return await asyncio.to_thread(read_json)

@router.get("/download/{task_id}")
async def download_extracted_file(task_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    task = await get_secure_task(task_id, user.id, db)
    if task.status != "completed": raise HTTPException(status_code=400, detail="File is not ready.")
    if not task.excel_path or not os.path.exists(task.excel_path): raise HTTPException(status_code=410, detail="File deleted.")

    encoded_filename = quote(task.export_filename)
    return FileResponse(
        path=task.excel_path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={'Content-Disposition': f"attachment; filename*=utf-8''{encoded_filename}"}
    )

# ==========================================
# 🚀 ENDPOINT 5: THE GARBAGE COLLECTOR
# ==========================================
@router.post("/garbage-collect")
async def trigger_garbage_collection(
    x_cron_secret: str = Header(None), 
    db: AsyncSession = Depends(get_db)
):
    """
    Secure endpoint to be pinged by cron-job.org every 5 minutes.
    Sweeps the database for expired tasks, shreds their files, and deletes the rows.
    """
    expected_secret = os.getenv("CRON_SECRET", "dev_secret_123")
    
    # Time-safe comparison prevents hackers from guessing the password via timing attacks
    if not x_cron_secret or not secrets.compare_digest(x_cron_secret, expected_secret):
        log.warning("Unauthorized garbage collection attempt blocked.")
        raise HTTPException(status_code=403, detail="Invalid cron secret.")

    log.info("🧹 Initiating Database-Backed Garbage Collection...")
    
    # Find all tasks that have expired
    result = await db.execute(
        select(ExtractionTask).where(ExtractionTask.expires_at <= datetime.now(timezone.utc))
    )
    expired_tasks = result.scalars().all()
    
    count = 0
    for task in expired_tasks:
        cleanup_temp_dir(task.temp_dir)
        await db.delete(task)
        count += 1
        
    await db.commit()
    log.info(f"✨ Garbage Collection Complete. Shredded {count} expired tasks.")
    
    return {"status": "success", "shredded_count": count}

# ==========================================
# 🚀 ENDPOINT 6: MANUAL JSON TO EXCEL
# ==========================================
@router.post("/manual/")
async def generate_manual_excel(
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user)
):
    """
    Instantly generates an Excel file from raw JSON.
    Used when a user edits the JSON in the frontend Success Hub.
    """
    try:
        body = await request.json()
        
        # 1. Isolate the target data
        json_data = body.get("json_data", body) if isinstance(body, dict) else body
        
        # 2. Deep Unwrapper for double-stringified JSON
        parse_attempts = 0
        while isinstance(json_data, str) and parse_attempts < 5:
            try:
                json_data = json.loads(json_data)
                parse_attempts += 1
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Provided JSON string is malformed and cannot be parsed.")

        if not isinstance(json_data, dict):
            raise HTTPException(status_code=400, detail=f"Expected a JSON object, but received a {type(json_data).__name__}.")

        # 3. Intelligent Parent Unwrapping
        if "pages" not in json_data and "document" not in json_data:
            if "data" in json_data and isinstance(json_data["data"], dict):
                json_data = json_data["data"]
            elif "payload" in json_data and isinstance(json_data["payload"], dict):
                json_data = json_data["payload"]
            else:
                raise HTTPException(status_code=400, detail="JSON must contain a 'pages' or 'document' root key. Check your JSON hierarchy.")

        # 🚀 4. THE FIX: Aggressive Filename Extraction (AFTER parsing is complete)
        ai_recommended_name = None
        
        # Location A: Top level of the request body
        if isinstance(body, dict) and body.get("recommended_filename"):
            ai_recommended_name = body.get("recommended_filename")
            
        # Location B: Inside the fully parsed json_data object
        if not ai_recommended_name and isinstance(json_data, dict) and json_data.get("recommended_filename"):
            ai_recommended_name = json_data.get("recommended_filename")
            
        # Location C: Nested inside the first page (standard Gemini output)
        if not ai_recommended_name and isinstance(json_data, dict):
            pages = json_data.get("pages", [])
            if isinstance(pages, list) and len(pages) > 0 and isinstance(pages[0], dict):
                ai_recommended_name = pages[0].get("recommended_filename")
                
        # Safety Net Fallback
        if not ai_recommended_name or not str(ai_recommended_name).strip():
            ai_recommended_name = "Manual_Export"

        # 5. Extract configuration safely
        use_legacy_font = False
        legacy_font_name = LegacyFontEnum.KRUTI_DEV_010.value
        
        if isinstance(body, dict):
            legacy_str = str(body.get("use_legacy_font", "false")).lower()
            use_legacy_font = legacy_str in ["true", "1", "yes"]
            legacy_font_name = body.get("legacy_font_name", legacy_font_name)

        # 6. Setup Secure Temporary Workspace
        task_id = str(uuid.uuid4())
        temp_dir = tempfile.mkdtemp(prefix=f"hs_manual_{task_id}_")
        json_path = os.path.join(temp_dir, "manual_input.json")
        
        # Clean the filename to prevent OS path errors
        safe_base_name = "".join(c for c in str(ai_recommended_name) if c.isalnum() or c in (' ', '_', '-')).strip()
        if not safe_base_name:
            safe_base_name = "Manual_Export"
            
        export_filename = f"{safe_base_name.replace(' ', '_')}.xlsx"
        excel_path = os.path.join(temp_dir, export_filename)

        # 7. Write parsed JSON to disk
        def save_json():
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False)
        await asyncio.to_thread(save_json)

        # 8. Build Excel synchronously in a separate thread
        await asyncio.to_thread(
            build_excel_sync, 
            json_path, 
            excel_path, 
            use_legacy_font, 
            legacy_font_name
        )

        if not os.path.exists(excel_path):
            raise RuntimeError("ExcelBuilder failed silently and did not produce an output file.")

        # 9. Schedule instant cleanup
        background_tasks.add_task(cleanup_temp_dir, temp_dir)

        log.info(f"Successfully generated manual Excel: {export_filename}")

        # 10. Stream the file directly back to the user
        encoded_filename = quote(export_filename)
        return FileResponse(
            path=excel_path, 
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={'Content-Disposition': f"attachment; filename*=utf-8''{encoded_filename}"}
        )

    except HTTPException as he:
        if 'temp_dir' in locals():
            cleanup_temp_dir(temp_dir)
        raise he
    except Exception as e:
        log.error(f"Manual Excel generation failed for user {user.email}: {str(e)}")
        if 'temp_dir' in locals():
            cleanup_temp_dir(temp_dir)
        raise HTTPException(status_code=500, detail="Failed to build Excel from manual data.")