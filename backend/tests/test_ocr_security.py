"""
backend/tests/test_ocr_security.py

Comprehensive test suite verifying SEC-05 remediation:
- Mandatory authentication on POST /ocr/extract (HTTP 401 Unauthorized for anonymous).
- Role-based authorization: restricted to teacher and admin (HTTP 403 Forbidden for students).
- Streaming upload size enforcement (5 MB limit aborts with HTTP 413 Payload Too Large).
- File format and magic byte signature verification (JPEG, PNG, WebP vs spoofed files).
- Pillow integrity verification and corrupted image rejection (HTTP 400 Bad Request).
- Decompression bomb prevention via Image.MAX_IMAGE_PIXELS and pixel caps (HTTP 400).
- Image dimension limits (max 4096 x 4096 px) (HTTP 400).
- Process-local concurrency bounded by asyncio.Semaphore (MAX_CONCURRENT_OCR_WORKERS).
- PyTesseract execution timeout enforcement (HTTP 504 Gateway Timeout).
- Engine runtime failure handling (HTTP 502 Bad Gateway).
- File descriptor and temporary file cleanup on both success and failure paths.

TEST EXECUTION ENVIRONMENT NOTE:
These automated unit and route-contract tests utilize FastAPI ASGITransport with
dependency injection overrides (`app.dependency_overrides`) and in-memory test images.
They verify route authorization guards, streaming byte enforcement, Pillow verification,
and error handling without mutating active database records. Live PostgreSQL integration
testing with a disposable test database is formally scheduled for Phase 4.
"""
import asyncio
import io
import threading
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from starlette.datastructures import UploadFile

from app.auth.security import create_access_token, hash_password
from app.core.config import settings
from app.main import app
from app.users.dependencies import get_current_user
from app.users.models import User


def create_mock_user(role: str, user_id: uuid.UUID | None = None) -> User:
    uid = user_id or uuid.uuid4()
    return User(
        id=uid,
        email=f"user_{role}_{uid.hex[:6]}@example.com",
        name=f"Mock {role.capitalize()}",
        hashed_password=hash_password("MockPass123!"),
        role=role,
        is_active=True,
    )


def make_auth_header(user: User) -> dict:
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": f"Bearer {token}"}


def make_test_image_bytes(format_name: str = "PNG", size: tuple[int, int] = (100, 100), color: str = "white") -> bytes:
    """Generates valid image bytes for tests."""
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format=format_name)
    return buf.getvalue()


class TestOcrAuthenticationAndAuthorization:
    @pytest.mark.asyncio
    async def test_ocr_unauthenticated_rejected_with_401(self):
        """Verifies unauthenticated callers receive 401 Unauthorized."""
        png_data = make_test_image_bytes("PNG")
        files = {"file": ("test.png", png_data, "image/png")}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/ocr/extract", files=files)
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_ocr_student_role_rejected_with_403(self):
        """Verifies authenticated students receive 403 Forbidden."""
        student_user = create_mock_user("student")
        app.dependency_overrides[get_current_user] = lambda: student_user

        png_data = make_test_image_bytes("PNG")
        files = {"file": ("test.png", png_data, "image/png")}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student_user)
                resp = await client.post("/ocr/extract", files=files, headers=headers)
                assert resp.status_code == 403
                assert "requires one of these roles: teacher, admin" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ocr_teacher_role_authorized(self):
        """Verifies authenticated teachers are authorized to invoke OCR."""
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        png_data = make_test_image_bytes("PNG")
        files = {"file": ("test.png", png_data, "image/png")}
        mock_result = {"extracted_text": "Sample Lecture Notes", "confidence": 0.95}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                with patch("app.ocr.service.extract_text", return_value=mock_result):
                    resp = await client.post("/ocr/extract", files=files, headers=headers)
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["extracted_text"] == "Sample Lecture Notes"
                    assert data["confidence"] == 0.95
                    assert data["engine"] == "tesseract"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ocr_admin_role_authorized(self):
        """Verifies authenticated administrators are authorized to invoke OCR."""
        admin_user = create_mock_user("admin")
        app.dependency_overrides[get_current_user] = lambda: admin_user

        png_data = make_test_image_bytes("PNG")
        files = {"file": ("test.png", png_data, "image/png")}
        mock_result = {"extracted_text": "Official Institutional Document", "confidence": 0.99}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)
                with patch("app.ocr.service.extract_text", return_value=mock_result):
                    resp = await client.post("/ocr/extract", files=files, headers=headers)
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["extracted_text"] == "Official Institutional Document"
                    assert data["confidence"] == 0.99
        finally:
            app.dependency_overrides.clear()


