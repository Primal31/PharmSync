"""Lazy CPU PaddleOCR with in-memory OpenCV preprocessing."""
from __future__ import annotations

import io
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
MAX_IMAGE_PIXELS = 36_000_000
MAX_SIDE = 2200
_engine: Any = None
_engine_lock = threading.Lock()
_inference_lock = threading.Lock()


class OCRUnavailable(RuntimeError):
    """OpenCV/PaddleOCR could not be loaded or run."""


def load_image(source: bytes | bytearray | str | Path | io.BufferedIOBase):
    """Decode a real supported image to BGR; never trusts the filename."""
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise OCRUnavailable("OpenCV is not installed") from exc

    if isinstance(source, (str, Path)):
        raw = np.fromfile(str(source), dtype=np.uint8)
    elif hasattr(source, "read"):
        raw = np.frombuffer(source.read(), dtype=np.uint8)
    else:
        raw = np.frombuffer(bytes(source), dtype=np.uint8)
    if raw.size == 0:
        raise ValueError("The image is empty.")
    image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("The selected file is not a readable image.")
    height, width = image.shape[:2]
    if height < 2 or width < 2 or height * width > MAX_IMAGE_PIXELS:
        raise ValueError("Image dimensions are not supported. Choose a smaller image.")
    # Correct EXIF orientation when Pillow is available. Some camera images rely on it.
    try:
        from PIL import Image, ImageOps
        exif_image = ImageOps.exif_transpose(Image.open(io.BytesIO(raw.tobytes())))
        if exif_image.size != (width, height) or exif_image.getexif():
            image = cv2.cvtColor(np.asarray(exif_image.convert("RGB")), cv2.COLOR_RGB2BGR)
    except Exception:
        pass
    return image


def _get_engine():
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                try:
                    from paddleocr import PaddleOCR
                    _engine = PaddleOCR(
                        lang="en", device="cpu", cpu_threads=4,
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                        text_detection_model_name="PP-OCRv5_mobile_det",
                        text_recognition_model_name="en_PP-OCRv5_mobile_rec",
                    )
                except Exception as exc:
                    raise OCRUnavailable("PaddleOCR could not be initialized") from exc
    return _engine


def _lines_from_result(result: Any) -> list[dict]:
    lines: list[dict] = []
    if isinstance(result, (list, tuple)):
        items = result
    elif isinstance(result, dict) or hasattr(result, "json"):
        items = [result]
    else:
        try: items = list(result)
        except TypeError: items = [result]
    for item in items:
        payload = item
        if hasattr(payload, "json"):
            payload = payload.json
            if callable(payload): payload = payload()
        if isinstance(payload, dict) and isinstance(payload.get("res"), dict):
            payload = payload["res"]
        if isinstance(payload, dict):
            texts = payload.get("rec_texts") or payload.get("texts") or []
            scores = payload.get("rec_scores") or payload.get("scores") or []
            for index, text in enumerate(texts):
                clean = str(text).strip()
                if clean:
                    try: confidence = float(scores[index])
                    except (IndexError, TypeError, ValueError): confidence = 0.0
                    lines.append({"text": clean, "confidence": max(0.0, min(1.0, confidence))})
            continue
        # PaddleOCR 2.x compatibility: [[box, (text, score)], ...]
        if isinstance(payload, list):
            for row in payload:
                if isinstance(row, (tuple, list)) and len(row) > 1 and isinstance(row[1], (tuple, list)):
                    text, score = row[1][0], row[1][1] if len(row[1]) > 1 else 0.0
                    clean = str(text).strip()
                    if clean:
                        try: confidence = float(score)
                        except (TypeError, ValueError): confidence = 0.0
                        lines.append({"text": clean, "confidence": max(0.0, min(1.0, confidence))})
    return lines


def _preprocess(image):
    import cv2
    height, width = image.shape[:2]
    scale = min(1.0, MAX_SIDE / max(height, width))
    if scale < 1.0:
        image = cv2.resize(image, (max(2, int(width * scale)), max(2, int(height * scale))), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    light, a, b = cv2.split(lab)
    light = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(light)
    contrast = cv2.cvtColor(cv2.merge((light, a, b)), cv2.COLOR_LAB2BGR)
    denoised = cv2.bilateralFilter(contrast, 5, 35, 35)
    blur = cv2.GaussianBlur(denoised, (0, 0), 1.1)
    sharpened = cv2.addWeighted(denoised, 1.45, blur, -0.45, 0)
    return image, sharpened


def extract_text(image_or_source) -> dict:
    """Return raw text and confidence-scored lines from one or two image variants."""
    import cv2
    image = image_or_source if hasattr(image_or_source, "shape") else load_image(image_or_source)
    variants = _preprocess(image)
    engine = _get_engine()
    best: list[dict] = []
    with _inference_lock:
        for variant in variants:
            try:
                if hasattr(engine, "predict"):
                    result = engine.predict(input=variant)
                else:
                    result = engine.ocr(variant, cls=False)
                lines = _lines_from_result(result)
                if len(lines) > len(best) or (len(lines) == len(best) and sum(x["confidence"] for x in lines) > sum(x["confidence"] for x in best)):
                    best = lines
                if len(best) >= 5:
                    break
            except Exception as exc:
                logger.warning("PaddleOCR image variant failed (%s)", type(exc).__name__)
    return {"raw_text": "\n".join(line["text"] for line in best), "lines": best}
