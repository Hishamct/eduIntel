import asyncio
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.ocr import service
from app.ocr.schemas import OcrExtractResponse
from app.users.dependencies import require_role
from app.users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ocr", tags=["ocr"])

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
CHUNK_SIZE = 64 * 1024  # 64 KB

# Process-local semaphore: bounds simultaneous OCR tasks within this worker process
ocr_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_OCR_WORKERS)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/png": "image/png",
    "image/webp": "image/webp",
}


def validate_image_signature(normalized_content_type: str, data: bytes) -> bool:
    """
    Validates magic byte signatures for supported image formats.
    """
    if normalized_content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if normalized_content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if normalized_content_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


@router.post("/extract", response_model=OcrExtractResponse)
async def extract_text_from_image(
    file: UploadFile = File(...),
    current_user: User = Depends(require_role("teacher", "admin")),
):
    """
    Extracts text from an image using Tesseract OCR with security safeguards:
    - Authentication and role authorization (teacher, admin).
    - Streaming 5 MB file size limit enforcement.
    - Content-type and magic byte signature verification.
    - Pillow structural verification and decompression bomb prevention.
    - Process-local concurrency bounded by semaphore.
    - Blocking OCR execution delegated to worker thread pool.
    - Guaranteed file descriptor and temporary file cleanup on all exit paths.
    """
    try:
        content_type = (file.content_type or "").lower().strip()
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Unsupported image type: '{file.content_type}'. "
                    "Allowed formats: image/jpeg, image/png, image/webp."
                ),
            )
        normalized_type = ALLOWED_CONTENT_TYPES[content_type]

        # Enforce streaming byte count limit
        file_bytes = bytearray()
        while chunk := await file.read(CHUNK_SIZE):
            file_bytes.extend(chunk)
            if len(file_bytes) > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="File size exceeds maximum permitted 5 MB limit.",
                )

        if not file_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty file submitted.",
            )

        # Validate file magic bytes
        if not validate_image_signature(normalized_type, bytes(file_bytes)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File content does not match reported image format.",
            )

        # Process-local bounded concurrency semaphore + threadpool execution
        async with ocr_semaphore:
            result = await run_in_threadpool(service.extract_text, bytes(file_bytes))
    finally:
        await file.close()

    return OcrExtractResponse(
        extracted_text=result["extracted_text"],
        confidence=result["confidence"],
        engine="tesseract",
    )
