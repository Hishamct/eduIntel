from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.core.llm_client import generate_text_with_usage
from app.guardrails.pii_redaction import redact_pii, summarize_findings

SERVER_PARAMS = StdioServerParameters(
    command="python",
    args=["-m", "app.mcp.server"],
)

REPORT_PROMPT = """Write a warm, concise progress report email (3-4 short paragraphs) for a parent,
based on this student's data. Mention recent exam performance by subject and overall attendance.
Keep the tone encouraging even if there are concerns — frame concerns constructively, not alarmingly.
Do not include a greeting like "Dear Parent" or a sign-off — those are added separately.

Student name: {student_name}
Data: {data}

Write only the email body paragraphs."""


async def generate_and_send_report(
    student_id: str,
    student_name: str,
    parent_email: str,
    db=None,
    generated_by_user_id=None,
) -> dict:
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            data_result = await session.call_tool(
                "get_student_data", {"student_id": student_id}
            )
            student_data = data_result.content[0].text

            prompt = REPORT_PROMPT.format(student_name=student_name, data=student_data)
            report_body, llm_usage = generate_text_with_usage(prompt)

            # Guardrail: redact PII from the LLM-generated body BEFORE it's
            # wrapped into the full email and sent. student_data comes
            # straight from get_student_data (which may include teacher
            # free-text notes), and that text is inside the prompt above —
            # so the model has had the opportunity to echo back a phone
            # number or email address that belongs to someone else entirely
            # (another parent, a colleague) rather than to this report's
            # recipient. parent_email is allow-listed since it's fine (and
            # sometimes expected) for a report to reference how to reach
            # the school/parent by their own address.
            redacted_body, findings = redact_pii(
                report_body, allow_values={parent_email}
            )
            redacted_types = summarize_findings(findings)

            if findings:
                print(
                    f"[guardrail] Redacted {len(findings)} PII match(es) from parent report "
                    f"(student_id={student_id}, types={redacted_types})"
                )

            if db is not None and generated_by_user_id is not None:
                from app.observability.service import log_llm_usage, log_pii_redaction

                await log_pii_redaction(
                    db=db,
                    user_id=generated_by_user_id,
                    endpoint="reports/parent-report",
                    query_text=f"parent report for student_id={student_id}",
                    redaction_count=len(findings),
                    redacted_types=redacted_types,
                )
                await log_llm_usage(
                    db=db, endpoint="reports/parent-report", usage=llm_usage
                )

            full_email = f"Dear Parent,\n\n{redacted_body}\n\nRegards,\nEduIntel AI"

            send_result = await session.call_tool(
                "send_email",
                {
                    "to_email": parent_email,
                    "subject": f"Progress Report — {student_name}",
                    "body": full_email,
                },
            )

    return {
        "report_body": full_email,
        "email_result": send_result.content[0].text,
        "redaction_count": len(findings),
        "redacted_types": redacted_types,
    }
