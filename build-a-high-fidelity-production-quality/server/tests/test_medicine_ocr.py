from datetime import date
from io import BytesIO
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.services.barcode import checksum_valid, parse_gtin_text
from app.services.medicine_extractor import extract_medicine_fields


SAMPLE = """AMOXICILLIN CAPSULES IP
500 mg
Batch No: AMX2025A01
Mfg Date: 02/2025
Expiry Date: 02/2027
M.R.P: ₹45.00
GTIN: 8901234567890
Store at room temperature"""


def test_gtin_checksum_and_normalized_label_detection():
    assert checksum_valid("8901234567890")
    assert parse_gtin_text("GTIN: 8901234567890") == {
        "detected": True, "value": "8901234567890", "gtin": "08901234567890", "format": "EAN13", "valid_checksum": True
    }


def test_invalid_gtin_not_trusted():
    assert not checksum_valid("8901234567891")
    result = parse_gtin_text("EAN-13: 8901234567891")
    assert result["detected"] and not result["valid_checksum"] and result["gtin"] is None


@pytest.mark.parametrize("value,valid", [("8901234567890", True), ("8901234567891", False)])
def test_pyzbar_decoding_and_checksum_validation(monkeypatch, value, valid):
    from app.services import barcode
    class GrayImage:
        ndim = 2
        shape = (12, 18)
        def tobytes(self): return bytes(12 * 18)
    class Code:
        data = value.encode()
        type = "EAN13"
    decoder = SimpleNamespace(decode=lambda _image: [Code()])
    monkeypatch.setitem(sys.modules, "pyzbar", SimpleNamespace(__path__=[]))
    monkeypatch.setitem(sys.modules, "pyzbar.pyzbar", decoder)
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace(ascontiguousarray=lambda image: image))
    monkeypatch.setattr(barcode, "_variants", lambda image: [image])
    result = barcode.detect_barcode(GrayImage())
    assert result["detected"] is True
    assert result["valid_checksum"] is valid
    assert result["gtin"] == ("08901234567890" if valid else None)


def test_pyzbar_supports_non_gtin_types_without_fabricated_confidence(monkeypatch):
    from app.services import barcode
    class GrayImage:
        ndim = 2
        shape = (3, 4)
        def tobytes(self): return bytes(12)
    class Code:
        data = b"LOT-A17"
        type = "CODE128"
    monkeypatch.setitem(sys.modules, "pyzbar", SimpleNamespace(__path__=[]))
    monkeypatch.setitem(sys.modules, "pyzbar.pyzbar", SimpleNamespace(decode=lambda _image: [Code()]))
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace(ascontiguousarray=lambda image: image))
    monkeypatch.setattr(barcode, "_variants", lambda image: [image])
    result = barcode.detect_barcode(GrayImage())
    assert result["detected"] and result["value"] == "LOT-A17"
    assert result["format"] == "CODE128" and result["gtin"] is None
    assert "confidence" not in result


def test_extracts_labeled_batch_dates_price_strength_and_storage_without_guessing():
    lines = [{"text": line, "confidence": .9} for line in SAMPLE.splitlines()]
    result = extract_medicine_fields({"raw_text": SAMPLE, "lines": lines}, {"detected": False})
    assert result["medicineName"] == "AMOXICILLIN 500 mg"
    assert result["batchNumber"] == "AMX2025A01"
    assert result["manufacturingDate"] == "2025-02-01"
    assert result["expiryDate"] == "2027-02-28"
    assert result["unitPrice"] == 45
    assert result["storageCondition"] == "Ambient Room Temperature"
    assert result["strength"] == "500 mg" and result["dosageForm"] == "Capsule"
    assert result["genericName"] is None
    assert "medicineId" in result["missingFields"]
    assert any("first day" in warning for warning in result["warnings"])
    assert any("last day" in warning for warning in result["warnings"])


def test_catalog_gtin_match_enriches_product_fields():
    catalog = {"medicine_id": "MED-1", "medicine_name": "Catalog Amoxicillin", "generic_name": "Amoxicillin",
               "manufacturer": "Example Labs", "strength": "500 mg", "dosage_form": "Capsule"}
    result = extract_medicine_fields({"raw_text": "Batch: B-1", "lines": [{"text": "Batch: B-1", "confidence": .8}]},
                                    {"detected": True, "gtin": "08901234567890", "valid_checksum": True}, catalog)
    assert result["medicineId"] == "MED-1"
    assert result["medicineName"] == "Catalog Amoxicillin"
    assert result["genericName"] == "Amoxicillin"
    assert result["batchNumber"] == "B-1"


def test_unknown_gtin_produces_stable_id_but_no_invented_catalog_details():
    result = extract_medicine_fields({"raw_text": "Batch: X1", "lines": []},
                                    {"detected": True, "gtin": "08901234567890", "valid_checksum": True})
    assert result["medicineId"] == "GTIN-08901234567890"
    assert result["medicineName"] is None


def test_no_batch_label_does_not_use_gtin_as_batch():
    result = extract_medicine_fields({"raw_text": "GTIN: 8901234567890", "lines": []},
                                    {"detected": True, "gtin": "08901234567890", "valid_checksum": True})
    assert result["batchNumber"] is None


