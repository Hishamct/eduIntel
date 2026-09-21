import io

import pytesseract
from fastapi import HTTPException
from PIL import Image
from pypdf import PdfReader


def extract_text(file_bytes: bytes) -> dict:
    """
    Extracts text from an image using Tesseract OCR.

    """
    try:
        image = Image.open(io.BytesIO(file_bytes))
        text = pytesseract.image_to_string(image)

        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        confidences = [int(c) for c in data["conf"] if c != "-1"]
        avg_confidence = (
            (sum(confidences) / len(confidences) / 100) if confidences else None
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OCR engine error: {e!s}")

    return {
        "extracted_text": text.strip(),
        "confidence": avg_confidence,
    }


def extract_text_from_pdf(file_bytes: bytes) -> dict:
    """
    Extracts embedded text directly from a typed/digital PDF.
    Not OCR — assumes the PDF already contains real text layers,
    not scanned images. Fast and accurate when that assumption holds.
    """
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        text_parts = [page.extract_text() or "" for page in reader.pages]
        full_text = "\n".join(text_parts).strip()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"PDF extraction error: {e!s}")

    return {
        "extracted_text": full_text,
        "confidence": None,  # not applicable — this isn't a probabilistic OCR read
    }
