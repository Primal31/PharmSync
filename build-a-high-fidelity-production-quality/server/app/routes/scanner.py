import asyncio
import logging
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from app.middleware.auth import require_retail
from app.services.gemini_ocr import extract_medicine_fields
from app.services.ocr_space import extract_with_ocr_space
from app.config.settings import settings
from pydantic import ValidationError
from app.schemas.scanner import MedicineExtraction

router = APIRouter(prefix="/api/scanner", tags=["scanner"])
logger = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MIME_EXTENSIONS = {"image/jpeg": {".jpg", ".jpeg"}, "image/png": {".png"}, "image/webp": {".webp"}}

@router.post("/analyze-image")
async def analyze_image(file: UploadFile = File(...), user=Depends(require_retail)):
    mime = (file.content_type or "").lower()
    if mime not in MIME_EXTENSIONS:
        raise HTTPException(415, "Unsupported file type. Upload a JPG, PNG, or WEBP image.")
    if file.filename and not file.filename.lower().endswith(tuple(ext for exts in MIME_EXTENSIONS.values() for ext in exts)):
        raise HTTPException(415, "Unsupported file type. Upload a JPG, PNG, or WEBP image.")
    content = await file.read(MAX_IMAGE_BYTES + 1)
    await file.close()
    if not content:
        raise HTTPException(400, "Choose a medicine image before analyzing.")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image is too large. Choose an image smaller than 8 MB.")
    valid_signature = ((mime == "image/jpeg" and content.startswith(b"\xff\xd8\xff"))
        or (mime == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
        or (mime == "image/webp" and len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"))
    if not valid_signature:
        raise HTTPException(415, "The selected file is not a valid JPG, PNG, or WEBP image.")
    try:
        fields = await asyncio.to_thread(extract_medicine_fields, content, mime)
        return {"success": True, "data": MedicineExtraction.model_validate(fields).model_dump()}
    except (ValueError, ValidationError):
        gemini_error = "Could not confidently read the medicine information."
    except Exception as exc:
        logger.error("Gemini OCR request failed (%s, code=%s)", type(exc).__name__, getattr(exc, "code", "unknown"))
        gemini_error = "Gemini analysis failed."
    if settings.ocr_space_api_key:
        try:
            fields = await asyncio.to_thread(extract_with_ocr_space, content, mime)
            return {"success": True, "data": MedicineExtraction.model_validate(fields).model_dump(), "provider": "ocr.space"}
        except Exception as exc:
            logger.error("OCR.Space fallback failed (%s)", type(exc).__name__)
    raise HTTPException(502, f"{gemini_error} Please try a clearer image or enter the details manually.")
