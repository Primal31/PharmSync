"""Conservative package text parsing and catalog enrichment."""
from __future__ import annotations
from calendar import monthrange
from datetime import date
import re

_DATE = r"(?:\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{1,2}[./-]\d{4})"


def _labeled_value(text: str, label: str) -> str | None:
    match = re.search(rf"(?im)^\s*(?:{label})\s*[:#=\-]?\s*([^\r\n]+)", text)
    if not match: return None
    value = re.split(r"\s{2,}|\s+(?:MRP|M\.R\.P|MFG|MFD|EXP|EXPIRY|BATCH)\s*[:#=\-]", match.group(1), maxsplit=1, flags=re.I)[0]
    value = value.strip(" \t:;#.-")
    return value or None


def _date_value(text: str, labels: str, expiry: bool) -> tuple[str | None, str | None]:
    match = re.search(rf"(?im)(?:{labels})\s*(?:DATE)?\s*[:#=\-]?\s*({_DATE})", text)
    if not match: return None, None
    raw = match.group(1).replace(".", "/").replace("-", "/")
    parts = raw.split("/")
    try:
        if len(parts) == 2:
            month, year = int(parts[0]), int(parts[1])
            if year < 100: year += 2000
            if not 1 <= month <= 12: return None, None
            day = monthrange(year, month)[1] if expiry else 1
            warning = f"Month/year date {raw} normalized to {year:04d}-{month:02d}-{day:02d}."
            return date(year, month, day).isoformat(), warning
        if len(parts) == 3 and len(parts[0]) == 4:
            year, month, day = map(int, parts)
        elif len(parts) == 3:
            first, second, year = map(int, parts)
            if year < 100: year += 2000
            # India medicine labels commonly use DD/MM/YYYY. When one order is
            # impossible, accept the unambiguous month/day order and disclose it.
            if first > 12: day, month = first, second
            elif second > 12: month, day = first, second
            else: day, month = first, second
        else: return None, None
        return date(year, month, day).isoformat(), None
    except (ValueError, OverflowError):
        return None, None


