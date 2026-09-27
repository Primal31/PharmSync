import asyncio
import logging
import re
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import ValidationError
from app.config.settings import settings
from app.database.connection import connection
from app.middleware.auth import require_retail
from app.schemas.scanner import MedicineExtraction
from app.services.barcode import detect_barcode, parse_gtin_text, checksum_valid
from app.services.gemini_ocr import extract_medicine_fields as extract_with_gemini
from app.services.medicine_extractor import extract_medicine_fields as parse_medicine_fields
from app.services.ocr_space import extract_with_ocr_space
from app.services.paddle_ocr import OCRUnavailable, extract_text, load_image
from app.services.demo_scanner import format_demo_response, lookup_demo_image

router = APIRouter(prefix="/api/scanner", tags=["scanner"])
logger = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MIME_EXTENSIONS = {"image/jpeg", "image/png", "image/webp"}


def normalize_gtin(value: str | None, barcode_format: str | None = None) -> str | None:
    """Compatibility helper returning a 14-digit canonical value only if valid."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) in {8, 12, 13, 14} and checksum_valid(digits):
        return digits.zfill(14)
    return None


def lookup_catalog(gtin: str | None) -> dict | None:
    if not gtin: return None
    try:
        with connection() as conn:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT medicine_id,medicine_name,generic_name,manufacturer FROM medicines WHERE gtin=%s LIMIT 1", (gtin,))
            row = cur.fetchone()
            if row:
                try:
                    cur.execute("SELECT strength,dosage_form FROM medicines WHERE medicine_id=%s LIMIT 1", (row["medicine_id"],))
                    row.update(cur.fetchone() or {})
                except Exception:
                    # Step 9 only adds optional descriptive columns; step 8 catalog remains usable.
                    pass
            cur.close()
        return row
    except Exception as exc:
        logger.info("Medicine catalog lookup unavailable (%s)", type(exc).__name__)
        return None


def _gemini_fallback(image_bytes: bytes, mime: str, barcode: dict, catalog: dict | None,
                    gtin_info: dict | None = None) -> dict:
    if not settings.gemini_api_key:
        raise OCRUnavailable("Local OCR is unavailable and Gemini is not configured.")
    fields = extract_with_gemini(image_bytes, mime)
    gtin_info = gtin_info or barcode
    gtin = gtin_info.get("gtin") if gtin_info.get("valid_checksum") else None
    if gtin and catalog:
        fields["medicineId"] = catalog["medicine_id"]
        fields["medicineName"] = catalog.get("medicine_name") or fields.get("medicineName")
        fields["genericName"] = catalog.get("generic_name") or fields.get("genericName")
        fields["manufacturer"] = catalog.get("manufacturer") or fields.get("manufacturer")
        fields["strength"] = catalog.get("strength") or fields.get("strength")
        fields["dosageForm"] = catalog.get("dosage_form") or fields.get("dosageForm")
    fields.update({"gtin": gtin, "source": "gemini_fallback", "confidence": fields.get("confidence") or 0,
                   "missingFields": fields.get("missingFields") or [], "warnings": fields.get("warnings") or []})
    if not fields.get("medicineId") and gtin: fields["medicineId"] = "GTIN-" + gtin
    return MedicineExtraction.model_validate(fields).model_dump()


def _api_result(extracted: dict, barcode: dict, catalog: dict | None, source: str,
                gtin_info: dict | None = None) -> dict:
    model = MedicineExtraction.model_validate(extracted)
    data = model.model_dump()
    data["source"] = source
    matched = bool(catalog)
    catalog_result = {"found": matched}
    if catalog:
        catalog_result.update({"medicine_id": catalog.get("medicine_id"), "medicine_name": catalog.get("medicine_name"),
                               "generic_name": catalog.get("generic_name"), "strength": catalog.get("strength"),
                               "dosage_form": catalog.get("dosage_form")})
        if "GTIN matched a PharmSync medicine catalog entry." not in data["warnings"]:
            data["warnings"].append("GTIN matched a PharmSync medicine catalog entry.")
    gtin_info = gtin_info or barcode
    has_trusted_gtin = bool(gtin_info.get("gtin") and gtin_info.get("valid_checksum"))
    return {"success": True, "source": source,
        "barcode": {"detected": bool(barcode.get("detected")), "value": barcode.get("value"),
                    "format": barcode.get("format"), "valid_checksum": barcode.get("valid_checksum"),
                    "barcodes": barcode.get("barcodes", [])},
        "gtin": {"detected": bool(gtin_info.get("detected") and gtin_info.get("valid_checksum") is False or has_trusted_gtin),
                 "value": gtin_info.get("gtin") if has_trusted_gtin else None,
                 "format": gtin_info.get("format"), "valid": has_trusted_gtin},
        "catalog_match": catalog_result,
        "extracted": {"medicine_name": data.get("medicineName"), "generic_name": data.get("genericName"),
            "manufacturer": data.get("manufacturer"), "medicine_id": data.get("medicineId"),
            "strength": data.get("strength"), "dosage_form": data.get("dosageForm"),
            "batch_number": data.get("batchNumber"), "manufacture_date": data.get("manufacturingDate"),
            "expiry_date": data.get("expiryDate"), "unit_price": data.get("unitPrice"),
            "storage_type": data.get("storageCondition"), "gtin": data.get("gtin"),
            "barcode": barcode.get("value")},
        "confidence": {"overall": data.get("confidence", 0)}, "requires_confirmation": True,
        # Keep the previous React response envelope to avoid breaking the existing Restock form.
        "data": data}


@router.post("/analyze-image")
async def analyze_image(file: UploadFile = File(...), user=Depends(require_retail)):
    mime = (file.content_type or "").lower()
    if mime not in MIME_EXTENSIONS:
        raise HTTPException(415, "Unsupported file type. Upload a JPG, PNG, or WEBP image.")
    content = await file.read(MAX_IMAGE_BYTES + 1)
    await file.close()
    if not content: raise HTTPException(400, "Choose a medicine image before analyzing.")
    if len(content) > MAX_IMAGE_BYTES: raise HTTPException(413, "Image is too large. Choose an image smaller than 8 MB.")
    try:
        image = await asyncio.to_thread(load_image, content)
    except (ValueError, OCRUnavailable) as exc:
        demo_record = lookup_demo_image(content)
        if demo_record:
            return format_demo_response(demo_record)
        raise HTTPException(415, str(exc) if isinstance(exc, ValueError) else "Image processing is unavailable on this server.")

    barcode = await asyncio.to_thread(detect_barcode, image)
    gtin_info = barcode if barcode.get("valid_checksum") and barcode.get("gtin") else None
    try:
        ocr_result = await asyncio.to_thread(extract_text, image)
        if not ocr_result.get("lines"):
            raise OCRUnavailable("PaddleOCR did not return any readable text.")
        if not gtin_info:
            printed = parse_gtin_text(ocr_result.get("raw_text"))
            if printed.get("detected"): gtin_info = printed
        valid_gtin = gtin_info.get("gtin") if gtin_info else None
        catalog = await asyncio.to_thread(lookup_catalog, valid_gtin)
        fields = parse_medicine_fields(ocr_result, gtin_info or barcode, catalog)
        fields["barcode"] = barcode.get("value")
        fields["source"] = "paddleocr"
        return _api_result(fields, barcode, catalog, "paddleocr", gtin_info)
    except Exception as paddle_exc:
        logger.info("PaddleOCR unavailable (%s); trying configured fallback", type(paddle_exc).__name__)

    valid_gtin = gtin_info.get("gtin") if gtin_info else None
    catalog = await asyncio.to_thread(lookup_catalog, valid_gtin)
    try:
        fields = await asyncio.to_thread(_gemini_fallback, content, mime, barcode, catalog, gtin_info)
        return _api_result(fields, barcode, catalog, "gemini_fallback", gtin_info)
    except Exception as gemini_exc:
        logger.info("Gemini OCR fallback unavailable (%s)", type(gemini_exc).__name__)

    # Preserve the existing optional OCR.Space fallback, after local OCR and Gemini.
    if settings.ocr_space_api_key:
        try:
            legacy = await asyncio.to_thread(extract_with_ocr_space, content, mime)
            fields = {"medicineName": legacy.get("medicineName"), "genericName": legacy.get("genericName"),
                "manufacturer": legacy.get("manufacturer"), "medicineId": catalog.get("medicine_id") if catalog else None,
                "batchNumber": legacy.get("batchNumber"), "manufacturingDate": legacy.get("manufacturingDate"),
                "expiryDate": legacy.get("expiryDate"), "gtin": valid_gtin, "storageCondition": legacy.get("storageCondition"),
                "strength": catalog.get("strength") if catalog else None, "dosageForm": catalog.get("dosage_form") if catalog else None,
                "unitPrice": None, "source": "ocr_space_fallback", "confidence": 0,
                "missingFields": [], "warnings": ["OCR.Space fallback used; verify every extracted field."]}
            fields["missingFields"] = [key for key in ("medicineName", "medicineId", "batchNumber", "manufacturingDate", "expiryDate", "unitPrice") if fields.get(key) is None]
            return _api_result(fields, barcode, catalog, "ocr_space_fallback", gtin_info)
        except Exception as fallback_exc:
            logger.info("OCR.Space fallback unavailable (%s)", type(fallback_exc).__name__)
    demo_record = lookup_demo_image(content)
    if demo_record:
        return format_demo_response(demo_record)
    raise HTTPException(503, "Unable to automatically extract medicine details. Please enter the information manually.") from None