class TestOcrUploadValidationAndMagicBytes:
    @pytest.mark.asyncio
    async def test_ocr_unsupported_content_type_rejected_with_400(self):
        """Verifies files with non-image MIME types are rejected with 400 Bad Request."""
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        files = {"file": ("document.pdf", b"%PDF-1.4 mock pdf data", "application/pdf")}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                resp = await client.post("/ocr/extract", files=files, headers=headers)
                assert resp.status_code == 400
                assert "Unsupported image type" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ocr_empty_file_rejected_with_400(self):
        """Verifies 0-byte file submission returns 400 Bad Request."""
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        files = {"file": ("empty.png", b"", "image/png")}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                resp = await client.post("/ocr/extract", files=files, headers=headers)
                assert resp.status_code == 400
                assert "Empty file" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ocr_spoofed_magic_bytes_rejected_with_400(self):
        """
        Verifies that a text file renamed with .png extension and sent with
        image/png MIME type is rejected by the magic bytes signature validator.
        """
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        # Malicious text script spoofed as PNG
        spoofed_data = b"echo 'Malicious shell payload disguised as image'"
        files = {"file": ("exploit.png", spoofed_data, "image/png")}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                resp = await client.post("/ocr/extract", files=files, headers=headers)
                assert resp.status_code == 400
                assert "File content does not match reported image format" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ocr_corrupted_image_rejected_with_400(self):
        """
        Verifies that a file possessing valid PNG header bytes but corrupted
        internal structure fails Pillow verification and returns 400 Bad Request.
        """
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        # Starts with valid PNG header, but truncated garbage data follows
        corrupted_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"truncated corrupted bytes"
        files = {"file": ("corrupted.png", corrupted_png, "image/png")}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                resp = await client.post("/ocr/extract", files=files, headers=headers)
                assert resp.status_code == 400
                assert "Corrupted or invalid image content" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ocr_valid_jpeg_format_success(self):
        """Verifies valid JPEG image passes signature validation and extracts text."""
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        jpeg_data = make_test_image_bytes("JPEG")
        files = {"file": ("photo.jpg", jpeg_data, "image/jpeg")}
        mock_result = {"extracted_text": "JPEG Scanned Document", "confidence": 0.92}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                with patch("app.ocr.service.extract_text", return_value=mock_result):
                    resp = await client.post("/ocr/extract", files=files, headers=headers)
                    assert resp.status_code == 200
                    assert resp.json()["extracted_text"] == "JPEG Scanned Document"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ocr_valid_webp_format_success(self):
        """Verifies valid WebP image passes signature validation and extracts text."""
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        webp_data = make_test_image_bytes("WEBP")
        files = {"file": ("photo.webp", webp_data, "image/webp")}
        mock_result = {"extracted_text": "WebP Extracted Text", "confidence": 0.88}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                with patch("app.ocr.service.extract_text", return_value=mock_result):
                    resp = await client.post("/ocr/extract", files=files, headers=headers)
                    assert resp.status_code == 200
                    assert resp.json()["extracted_text"] == "WebP Extracted Text"
        finally:
            app.dependency_overrides.clear()


class TestOcrFileLimitsAndStreaming:
    @pytest.mark.asyncio
    async def test_ocr_streaming_file_exceeding_5mb_rejected_with_413(self):
        """
        Verifies that an image upload exceeding 5 MB is aborted immediately
        while streaming chunks and returns HTTP 413 Payload Too Large.
        """
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        # 5 MB + 1024 bytes (exceeds 5 * 1024 * 1024)
        oversized_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024 + 1024)
        files = {"file": ("massive.png", oversized_data, "image/png")}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                resp = await client.post("/ocr/extract", files=files, headers=headers)
                assert resp.status_code == 413
                assert "exceeds maximum permitted 5 MB limit" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()


