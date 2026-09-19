"""
MCP server exposing EduIntel AI's student data and email-sending
as standardized tools. Run standalone via stdio; the reports module
connects to this as an MCP client.
"""
from mcp.server.fastmcp import FastMCP
import smtplib
from email.mime.text import MIMEText
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.teacher.models import ExamResult
from app.admin.models import Attendance

mcp = FastMCP("eduintel-mcp")


@mcp.tool()
async def get_student_data(student_id: str) -> dict:
    """Get a student's recent exam results and attendance percentage for a parent progress report."""
    async with AsyncSessionLocal() as db:
        exam_results = (await db.execute(
            select(ExamResult)
            .where(ExamResult.student_id == student_id)
            .order_by(ExamResult.exam_date.desc())
            .limit(5)
        )).scalars().all()

        attendance = (await db.execute(
            select(Attendance).where(Attendance.student_id == student_id)
        )).scalars().all()

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