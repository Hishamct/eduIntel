from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from app.core.llm_client import generate_text

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


async def generate_and_send_report(student_id: str, student_name: str, parent_email: str) -> dict:
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            data_result = await session.call_tool(
                "get_student_data", {"student_id": student_id}
            )
            student_data = data_result.content[0].text

            prompt = REPORT_PROMPT.format(student_name=student_name, data=student_data)
            report_body = generate_text(prompt)

            full_email = f"Dear Parent,\n\n{report_body}\n\nRegards,\nEduIntel AI"

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
    }