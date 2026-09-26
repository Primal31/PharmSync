"""Optional OCR.Space fallback; API key stays on the FastAPI server."""
import json
import re
import urllib.error
import urllib.request

from app.config.settings import settings


def _post_image(image_bytes: bytes, mime_type: str) -> str:
    if not settings.ocr_space_api_key:
        raise RuntimeError("OCR.Space fallback is not configured")
    boundary = "----PharmSyncOCRBoundary7MA4YWxkTrZu0gW"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\neng\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"OCREngine\"\r\n\r\n2\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"isOverlayRequired\"\r\n\r\nfalse\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"medicine-image\"\r\n"
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode() + image_bytes + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        "https://api.ocr.space/parse/image", data=body,
        headers={"apikey": settings.ocr_space_api_key, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OCR.Space request failed with HTTP {exc.code}") from exc
    if payload.get("IsErroredOnProcessing"):
        raise RuntimeError("OCR.Space could not process the image")
    results = payload.get("ParsedResults") or []
    text = "\n".join(item.get("ParsedText", "") for item in results).strip()
    if not text:
        raise ValueError("OCR.Space found no readable text")
    return text


def _label(text: str, labels: str) -> str | None:
    match = re.search(rf"(?:{labels})\s*[:#.-]?\s*([A-Z0-9][A-Z0-9./ -]{{1,35}})", text, re.I)
    return match.group(1).strip(" .-\r\n") if match else None


def extract_with_ocr_space(image_bytes: bytes, mime_type: str) -> dict:
    """Return only explicit label matches; ambiguous fields remain null for pharmacist review."""
    text = _post_image(image_bytes, mime_type)
    batch = _label(text, r"(?:BATCH(?:\s*(?:NO|NUMBER))?|B\.\s*NO)")
    mfg = _label(text, r"(?:MFG(?:\s*DATE)?|MANUFACT(?:URED|URING))")
    exp = _label(text, r"(?:EXP(?:\s*DATE)?|EXPIRY|EXPIRES)")
    # Medicine identifiers can only be attributed when explicitly labeled.
    medicine_id = _label(text, r"(?:MEDICINE\s*ID|MED\s*ID|PRODUCT\s*CODE)")
    gtin = _label(text, r"(?:GTIN|EAN|UPC)")
    # OCR.Space does not provide semantic identification; only capture a name if the
    # package explicitly labels it, avoiding guesses from arbitrary text.
    medicine_name = _label(text, r"(?:MEDICINE\s*NAME|PRODUCT\s*NAME|BRAND\s*NAME)")
    manufacturer = _label(text, r"(?:MANUFACTURER|MFR)")
    return {
        "medicineName": medicine_name,
        "genericName": _label(text, r"(?:GENERIC\s*NAME|COMPOSITION)"),
        "manufacturer": manufacturer,
        "medicineId": medicine_id,
        "batchNumber": batch,
        "manufacturingDate": mfg,
        "expiryDate": exp,
        "gtin": gtin,
        "storageCondition": _label(text, r"(?:STORAGE|STORE)"),
    }
