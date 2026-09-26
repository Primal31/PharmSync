import base64
from google import genai
from app.schemas.scanner import MedicineExtraction
from app.config.settings import settings

PROMPT = """You are extracting information from a pharmaceutical medicine strip or package.
Read only information visibly present in the image. Do not guess or infer missing values.
Return ONLY valid JSON with exactly these keys: medicineName, genericName, manufacturer,
medicineId, batchNumber, manufacturingDate, expiryDate, gtin, storageCondition, barcode,
unitPrice, confidence, missingFields, warnings.
medicineId is only a product/medicine identifier visibly printed on the package; do not
invent one. barcode is the literal decoded/printed barcode value only when readable.
unitPrice is the printed price in INR only when clearly visible; otherwise null.
Use null when a value is not visible or cannot be confidently read. Preserve batch numbers
exactly as printed. Normalize dates to YYYY-MM-DD where possible. The pharmacist reviews
all extracted data before it is stored. confidence is an overall 0-to-1 estimate based on
legibility; missingFields lists names of requested fields that are null; warnings contains
short caveats about ambiguous text, if any."""

def extract_medicine_fields(image_bytes: bytes, mime_type: str):
    if not settings.gemini_api_key:
        raise RuntimeError("Gemini OCR is not configured. Add GEMINI_API_KEY to server/.env.")
    # Bound provider latency so an upload cannot leave the form in a scanning
    # state indefinitely. Barcode-only results still have a local fallback.
    client = genai.Client(api_key=settings.gemini_api_key, http_options=genai.types.HttpOptions(timeout=45000))
    response = client.interactions.create(
        model=settings.gemini_model,
        input=[
            {"type": "text", "text": PROMPT},
            {"type": "image", "data": base64.b64encode(image_bytes).decode("ascii"), "mime_type": mime_type},
        ],
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": MedicineExtraction.model_json_schema(),
        },
        store=False,
    )
    return MedicineExtraction.model_validate_json(response.output_text).model_dump()
