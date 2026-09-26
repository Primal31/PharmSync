import asyncio
import logging
import re
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from app.middleware.auth import require_retail
from app.services.gemini_ocr import extract_medicine_fields
from app.services.ocr_space import extract_with_ocr_space
from app.config.settings import settings
from pydantic import ValidationError
from app.schemas.scanner import MedicineExtraction
from app.database.connection import connection

router = APIRouter(prefix="/api/scanner", tags=["scanner"])
logger = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MIME_EXTENSIONS = {"image/jpeg": {".jpg", ".jpeg"}, "image/png": {".png"}, "image/webp": {".webp"}}

def normalize_gtin(value: str | None, barcode_format: str | None = None) -> str | None:
    raw = (value or "").strip()
    ai01 = re.search(r"(?:\(01\)|\b01)(\d{14})(?!\d)", raw)
    if ai01:
        return ai01.group(1)
    supported_gtin_formats = {"ean_8", "ean_13", "upc_a"}
    if raw.isdigit() and len(raw) in {8, 12, 13, 14} and (barcode_format in supported_gtin_formats or barcode_format is None):
        return raw.zfill(14)
    return None

def enrich_from_catalog(data: dict, gtin: str | None) -> None:
    if not gtin:
        return
    try:
        with connection() as conn:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT medicine_id,medicine_name,generic_name,manufacturer FROM medicines WHERE gtin=%s LIMIT 1", (gtin,))
            medicine = cur.fetchone()
            cur.close()
        if medicine:
            data["medicineId"] = medicine["medicine_id"]
            for key, column in (("medicineName", "medicine_name"), ("genericName", "generic_name"), ("manufacturer", "manufacturer")):
                if not data.get(key): data[key] = medicine.get(column)
            data.setdefault("warnings", []).append("GTIN matched a PharmSync medicine catalog entry. Review the matched details.")
    except Exception as exc:
        # Scanner remains usable for manual review before/without the catalog migration.
        logger.info("Medicine catalog lookup unavailable (%s)", type(exc).__name__)

@router.post("/analyze-image")
async def analyze_image(file: UploadFile = File(...), barcode: str | None = Form(default=None), barcode_format: str | None = Form(default=None), user=Depends(require_retail)):
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
        extracted = MedicineExtraction.model_validate(fields)
        data = extracted.model_dump()
        decoded = (barcode or "").strip()[:256] or data.get("barcode")
        # Only treat a standards-shaped GTIN as a GTIN; a barcode may instead be a
        # serial, lot identifier, or another package code.
        gtin = normalize_gtin(decoded, barcode_format) or normalize_gtin(data.get("gtin"))
        data["barcode"] = decoded
        data["gtin"] = gtin
        data["source"] = "datamatrix" if (barcode_format or "").lower() == "datamatrix" else ("barcode" if barcode else "gemini")
        enrich_from_catalog(data, gtin)
        if gtin and not data.get("medicineId"):
            # Deterministic internal PharmSync medicine key derived from the GTIN.
            data["medicineId"] = "GTIN-" + gtin
        data["missingFields"] = [name for name in ("medicineName", "batchNumber", "manufacturingDate", "expiryDate") if not data.get(name)]
        return {"success": True, "data": data}
    except (ValueError, ValidationError):
        gemini_error = "Could not confidently read the medicine information."
    except Exception as exc:
        logger.error("Gemini OCR request failed (%s, code=%s)", type(exc).__name__, getattr(exc, "code", "unknown"))
        gemini_error = "Gemini analysis failed."
    if settings.ocr_space_api_key:
        try:
            fields = await asyncio.to_thread(extract_with_ocr_space, content, mime)
            data = MedicineExtraction.model_validate(fields).model_dump()
            data["source"] = "ocr"
            data["barcode"] = (barcode or "").strip()[:256] or None
            gtin = normalize_gtin(data["barcode"], barcode_format) or normalize_gtin(data.get("gtin"))
            data["gtin"] = gtin
            enrich_from_catalog(data, gtin)
            if gtin and not data.get("medicineId"): data["medicineId"] = "GTIN-" + gtin
            data["missingFields"] = [name for name in ("medicineName", "batchNumber", "manufacturingDate", "expiryDate") if not data.get(name)]
            return {"success": True, "data": data, "provider": "ocr.space"}
        except Exception as exc:
            logger.error("OCR.Space fallback failed (%s)", type(exc).__name__)
    if barcode:
        decoded = barcode.strip()[:256]
        gtin = normalize_gtin(decoded, barcode_format)
        names = ("medicineName", "batchNumber", "manufacturingDate", "expiryDate")
        empty_data = {"medicineName": None, "genericName": None, "manufacturer": None,
                "medicineId": "GTIN-" + gtin if gtin else None, "batchNumber": None, "manufacturingDate": None,
                "expiryDate": None, "gtin": gtin, "storageCondition": None, "barcode": decoded,
                "source": "datamatrix" if (barcode_format or "").lower() == "datamatrix" else "barcode",
                "unitPrice": None, "confidence": 0, "missingFields": list(names),
                "warnings": ["Barcode decoded, but package text could not be read. Enter or review the batch details manually."]}
        enrich_from_catalog(empty_data, gtin)
        empty_data["missingFields"] = [name for name in names if not empty_data.get(name)]
        return {"success": True, "data": empty_data}
    raise HTTPException(502, f"{gemini_error} Please try a clearer image or enter the details manually.")
