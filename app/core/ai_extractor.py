import os
import json
import re
import fitz 
import asyncio
import json_repair
from google import genai
from google.genai import types
from dotenv import load_dotenv

from app.core.logger import log
from app.core.config import MASTER_PROMPT, SAMPLE_JSON, TABLES_ONLY_PROMPT 

load_dotenv()

class AIExtractor:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key or not self.api_key.strip():
            log.error("API Key missing.")
            raise ValueError("No API Key provided. Please enter a valid Gemini API Key.")     
        
        self.client = genai.Client(api_key=self.api_key.strip())
        # 🚀 REVERT TO STABLE MODEL
        self.model_name = 'gemini-2.5-flash' 

    def _clean_json_response(self, text):
        clean_text = text.strip()
        match = re.search(r'```(?:json)?\s*(.*?)\s*```', clean_text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return clean_text

    def _slice_pdf_sync(self, file_path):
        """CPU-Bound task isolated for background threading"""
        images = []
        with fitz.open(file_path) as doc:
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                pix = page.get_pixmap(dpi=150) 
                images.append(pix.tobytes("jpeg"))
        return images

    def _api_call_sync(self, full_prompt, document_part):
        """Isolating the API call for stable threadpool execution"""
        return self.client.models.generate_content(
            model=self.model_name,
            contents=[full_prompt, document_part],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
                max_output_tokens=8192 
            )
        )

    async def process_document(self, file_path, mime_type, extract_tables_only=False, progress_callback=None):
        log.info(f"Initiating Async AI extraction for document: {file_path} ({mime_type})")
        
        images_to_process = []
        if mime_type == "application/pdf":
            try:
                images_to_process = await asyncio.to_thread(self._slice_pdf_sync, file_path)
                log.info(f"Successfully sliced PDF into {len(images_to_process)} pages.")
            except Exception as e:
                raise ValueError(f"Failed to read PDF file: {str(e)}")
        else:
            def read_image():
                with open(file_path, "rb") as f:
                    return f.read()
            images_to_process.append(await asyncio.to_thread(read_image))

        all_pages_data = []
        master_filename = "AI_Extracted_Report"
        
        active_prompt = TABLES_ONLY_PROMPT if extract_tables_only else MASTER_PROMPT
        full_prompt = f"{active_prompt}\n\nEXPECTED JSON SCHEMA:\n{SAMPLE_JSON}"

        for idx, img_bytes in enumerate(images_to_process):
            if progress_callback:
                progress_callback(idx, len(images_to_process))
                
            log.info(f"Sending Page {idx + 1} to {self.model_name}...")
            document_part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")

            try:
                # 🚀 FIX: Threaded stable synchronous call instead of .aio
                response = await asyncio.to_thread(self._api_call_sync, full_prompt, document_part)
                raw_output = response.text
                
                if not raw_output:
                    raise ValueError(f"Page {idx+1}: AI returned a blank response.")

                clean_json_string = self._clean_json_response(raw_output)
                
                try:
                    parsed_data = json_repair.loads(clean_json_string)
                except Exception as parse_error:
                    log.error(f"Page {idx+1} JSON Repair Failed: {parse_error}")
                    parsed_data = {
                        "tables": [{"headers": [{"column_name": "Error"}], "rows": [[f"Failed to parse page {idx+1}. AI generated invalid structure."]]}]
                    }

                if "document" not in parsed_data:
                    log.warning(f"Page {idx+1}: AI missed the 'document' wrapper. Auto-healing...")
                    valid_root_keys = ["tables", "main_title", "subtitles", "footer"]
                    if any(key in parsed_data for key in valid_root_keys):
                        filename = parsed_data.pop("recommended_filename", f"Extracted_Page_{idx+1}")
                        parsed_data = {"recommended_filename": filename, "document": parsed_data}
                    else:
                        parsed_data = {"document": {"tables": []}}

                if idx == 0 and "recommended_filename" in parsed_data:
                    master_filename = parsed_data["recommended_filename"]

                all_pages_data.append(parsed_data)

                if idx < len(images_to_process) - 1:
                    log.info("Free tier rate limit pacing: Waiting 5 seconds before next page...")
                    if progress_callback:
                        progress_callback(idx, len(images_to_process))
                    await asyncio.sleep(5)

            except json.JSONDecodeError as e:
                log.error(f"Failed to parse Gemini output on page {idx+1}: {e}")
                raise ValueError(f"The AI returned invalid JSON format on Page {idx+1}. Try again.")
            except Exception as e:
                log.error(f"Gemini API Error on page {idx+1}: {str(e)}")
                raise RuntimeError(str(e))

        log.info("Successfully extracted and parsed all pages.")
        
        return {
            "recommended_filename": master_filename,
            "pages": all_pages_data
        }