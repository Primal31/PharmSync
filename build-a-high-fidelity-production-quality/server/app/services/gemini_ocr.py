import base64
from google import genai
from app.schemas.scanner import MedicineExtraction
from app.config.settings import settings

PROMPT = """You are extracting information from a pharmaceutical medicine strip or package.
Read only information visibly present in the image. Do not guess or infer missing values.
Return ONLY valid JSON with exactly these keys: medicineName, genericName, manufacturer,
medicineId, batchNumber, manufacturingDate, expiryDate, gtin, storageCondition.
Use null when a value is not visible or cannot be confidently read. Preserve batch numbers
exactly as printed. Normalize dates to YYYY-MM-DD where possible. The pharmacist reviews
all extracted data before it is stored."""

def extract_medicine_fields(image_bytes: bytes, mime_type: str):
    if not settings.gemini_api_key:
        raise RuntimeError("Gemini OCR is not configured. Add GEMINI_API_KEY to server/.env.")
    client = genai.Client(api_key=settings.gemini_api_key)
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
