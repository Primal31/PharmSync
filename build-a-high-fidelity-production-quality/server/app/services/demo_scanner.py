"""Exact-image lookup for the six synthetic PharmSync demo package labels.

This is a deterministic demo adapter, not OCR. It only recognizes the shipped
sample PNGs by SHA-256 and returns their authored manifest data.
"""
from __future__ import annotations

import hashlib


_DEMO_LABELS = {
    "4aef856da9c1b5aeeaa65d92a3f26f3628d1d84f60a0ac53e1b1c6ded61a21c2": {
        "medicine_id": "DEMO-ATOR10", "gtin": "8901000000019", "medicine_name": "Atorvastatin 10 mg",
        "generic_name": "Atorvastatin", "strength": "10 mg", "dosage_form": "Tablet", "batch_number": "AB-501",
        "manufacture_date": "2025-12-01", "expiry_date": "2027-11-30", "unit_price": 85.0, "quantity": 40,
    },
    "65944df26d21e1f4ee77f62a74adf094f987c285af91f8a9ce4953bcc2d2a479": {
        "medicine_id": "DEMO-MET850", "gtin": "8901000000026", "medicine_name": "Metformin 850 mg",
        "generic_name": "Metformin", "strength": "850 mg", "dosage_form": "Tablet", "batch_number": "MFB-401",
        "manufacture_date": "2026-02-01", "expiry_date": "2030-01-31", "unit_price": 32.0, "quantity": 60,
    },
    "7ec13888f4a7bcf6523832a235c6e9a9db11f1b3b595f5f2cd80324dc3aedeec": {
        "medicine_id": "DEMO-OME20", "gtin": "8901000000033", "medicine_name": "Omeprazole 20 mg",
        "generic_name": "Omeprazole", "strength": "20 mg", "dosage_form": "Capsule", "batch_number": "OB-301",
        "manufacture_date": "2026-07-01", "expiry_date": "2029-06-30", "unit_price": 48.0, "quantity": 35,
    },
    # The original Paracetamol attachment and the generated annotated sample both
    # use this corrected synthetic batch record for demo repeatability.
    "c377c37388694f7bf14287b5b403023f78ba628c2d6e280b664693401a6f9f93": {
        "medicine_id": "PARA-BATCH-2", "gtin": "8901000000040", "medicine_name": "Paracetamol 500 mg",
        "generic_name": "Paracetamol", "strength": "500 mg", "dosage_form": "Tablet", "batch_number": "PCB-2",
        "manufacture_date": "2025-12-09", "expiry_date": "2028-12-31", "unit_price": 18.0, "quantity": 80,
    },
    "2bf8151d950df026fd81ab4efdb8ebe5b4976d163e35fb52db05f7ab159ab6fd": {
        "medicine_id": "PARA-BATCH-2", "gtin": "8901000000040", "medicine_name": "Paracetamol 500 mg",
        "generic_name": "Paracetamol", "strength": "500 mg", "dosage_form": "Tablet", "batch_number": "PCB-2",
        "manufacture_date": "2025-12-09", "expiry_date": "2028-12-31", "unit_price": 18.0, "quantity": 80,
    },
    "e8fc36fefc7857e7ff4a3fc91e88cf988a5c28960bda7501b624c2ca7243edd8": {
        "medicine_id": "DEMO-IBU200", "gtin": "8901000000057", "medicine_name": "Ibuprofen 200 mg",
        "generic_name": "Ibuprofen", "strength": "200 mg", "dosage_form": "Tablet", "batch_number": "IBB-101",
        "manufacture_date": "2025-04-01", "expiry_date": "2027-03-31", "unit_price": 22.0, "quantity": 32,
    },
    "9989aed7553d9afb2feabf9e5a4b55c062f161ac03eaa4566fb40024e392aadd": {
        "medicine_id": "AMOX-BATCH-001", "gtin": "8901000000064", "medicine_name": "Amoxicillin 500 mg",
        "generic_name": "Amoxicillin", "strength": "500 mg", "dosage_form": "Capsule", "batch_number": "H-AMB-001",
        "manufacture_date": "2020-10-26", "expiry_date": "2026-10-31", "unit_price": 64.0, "quantity": 20,
    },
    "30b732e804df3f3aa69c2318b2130787d632c4080af2248d4c45068fb23a38d2": {
        "medicine_id": "AMOX-BATCH-001", "gtin": "8901000000064", "medicine_name": "Amoxicillin 500 mg",
        "generic_name": "Amoxicillin", "strength": "500 mg", "dosage_form": "Capsule", "batch_number": "H-AMB-001",
        "manufacture_date": "2020-10-26", "expiry_date": "2026-10-31", "unit_price": 64.0, "quantity": 20,
    },
}


def lookup_demo_image(image_bytes: bytes) -> dict | None:
    """Return a copy of an authored demo record for an exact known image only."""
    record = _DEMO_LABELS.get(hashlib.sha256(image_bytes).hexdigest())
    if record is None:
        return None
    return dict(record)


def format_demo_response(record: dict) -> dict:
    """Shape predefined demo data like the normal scanner API response."""
    gtin = record["gtin"]
    fields = {
        "medicineName": record["medicine_name"], "genericName": record["generic_name"],
        "manufacturer": None, "medicineId": record["medicine_id"], "strength": record["strength"],
        "dosageForm": record["dosage_form"], "batchNumber": record["batch_number"],
        "manufacturingDate": record["manufacture_date"], "expiryDate": record["expiry_date"],
        "gtin": gtin.zfill(14), "storageCondition": "Unknown", "barcode": gtin,
        "source": "predefined_demo", "unitPrice": record["unit_price"], "confidence": 0,
        "missingFields": ["manufacturer", "storageCondition"],
        "warnings": ["Predefined synthetic demo data matched by exact sample-image fingerprint; not live OCR.",
                     "Expiry month/year values are normalized to the last calendar day for the date input."],
    }
    return {
        "success": True, "source": "predefined_demo",
        "barcode": {"detected": True, "value": gtin, "format": "EAN13", "valid_checksum": True, "barcodes": []},
        "gtin": {"detected": True, "value": gtin.zfill(14), "format": "EAN13", "valid": True},
        "catalog_match": {"found": record["medicine_id"] in {"PARA-BATCH-2", "AMOX-BATCH-001"}},
        "extracted": {"medicine_name": record["medicine_name"], "generic_name": record["generic_name"],
            "manufacturer": None, "medicine_id": record["medicine_id"], "strength": record["strength"],
            "dosage_form": record["dosage_form"], "batch_number": record["batch_number"],
            "manufacture_date": record["manufacture_date"], "expiry_date": record["expiry_date"],
            "unit_price": record["unit_price"], "quantity": record["quantity"], "storage_type": "Unknown",
            "gtin": gtin.zfill(14), "barcode": gtin},
        "confidence": {"overall": 0}, "requires_confirmation": True, "data": fields,
        "demo_quantity": record["quantity"],
    }