class TestOcrDecompressionBombAndDimensionCaps:
    def test_ocr_warning_filter_is_safely_scoped_without_global_leakage(self):
        """
        Verifies that Pillow decompression bomb filter configuration is scoped
        safely with catch_warnings and does not mutate global warning filters.
        """
        import warnings

        filters_before = list(warnings.filters)
        valid_png = make_test_image_bytes("PNG")

        with patch("pytesseract.image_to_string", return_value="dummy"):
            with patch("pytesseract.image_to_data", return_value={"conf": ["95"]}):
                from app.ocr import service

                service.extract_text(valid_png)

        filters_after = list(warnings.filters)
        assert filters_before == filters_after

    @pytest.mark.asyncio
    async def test_ocr_decompression_bomb_rejected_with_400(self):
        """
        Verifies that a decompression bomb (image exceeding 16,000,000 pixels)
        is intercepted by Pillow safeguards and rejected with HTTP 400 Bad Request.
        """
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        # 4000 x 4001 = 16,004,000 pixels (> MAX_PIXELS 16,000,000)
        # Note: compressed PNG size is under 60 KB, making this a true decompression attack vector
        bomb_png = make_test_image_bytes("PNG", size=(4000, 4001))
        files = {"file": ("bomb.png", bomb_png, "image/png")}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                resp = await client.post("/ocr/extract", files=files, headers=headers)
                assert resp.status_code == 400
                assert "decompression limit" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ocr_oversized_dimensions_rejected_with_400(self):
        """
        Verifies that an image exceeding the 4096 px dimension boundary
        (e.g., 4097 x 100 px) is rejected with HTTP 400 Bad Request.
        """
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        oversized_dim_png = make_test_image_bytes("PNG", size=(4097, 100))
        files = {"file": ("wide.png", oversized_dim_png, "image/png")}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                resp = await client.post("/ocr/extract", files=files, headers=headers)
                assert resp.status_code == 400
                assert "exceed maximum allowed 4096x4096 px" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()


class TestOcrTimeoutAndConcurrency:
    @pytest.mark.asyncio
    async def test_ocr_tesseract_timeout_returns_504(self):
        """
        Verifies that when PyTesseract exceeds its execution timeout (10 seconds),
        the server catches the timeout exception and returns HTTP 504 Gateway Timeout.
        """
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        png_data = make_test_image_bytes("PNG")
        files = {"file": ("document.png", png_data, "image/png")}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                with patch("pytesseract.image_to_string", side_effect=RuntimeError("Tesseract process timeout")):
                    resp = await client.post("/ocr/extract", files=files, headers=headers)
                    assert resp.status_code == 504
                    assert "OCR processing timed out" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ocr_engine_failure_returns_502(self):
        """
        Verifies that an internal Tesseract engine crash returns HTTP 502 Bad Gateway
        with a sanitized client message that does not expose internal stack or execution details.
        """
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        png_data = make_test_image_bytes("PNG")
        files = {"file": ("document.png", png_data, "image/png")}

        internal_error_msg = "INTERNAL_CRASH: segfault at 0x7fff at /var/run/tesseract/libnative.so"

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                with patch("pytesseract.image_to_string", side_effect=RuntimeError(internal_error_msg)):
                    resp = await client.post("/ocr/extract", files=files, headers=headers)
                    assert resp.status_code == 502
                    # Sanitized message returned to client
                    assert "OCR engine runtime failure" in resp.json()["detail"]
                    # Internal binary crash details must never leak to client!
                    assert "INTERNAL_CRASH" not in resp.text
                    assert "segfault" not in resp.text
                    assert "/var/run/tesseract" not in resp.text
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ocr_concurrency_bounded_by_semaphore(self):
        """
        Verifies that simultaneous calls to POST /ocr/extract are bounded
        by the process-local asyncio.Semaphore (MAX_CONCURRENT_OCR_WORKERS = 2).
        """
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        active_workers = 0
        peak_workers = 0
        worker_lock = threading.Lock()

        def mock_extract_worker(file_bytes):
            nonlocal active_workers, peak_workers
            # Synchronous threadpool worker simulating slow Tesseract OCR
            import time

            # Thread-safe counter update
            with worker_lock:
                active_workers += 1
                if active_workers > peak_workers:
                    peak_workers = active_workers
            time.sleep(0.08)
            with worker_lock:
                active_workers -= 1
            return {"extracted_text": "Concurrent OCR Output", "confidence": 0.9}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)

                async def send_ocr_req():
                    png_data = make_test_image_bytes("PNG")
                    files = {"file": ("concurrent.png", png_data, "image/png")}
                    return await client.post("/ocr/extract", files=files, headers=headers)

                with patch("app.ocr.service.extract_text", side_effect=mock_extract_worker):
                    # Launch 4 requests simultaneously
                    results = await asyncio.gather(
                        send_ocr_req(),
                        send_ocr_req(),
                        send_ocr_req(),
                        send_ocr_req(),
                    )

                    assert all(r.status_code == 200 for r in results)
                    # Peak active workers must never exceed configured MAX_CONCURRENT_OCR_WORKERS (2)
                    assert peak_workers <= settings.MAX_CONCURRENT_OCR_WORKERS
                    assert peak_workers == 2
        finally:
            app.dependency_overrides.clear()