def test_batch_id_label_is_parsed_as_the_existing_batch_number_field():
    result = extract_medicine_fields(
        {"raw_text": "Batch ID: AB-501", "lines": [{"text": "Batch ID: AB-501", "confidence": .95}]},
        {"detected": False},
    )
    assert result["batchNumber"] == "AB-501"


@pytest.mark.parametrize("mime,data,status", [
    ("text/plain", b"abc", 415),
    ("image/png", b"not an image", 415),
])
def test_scanner_rejects_invalid_upload(monkeypatch, mime, data, status):
    from app.routes import scanner
    async def run():
        file = UploadFile(filename="x.png", file=BytesIO(data), headers={"content-type": mime})
        with pytest.raises(HTTPException) as exc:
            await scanner.analyze_image(file, user={"node_id": "N1"})
        assert exc.value.status_code == status
    import asyncio
    asyncio.run(run())


def test_scanner_rejects_oversized_upload(monkeypatch):
    from app.routes import scanner
    monkeypatch.setattr(scanner, "MAX_IMAGE_BYTES", 3)
    async def run():
        file = UploadFile(filename="large.png", file=BytesIO(b"1234"), headers={"content-type": "image/png"})
        with pytest.raises(HTTPException) as exc:
            await scanner.analyze_image(file, user={"node_id": "N1"})
        assert exc.value.status_code == 413
    import asyncio
    asyncio.run(run())


def test_scanner_requires_confirmation_and_never_calls_restock(monkeypatch):
    from app.routes import scanner
    monkeypatch.setattr(scanner, "load_image", lambda data: object())
    monkeypatch.setattr(scanner, "detect_barcode", lambda image: {"detected": False, "gtin": None, "format": None, "valid_checksum": False})
    monkeypatch.setattr(scanner, "extract_text", lambda image: {"raw_text": SAMPLE, "lines": [{"text": line, "confidence": .9} for line in SAMPLE.splitlines()]})
    monkeypatch.setattr(scanner, "lookup_catalog", lambda gtin: None)
    async def run():
        file = UploadFile(filename="x.png", file=BytesIO(b"image"), headers={"content-type": "image/png"})
        result = await scanner.analyze_image(file, user={"node_id": "N1"})
        assert result["requires_confirmation"] is True
        assert result["barcode"]["detected"] is False
        assert result["gtin"] == {"detected": True, "value": "08901234567890", "format": "EAN13", "valid": True}
        assert result["gtin"]["value"] == "08901234567890"
        assert result["data"]["batchNumber"] == "AMX2025A01"
        assert result["data"]["unitPrice"] == 45
    import asyncio
    asyncio.run(run())


def test_scanner_keeps_ocr_working_when_no_barcode_is_detected(monkeypatch):
    from app.routes import scanner
    no_barcode_text = SAMPLE.replace("GTIN: 8901234567890\n", "")
    monkeypatch.setattr(scanner, "load_image", lambda data: object())
    monkeypatch.setattr(scanner, "detect_barcode", lambda image: {
        "detected": False, "value": None, "gtin": None, "format": None, "valid_checksum": None, "barcodes": []
    })
    monkeypatch.setattr(scanner, "extract_text", lambda image: {
        "raw_text": no_barcode_text,
        "lines": [{"text": line, "confidence": .9} for line in no_barcode_text.splitlines()],
    })
    monkeypatch.setattr(scanner, "lookup_catalog", lambda gtin: None)
    async def run():
        file = UploadFile(filename="x.png", file=BytesIO(b"image"), headers={"content-type": "image/png"})
        result = await scanner.analyze_image(file, user={"node_id": "N1"})
        assert result["success"] is True
        assert result["source"] == "paddleocr"
        assert result["barcode"]["detected"] is False
        assert result["gtin"]["value"] is None
        assert result["extracted"]["batch_number"] == "AMX2025A01"
    import asyncio
    asyncio.run(run())


def test_gemini_fallback_used_if_local_ocr_fails(monkeypatch):
    from app.routes import scanner
    monkeypatch.setattr(scanner, "load_image", lambda data: object())
    monkeypatch.setattr(scanner, "detect_barcode", lambda image: {"detected": False, "gtin": None, "format": None, "valid_checksum": False})
    def fail(*args): raise scanner.OCRUnavailable("unavailable")
    monkeypatch.setattr(scanner, "extract_text", fail)
    monkeypatch.setattr(scanner.settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(scanner, "extract_with_gemini", lambda *args: {
        "medicineName": "Medicine", "genericName": None, "manufacturer": None, "medicineId": None,
        "batchNumber": None, "manufacturingDate": None, "expiryDate": None, "gtin": None,
        "storageCondition": None, "source": "gemini", "confidence": .5,
    })
    async def run():
        file = UploadFile(filename="x.png", file=BytesIO(b"image"), headers={"content-type": "image/png"})
        result = await scanner.analyze_image(file, user={"node_id": "N1"})
        assert result["source"] == "gemini_fallback" and result["requires_confirmation"]
    import asyncio
    asyncio.run(run())
