"""Optional pyzbar decoder with conservative GTIN checksum validation."""
from __future__ import annotations

import re


_EMPTY = {
    "detected": False,
    "value": None,
    "gtin": None,
    "format": None,
    "valid_checksum": None,
    "barcodes": [],
}


def checksum_valid(value: str | None) -> bool:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) not in (8, 12, 13, 14):
        return False
    payload, check = digits[:-1], int(digits[-1])
    total = sum(int(digit) * (3 if index % 2 == 0 else 1)
                for index, digit in enumerate(reversed(payload)))
    return (10 - total % 10) % 10 == check


def _canonical_gtin(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    return digits.zfill(14) if checksum_valid(digits) else None


def parse_gtin_text(text: str | None) -> dict:
    """Validate a human-readable, explicitly labelled GTIN/EAN/UPC line."""
    match = re.search(
        r"(?im)\b(?:GTIN|EAN(?:\s*[- ]?13)?|UPC(?:\s*[- ]?A)?)\s*[:#=\-]?\s*([0-9\s-]{8,24})",
        text or "",
    )
    if not match:
        return {"detected": False, "gtin": None, "format": None, "valid_checksum": False}
    digits = re.sub(r"\D", "", match.group(1))
    valid = checksum_valid(digits)
    fmt = {8: "EAN8", 12: "UPCA", 13: "EAN13", 14: "GTIN14"}.get(len(digits), "GTIN")
    return {"detected": True, "value": digits, "gtin": digits.zfill(14) if valid else None,
            "format": fmt, "valid_checksum": valid}


def _variants(image) -> list:
    """Create grayscale variants while keeping the original resolution first."""
    try:
        import cv2
    except ImportError:
        return [image]

    if getattr(image, "ndim", 0) == 2:
        gray = image
    else:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    variants = [gray]
    height, width = gray.shape[:2]
    longest = max(height, width)
    if longest < 1800:
        scale = min(2.0, 1800 / longest)
        resized = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        variants.append(resized)
    elif longest > 2400:
        scale = 2400 / longest
        variants.append(cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA))

    # Barcode edges often decode better with both global and local binarization.
    try:
        variants.append(cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1])
    except Exception:
        pass
    try:
        variants.append(cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                              cv2.THRESH_BINARY, 31, 7))
    except Exception:
        pass
    return variants


def _text_gtin(raw: str, fmt: str) -> str | None:
    # GS1 Application Identifier 01 may be printed in human-readable or AIM form.
    gs1 = re.search(r"(?:\(01\)|\]C1?01|\b01)(\d{14})(?!\d)", raw)
    value = gs1.group(1) if gs1 else raw
    # Linear EAN/UPC symbols encode their product number directly. A QR/Code128
    # payload must be explicitly GTIN-shaped or contain the GS1 AI to be trusted.
    if not gs1 and fmt not in {"EAN13", "EAN8", "UPCA", "UPCE"}:
        if not re.fullmatch(r"\d{8}|\d{12,14}", value):
            return None
    return _canonical_gtin(value)


def detect_barcode(image) -> dict:
    """Decode common ZBar formats from an OpenCV image. Missing ZBar is non-fatal."""
    try:
        from pyzbar.pyzbar import decode
    except (ImportError, OSError):
        # On Windows pyzbar's Python package can be installed while its ZBar DLL
        # is absent. Barcode support is optional; OCR must still proceed.
        return dict(_EMPTY)

    try:
        import numpy as np
        variants = _variants(image)
        original_image = None
        try:
            import cv2
            from PIL import Image
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB) if getattr(image, "ndim", 0) == 3 else image
            original_image = Image.fromarray(rgb)
        except Exception:
            # Pillow conversion is optional; the original-resolution grayscale
            # variant is still attempted below.
            pass
        hits: dict[tuple[str, str], dict] = {}
        if original_image is not None:
            for code in decode(original_image):
                raw_bytes = getattr(code, "data", b"")
                raw = raw_bytes.decode("utf-8", errors="replace").strip() if isinstance(raw_bytes, bytes) else str(raw_bytes).strip()
                code_type = str(getattr(code, "type", "UNKNOWN")).upper().replace("_", "")
                format_name = {"EAN13": "EAN13", "EAN8": "EAN8", "UPCA": "UPCA",
                               "UPCE": "UPCE", "CODE128": "CODE128", "QRCODE": "QR"}.get(code_type, code_type)
                if raw:
                    gtin = _text_gtin(raw, format_name)
                    digits = re.sub(r"\D", "", raw)
                    checksum_applies = format_name in {"EAN13", "EAN8", "UPCA", "UPCE"} and len(digits) in (8, 12, 13, 14)
                    hits[(raw, format_name)] = {"value": raw, "gtin": gtin, "format": format_name,
                                                "valid_checksum": bool(gtin) if checksum_applies or gtin else None}
        for variant in variants:
            height, width = variant.shape[:2]
            # pyzbar accepts a (bytes, width, height) greyscale image tuple.
            for code in decode((np.ascontiguousarray(variant).tobytes(), width, height)):
                raw_bytes = getattr(code, "data", b"")
                raw = raw_bytes.decode("utf-8", errors="replace").strip() if isinstance(raw_bytes, bytes) else str(raw_bytes).strip()
                code_type = str(getattr(code, "type", "UNKNOWN")).upper().replace("_", "")
                format_name = {"EAN13": "EAN13", "EAN8": "EAN8", "UPCA": "UPCA",
                               "UPCE": "UPCE", "CODE128": "CODE128", "QRCODE": "QR"}.get(code_type, code_type)
                if not raw:
                    continue
                key = (raw, format_name)
                if key not in hits:
                    gtin = _text_gtin(raw, format_name)
                    # Invalid check digits on EAN/UPC identify an unreadable or
                    # damaged value, so never use it for catalog lookup.
                    linear_gtin = format_name in {"EAN13", "EAN8", "UPCA", "UPCE"}
                    digits = re.sub(r"\D", "", raw)
                    checksum_applies = linear_gtin and len(digits) in (8, 12, 13, 14)
                    valid = bool(gtin)
                    hits[key] = {"value": raw, "gtin": gtin, "format": format_name,
                                 "valid_checksum": valid if checksum_applies or gtin else None}
        barcodes = list(hits.values())
        if not barcodes:
            return dict(_EMPTY)
        # Prefer the first validated product identifier for catalog matching;
        # otherwise preserve the first decoded value for review/diagnostics.
        chosen = next((item for item in barcodes if item["valid_checksum"]), barcodes[0])
        return {"detected": True, **chosen, "barcodes": barcodes}
    except (ImportError, OSError):
        return dict(_EMPTY)
    except Exception:
        # A barcode decoder failure must never block OCR.
        return dict(_EMPTY)
