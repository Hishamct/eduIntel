"""
MCP server exposing EduIntel AI's student data and email-sending
as standardized tools. Run standalone via stdio; the reports module
connects to this as an MCP client.
"""

import smtplib
import uuid
from email.mime.text import MIMEText

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from app.admin.models import Attendance
from app.core.config import settings
from app.core.tenant import (
    PILOT_INSTITUTION_UUID,
    normalize_institution_id,
    tenant_session_scope,
)
from app.teacher.models import ExamResult

mcp = FastMCP("eduintel-mcp")


@mcp.tool()
async def get_student_data(student_id: str, institution_id: str | None = None) -> dict:
    """Get a student's recent exam results and attendance percentage for a parent progress report."""
    try:
        student_uuid = uuid.UUID(str(student_id))
    except (ValueError, TypeError, AttributeError) as err:
        raise ValueError(f"Invalid student UUID format '{student_id}': {err}") from err

    inst_uuid: uuid.UUID | None = None

    if institution_id:
        try:
            inst_uuid = normalize_institution_id(institution_id)
        except Exception as err:
            raise ValueError(f"Invalid institution_id '{institution_id}': {err}") from err
        if inst_uuid is None:
            raise ValueError(f"Invalid institution_id '{institution_id}'")
    else:
        # Non-tenant callers: allowed only if legacy single-tenant namespace is explicitly enabled
        if getattr(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", False):
            inst_uuid = PILOT_INSTITUTION_UUID
        else:
            raise ValueError("institution_id is required for tenant-scoped student data retrieval.")

    async with tenant_session_scope(inst_uuid) as db:
        exam_results = (
            (
                await db.execute(
                    select(ExamResult)
                    .where(
                        ExamResult.student_id == student_uuid,
                        ExamResult.institution_id == inst_uuid,
                    )
                    .order_by(ExamResult.exam_date.desc())
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )

        attendance = (
            (
                await db.execute(
                    select(Attendance).where(
                        Attendance.student_id == student_uuid,
                        Attendance.institution_id == inst_uuid,
                    )
                )
            )
            .scalars()
            .all()
        )

        total = len(attendance)
        present_or_late = sum(1 for a in attendance if a.status in ("present", "late"))
        attendance_pct = round((present_or_late / total) * 100, 1) if total else None

        return {
            "recent_exams": [
                {
                    "subject": e.subject,
                    "topic": e.topic,
                    "score": float(e.score),
                    "max_score": float(e.max_score),
                    "exam_date": e.exam_date.isoformat(),
                }
                for e in exam_results
            ],
            "attendance_percentage": attendance_pct,
        }


@mcp.tool()
def send_email(to_email: str, subject: str, body: str) -> dict:
    """Send an email via SMTP. Returns {'status': 'sent'} or {'status': 'error', 'detail': ...}."""
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = settings.EMAIL_FROM
        msg["To"] = to_email

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.EMAIL_FROM, [to_email], msg.as_string())
        return {"status": "sent"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
