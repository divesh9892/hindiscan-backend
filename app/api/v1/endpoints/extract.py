import os
import json
import tempfile
import asyncio
import traceback
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

class LegacyFontEnum(str, Enum):
    KRUTI_DEV_010 = "Kruti Dev 010"
    DEVLYS_010 = "DevLys 010"

def cleanup_temp_file(path: str):
    """Safely deletes temporary files after the request has completed."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
            log.info(f"Cleaned up temporary file: {path}")
    except Exception as e:
        log.error(f"Failed to clean up {path}: {str(e)}")

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

@router.post("/")
async def extract_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    extract_tables_only: bool = Form(False),
    use_legacy_font: bool = Form(False),
    legacy_font_name: LegacyFontEnum = Form(LegacyFontEnum.KRUTI_DEV_010),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    # --- 1. BILLING CHECK ---
    # Do they have enough credits? If not, stop immediately.
    if user.credit_balance < 1:
        raise HTTPException(status_code=402, detail="Insufficient credits. Please top up your balance.")

    # --- 2. FILE VALIDATION & SETUP ---
    allowed_types = ["application/pdf", "image/jpeg", "image/png"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF, JPG, and PNG are allowed.")

    class TempPaths:
        dir: str = None
        doc: str = None
        json: str = None
        excel: str = None
        
    paths = TempPaths()
    paths.dir = tempfile.mkdtemp()
    
    clean_original_filename = file.filename.replace(" ", "_")
    paths.doc = os.path.join(paths.dir, clean_original_filename)

    extraction_success = False
    error_detail = None
    pages_processed = 0

    # --- 3. THE EXTRACTION PROCESS ---
    try:
        with open(paths.doc, "wb") as buffer:
            buffer.write(await file.read())

        # Execute AI Extraction
        extractor = AIExtractor() 
        extracted_json = await extractor.process_document(paths.doc, file.content_type, extract_tables_only)

        # Dynamically count the exact number of pages the AI processed
        pages_processed = len(extracted_json.get("pages", []))
        
        if "pages" not in extracted_json and "document" not in extracted_json:
            raise ValueError("AI Output Error: Missing valid root keys.")

        paths.json = os.path.join(paths.dir, "ai_output.json")
        
        ai_recommended_name = extracted_json.get("recommended_filename", "AI_Extracted_Report")
        safe_base_name = "".join(c for c in ai_recommended_name if c.isalnum() or c in (' ', '_', '-')).strip()
        export_filename = f"{safe_base_name.replace(' ', '_')}.xlsx"
        paths.excel = os.path.join(paths.dir, export_filename)

        def save_json():
            with open(paths.json, 'w', encoding='utf-8') as f:
                json.dump(extracted_json, f)
        await asyncio.to_thread(save_json)

        # Execute Excel Build
        await asyncio.to_thread(
            build_excel_sync, 
            paths.json, 
            paths.excel, 
            use_legacy_font, 
            legacy_font_name.value
        )

        extraction_success = True # We made it to the end without crashing!

    except ValueError as ve:
        error_detail = str(ve) # Capture the error so it can be saved to the database
        log.error(f"Extraction failed: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=error_detail)
    except Exception as e:
        error_detail = str(e) # Capture the raw error
        log.error(f"Extraction failed: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error during extraction.")
    
    finally:
        # --- 4. THE BILLING RESOLUTION (PATCHED) ---
        # Wrapped in a try/except so a DB crash doesn't break the file download or cleanup
        try:
            await crud.log_and_bill_extraction(
                db=db,
                user_id=user.id,
                original_filename=clean_original_filename,
                pages=pages_processed,
                success=extraction_success,
                error_msg=error_detail if not extraction_success else None
            )
        except Exception as db_err:
            # 🚨 CRITICAL LOG: We failed to bill the user, but we won't crash their download.
            log.error(f"CRITICAL BILLING FAILURE: Could not log/deduct for user {user.id}. Error: {str(db_err)}")

        # --- 5. CLEANUP ---
        background_tasks.add_task(cleanup_temp_file, paths.excel)
        background_tasks.add_task(cleanup_temp_file, paths.doc)
        background_tasks.add_task(cleanup_temp_file, paths.json)

    # --- 6. SEND TO USER ---
    encoded_filename = quote(export_filename)
    custom_headers = {
        'Content-Disposition': f"attachment; filename*=utf-8''{encoded_filename}"
    }

    return FileResponse(
        path=paths.excel, 
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=custom_headers
    )