def _extract(lines: list[dict], raw_text: str, gtin: dict, catalog: dict | None) -> dict:
    text = "\n".join(line["text"] for line in lines) if lines else (raw_text or "")
    batch = _labeled_value(text, r"(?:BATCH(?:\s*(?:NO\.?|NUMBER|ID))?|B\.?\s*NO\.?|LOT(?:\s*(?:NO\.?|NUMBER))?)")
    if batch and re.sub(r"\D", "", batch) in {re.sub(r"\D", "", gtin.get("gtin") or ""), re.sub(r"\D", "", (gtin.get("gtin") or "").lstrip("0"))}:
        batch = None
    manufacture, mfg_warning = _date_value(text, r"(?:MFG|MFD|MFG\.?\s*DATE|MANUFACT(?:URED|URING))", False)
    expiry, exp_warning = _date_value(text, r"(?:EXP|EXPIRY|EXPIRES?|USE\s*BEFORE)", True)
    price_match = re.search(r"(?i)(?:M\s*\.?\s*R\s*\.?\s*P\s*\.?|MAX(?:IMUM)?\s+RETAIL\s+PRICE)\s*[:#=\-]?\s*(?:₹|INR\s*|RS\.?\s*)?([0-9][0-9,]*(?:\.\d{1,2})?)", text)
    if not price_match:
        price_match = re.search(r"(?:₹|\bINR\s*|\bRs\.?\s*)([0-9][0-9,]*(?:\.\d{1,2})?)", text, re.I)
    unit_price = None
    if price_match:
        try: unit_price = float(price_match.group(1).replace(",", ""))
        except ValueError: pass

    strength_match = re.search(r"(?i)\b\d+(?:\.\d+)?\s?(?:mg|mcg|μg|g|ml|%|iu)\b", text)
    strength = strength_match.group(0).strip() if strength_match else None
    form_match = re.search(r"(?i)\b(capsules?|tablets?|syrups?|suspensions?|solutions?|injections?|drops?|ointments?|creams?|powders?|inhalers?|sprays?)\b", text)
    form = form_match.group(1).lower().rstrip("s") if form_match else None
    if form == "capsule": form = "Capsule"
    elif form == "tablet": form = "Tablet"
    elif form: form = form.title()

    generic = _labeled_value(text, r"(?:GENERIC(?:\s*NAME)?|COMPOSITION|EACH\s+(?:CAPSULE|TABLET)\s+CONTAINS)")
    if generic and strength:
        generic = re.sub(re.escape(strength), "", generic, flags=re.I).strip(" :-,;") or None
    medicine_name = _labeled_value(text, r"(?:MEDICINE|PRODUCT|BRAND)\s*NAME")
    if not medicine_name:
        excluded = re.compile(r"(?i)(?:BATCH|LOT|MFG|MFD|EXP|EXPIRY|MRP|PRICE|GTIN|EAN|UPC|STORE|STORAGE|KEEP|COMPOSITION|GENERIC|\b\d{1,2}[./-]\d{2,4}\b)")
        for line in text.splitlines():
            value = line.strip()
            has_product_context = re.search(r"(?i)\b(capsules?|tablets?|syrups?|suspensions?|solutions?|injections?|drops?|ointments?|creams?|powders?|inhalers?|sprays?|\d+(?:\.\d+)?\s?(?:mg|mcg|μg|g|ml|iu))\b", value)
            if len(value) < 3 or not re.search(r"[A-Za-z]{3}", value) or excluded.search(value) or not has_product_context: continue
            medicine_name = re.sub(r"(?i)\b(?:CAPSULES?|TABLETS?|SYRUPS?|IP|USP|BP)\b", " ", value)
            medicine_name = re.sub(r"\s+", " ", medicine_name).strip(" -:;,. ") or None
            if medicine_name: break
    if medicine_name and strength and strength.casefold() not in medicine_name.casefold():
        medicine_name = f"{medicine_name} {strength}"
    manufacturer = _labeled_value(text, r"(?:MANUFACTURER|MFR|MFD\s*BY)")
    lower = text.casefold()
    if re.search(r"room\s+temperature|below\s+(?:25|30)\s*°?\s*c", lower): storage = "Ambient Room Temperature"
    elif re.search(r"keep\s+refrigerated|store\s+between\s+2\s*(?:-|to)\s*8\s*°?\s*c", lower): storage = "Cold Chain"
    else: storage = None

    if catalog:
        medicine_id = catalog.get("medicine_id")
        medicine_name = catalog.get("medicine_name") or medicine_name
        generic = catalog.get("generic_name") or generic
        manufacturer = catalog.get("manufacturer") or manufacturer
        strength = catalog.get("strength") or strength
        form = catalog.get("dosage_form") or form
    else:
        medicine_id = "GTIN-" + gtin["gtin"] if gtin.get("valid_checksum") and gtin.get("gtin") else None

    warnings = []
    if mfg_warning: warnings.append("Manufacture month/year was normalized to the first day of that month.")
    if exp_warning: warnings.append("Expiry month/year was normalized to the last day of that month.")
    if gtin.get("detected") and not gtin.get("valid_checksum"): warnings.append("A code was detected, but it failed GTIN checksum validation and was not used for catalog lookup.")
    fields = {"medicineName": medicine_name, "genericName": generic, "manufacturer": manufacturer,
        "medicineId": medicine_id, "batchNumber": batch, "manufacturingDate": manufacture,
        "expiryDate": expiry, "gtin": gtin.get("gtin") if gtin.get("valid_checksum") else None,
        "storageCondition": storage, "strength": strength, "dosageForm": form, "unitPrice": unit_price}
    fields["missingFields"] = [key for key in ("medicineName", "medicineId", "batchNumber", "manufacturingDate", "expiryDate", "unitPrice") if fields.get(key) is None]
    confidences = [max(0.0, min(1.0, float(line.get("confidence", 0)))) for line in lines]
    fields["confidence"] = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
    fields["warnings"] = warnings
    return fields


def extract_medicine_fields(ocr_result: dict, gtin: dict, catalog: dict | None = None) -> dict:
    return _extract(ocr_result.get("lines") or [], ocr_result.get("raw_text") or "", gtin, catalog)
