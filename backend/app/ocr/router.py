from fastapi import APIRouter, UploadFile, File, HTTPException
from app.ocr.schemas import OcrExtractResponse
from app.ocr import service

router = APIRouter(prefix="/ocr", tags=["ocr"])

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/jpg", "image/webp"}


@router.post("/extract", response_model=OcrExtractResponse)
async def extract_text_from_image(file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Use JPEG, PNG, or WebP."
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    result = service.extract_text(file_bytes)

    return OcrExtractResponse(
        extracted_text=result["extracted_text"],
        confidence=result["confidence"],
    )