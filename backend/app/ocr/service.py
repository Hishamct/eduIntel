import io
import logging
import warnings

import pytesseract
from fastapi import HTTPException, status
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

logger = logging.getLogger(__name__)

MAX_PIXELS = 16_000_000  # 16 Megapixels
MAX_DIM = 4096  # 4096 px width/height
TESSERACT_TIMEOUT_SECONDS = 10


def extract_text(file_bytes: bytes) -> dict:
    """
    Extracts text from an image using Tesseract OCR with security safeguards:
    - Pillow decompression bomb protection scoped via catch_warnings.
    - Dimension verification (max 4096 x 4096 px).
    - Image integrity verification via image.verify().
    - PyTesseract execution timeout enforcement.
    - Explicit resource cleanup in finally block.
    - Sanitized client error responses.
    """
    image = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            Image.MAX_IMAGE_PIXELS = MAX_PIXELS

            try:
                image = Image.open(io.BytesIO(file_bytes))
                image.verify()
            except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image pixel count exceeds decompression limit ({MAX_PIXELS} pixels).",
                ) from e
            except (UnidentifiedImageError, SyntaxError, ValueError) as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Corrupted or invalid image content.",
                ) from e

            # Re-open after verify() as required by Pillow
            image.close()
            image = Image.open(io.BytesIO(file_bytes))

            # Check total pixel count and dimensions
            total_pixels = image.width * image.height
            if total_pixels > MAX_PIXELS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Image pixel count ({total_pixels}) exceeds maximum allowed {MAX_PIXELS} pixels.",
                )

            if image.width > MAX_DIM or image.height > MAX_DIM:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Image dimensions ({image.width}x{image.height}) "
                        f"exceed maximum allowed {MAX_DIM}x{MAX_DIM} px."
                    ),
                )

            text = pytesseract.image_to_string(image, timeout=TESSERACT_TIMEOUT_SECONDS)
            data = pytesseract.image_to_data(
                image, output_type=pytesseract.Output.DICT, timeout=TESSERACT_TIMEOUT_SECONDS
            )
            confidences = [int(c) for c in data.get("conf", []) if c != "-1"]
            avg_confidence = (
                (sum(confidences) / len(confidences) / 100) if confidences else None
            )
    except HTTPException:
        raise
    except RuntimeError as te:
        if "timeout" in str(te).lower():
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"OCR processing timed out (exceeded {TESSERACT_TIMEOUT_SECONDS} seconds).",
            ) from te
        logger.error("OCR engine runtime error: %s", str(te))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OCR engine runtime failure. Please try again or contact system support.",
        ) from te
    except Exception as e:
        logger.error("OCR engine failure | error_type=%s: %s", type(e).__name__, str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OCR engine failure. Please try again or contact system support.",
        ) from e
    finally:
        if image is not None:
            try:
                image.close()
            except Exception:
                pass

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
        logger.error("PDF extraction failure: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PDF text extraction failed. Please try again or contact system support.",
        ) from e

    return {
        "extracted_text": full_text,
        "confidence": None,
    }