class TestOcrResourceAndFileCleanup:
    @pytest.mark.asyncio
    async def test_ocr_temporary_file_closed_and_cleaned_up_on_success(self):
        """
        Verifies that file.close() is called to ensure any temporary/spooled
        files on disk are deleted after successful extraction.
        """
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        png_data = make_test_image_bytes("PNG")
        files = {"file": ("clean.png", png_data, "image/png")}
        mock_result = {"extracted_text": "Clean extraction", "confidence": 0.95}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                with patch("app.ocr.service.extract_text", return_value=mock_result):
                    with patch.object(UploadFile, "close", new_callable=AsyncMock) as mock_close:
                        resp = await client.post("/ocr/extract", files=files, headers=headers)
                        assert resp.status_code == 200
                        assert mock_close.called
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ocr_temporary_file_closed_and_cleaned_up_on_oversized_failure(self):
        """
        Verifies that file.close() is called even when an oversized file is aborted
        with HTTP 413, guaranteeing immediate disk cleanup of spooled temp files.
        """
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        oversized_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024 + 1024)
        files = {"file": ("massive_clean.png", oversized_data, "image/png")}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                with patch.object(UploadFile, "close", new_callable=AsyncMock) as mock_close:
                    resp = await client.post("/ocr/extract", files=files, headers=headers)
                    assert resp.status_code == 413
                    assert mock_close.called
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ocr_temporary_file_closed_on_invalid_mime_type(self):
        """
        Verifies that file.close() is called when an upload has an unsupported
        MIME type and is rejected with HTTP 400 Bad Request.
        """
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        files = {"file": ("doc.txt", b"plain text", "text/plain")}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                with patch.object(UploadFile, "close", new_callable=AsyncMock) as mock_close:
                    resp = await client.post("/ocr/extract", files=files, headers=headers)
                    assert resp.status_code == 400
                    assert mock_close.called
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ocr_temporary_file_closed_on_magic_bytes_mismatch(self):
        """
        Verifies that file.close() is called when an upload fails magic byte
        verification and is rejected with HTTP 400 Bad Request.
        """
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        files = {"file": ("fake.png", b"not-a-png-file", "image/png")}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                with patch.object(UploadFile, "close", new_callable=AsyncMock) as mock_close:
                    resp = await client.post("/ocr/extract", files=files, headers=headers)
                    assert resp.status_code == 400
                    assert mock_close.called
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ocr_image_closed_in_finally_on_error(self):
        """
        Verifies that PIL Image instance is closed in finally block if Tesseract fails.
        """
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        png_data = make_test_image_bytes("PNG")
        files = {"file": ("image_close.png", png_data, "image/png")}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                with patch("PIL.Image.Image.close") as mock_img_close:
                    with patch("pytesseract.image_to_string", side_effect=RuntimeError("Simulated failure")):
                        resp = await client.post("/ocr/extract", files=files, headers=headers)
                        assert resp.status_code == 502
                        assert mock_img_close.called
        finally:
            app.dependency_overrides.clear()
