from pydantic import BaseModel


class OcrExtractResponse(BaseModel):
    extracted_text: str
    confidence: float | None = None
    engine: str = "tesseract"