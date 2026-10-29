"""
tests/test_admin_assistant_security.py

Comprehensive security regression tests for the Admin AI Assistant:
1. Verifies that unauthorized users (students, teachers, unauthenticated) are blocked.
2. Verifies that arbitrary SQL tools and unapproved functions are strictly rejected.
3. Verifies that SQL injection payloads and malformed arguments are caught by Pydantic schemas.
4. Verifies that internal UUIDs (pending_teacher_ids) and database errors are scrubbed safely.
5. Verifies that approved reporting queries execute correctly with bounded parameters.
"""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.agents.admin_assistant import (
    APPROVED_TOOL_SCHEMAS,
    AttendanceStatsArgs,
    SalarySummaryArgs,
    StudentTeacherCountsArgs,
    TeacherGradingPerformanceArgs,
    execute_tools_node,
)
from app.users.dependencies import require_role
from app.users.models import User

# =====================================================================
# 1. Route Authorization Unit Tests (FastAPI Dependency Guards)
# =====================================================================

class TestAdminAssistantAuthorization:
    """Verifies that non-admin roles and unauthenticated callers are rejected at the dependency layer."""

    @pytest.mark.asyncio
    async def test_require_role_admin_accepts_admin(self):
        admin_user = User(email="admin@eduintel.com", role="admin")
        checker = require_role("admin")
        result = await checker(current_user=admin_user)
        assert result.role == "admin"

    @pytest.mark.asyncio
    async def test_require_role_admin_rejects_student(self):
        student_user = User(email="student@eduintel.com", role="student")
        checker = require_role("admin")
        with pytest.raises(HTTPException) as exc_info:
            await checker(current_user=student_user)
        assert exc_info.value.status_code == 403
        assert "requires one of these roles: admin" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_require_role_admin_rejects_teacher(self):
        teacher_user = User(email="teacher@eduintel.com", role="teacher")
        checker = require_role("admin")
        with pytest.raises(HTTPException) as exc_info:
            await checker(current_user=teacher_user)
        assert exc_info.value.status_code == 403
        assert "requires one of these roles: admin" in exc_info.value.detail.lower()


# =====================================================================
# 2. Strict Tool Whitelist & Arbitrary SQL Tool Rejection Tests
# =====================================================================

class TestToolWhitelistAndArbitrarySQLRejection:
    """Verifies that the assistant explicitly rejects unapproved or arbitrary SQL tools."""

    @pytest.mark.asyncio
    async def test_arbitrary_sql_tool_is_blocked(self):
        state = {
            "query": "drop all tables",
            "history": [],
            "tool_calls": [
                {"name": "query_database", "args": {"sql": "DROP TABLE users CASCADE;"}},
                {"name": "execute_sql", "args": {"query": "SELECT * FROM users"}},
                {"name": "raw_query", "args": {"statement": "DELETE FROM fee_records"}},
            ],
            "tool_results": [],
            "answer": "",
            "decide_tools_usage": None,
            "generate_usage": None,
            "trace_steps": [],
        }

        new_state = await execute_tools_node(state)
        results = new_state["tool_results"]

        assert len(results) == 3
        for res in results:
            assert "error" in res["result"]
            assert "not authorized" in res["result"]["error"]
            assert "Arbitrary queries and unapproved tools are prohibited" in res["result"]["error"]

    @pytest.mark.asyncio
    async def test_only_approved_six_tools_in_registry(self):
        expected_tools = {
            "get_student_teacher_counts",
            "get_salary_summary",
            "get_timetable_coverage",
            "get_teacher_grading_performance",
            "get_revenue_summary",
            "get_attendance_stats",
        }
        assert set(APPROVED_TOOL_SCHEMAS.keys()) == expected_tools


# =====================================================================
# 3. Pydantic Parameter Validation & SQL Injection Containment Tests
# =====================================================================

class TestToolArgumentValidation:
    """Verifies that input arguments are strictly typed, bounded, and immune to injection."""

    def test_salary_summary_valid_month(self):
        args = SalarySummaryArgs(month="2026-08")
        assert args.month == date(2026, 8, 1)

    def test_salary_summary_none_month(self):
        args = SalarySummaryArgs()
        assert args.month is None

    def test_salary_summary_rejects_sql_injection_in_month(self):
        malicious_inputs = [
            "2026-08; DROP TABLE users;",
            "2026-08' OR '1'='1",
            "2026-08 UNION SELECT password FROM users",
            "2026-08--",
        ]
        for bad_input in malicious_inputs:
            with pytest.raises((ValueError, ValidationError)):
                SalarySummaryArgs(month=bad_input)

    def test_salary_summary_rejects_malformed_month_formats(self):
        invalid_months = ["invalid", "2026/08", "2026-13", "08-2026", "2026-8", "2026-00"]
        for bad_month in invalid_months:
            with pytest.raises((ValueError, ValidationError)):
                SalarySummaryArgs(month=bad_month)

    def test_salary_summary_forbids_unexpected_arguments(self):
        with pytest.raises(ValidationError):
            SalarySummaryArgs(month="2026-08", extra_injected_param="malicious_payload")

    def test_attendance_stats_valid_class_section(self):
        args = AttendanceStatsArgs(class_section="10-A")
        assert args.class_section == "10-A"

    def test_attendance_stats_rejects_sql_injection_in_section(self):
        malicious_sections = [
            "10-A' OR 1=1 --",
            "10-A; DROP TABLE attendance;",
            "10-A UNION SELECT *",
        ]
        for bad_sec in malicious_sections:
            with pytest.raises((ValueError, ValidationError)):
                AttendanceStatsArgs(class_section=bad_sec)

    def test_attendance_stats_rejects_excessive_length(self):
        excessive_section = "A" * 50
        with pytest.raises((ValueError, ValidationError)):
            AttendanceStatsArgs(class_section=excessive_section)

    def test_no_args_tools_forbid_extra_parameters(self):
        with pytest.raises(ValidationError):
            StudentTeacherCountsArgs(injected_arg="hacked")

        with pytest.raises(ValidationError):
            TeacherGradingPerformanceArgs(extra_sql="SELECT 1")


# =====================================================================
# 4. Output Sanitization & Error Masking Tests
# =====================================================================

class TestToolOutputSanitization:
    """Verifies that sensitive database identifiers and raw error traces are never leaked."""

    @pytest.mark.asyncio
    async def test_pending_teacher_uuids_are_scrubbed_from_salary_summary(self):
        mock_salary_result = {
            "record_count": 5,
            "total_payout": 250000.0,
            "total_base_salary": 240000.0,
            "total_bonus": 10000.0,
            "total_deduction": 0.0,
            "pending_count": 2,
            "pending_teacher_ids": ["c3f8e02d-0b1a-4d2b-9876-543210abcdef", "a1b2c3d4-e5f6-7890-1234-567890abcdef"],
            "paid_count": 3,
        }

        with patch("app.agents.admin_assistant.TOOL_FUNCTIONS", {
            "get_salary_summary": AsyncMock(return_value=mock_salary_result)
        }):
            state = {
                "query": "salary status",
                "history": [],
                "tool_calls": [{"name": "get_salary_summary", "args": {"month": "2026-08"}}],
                "tool_results": [],
                "answer": "",
                "decide_tools_usage": None,
                "generate_usage": None,
                "trace_steps": [],
            }

            new_state = await execute_tools_node(state)
            result = new_state["tool_results"][0]["result"]

            # Asserts sensitive teacher UUIDs are completely scrubbed
            assert "pending_teacher_ids" not in result
            assert result["pending_count"] == 2
            assert result["total_payout"] == 250000.0

    @pytest.mark.asyncio
    async def test_database_exceptions_are_masked_safely(self):
        db_err = RuntimeError("psql: FATAL: password authentication failed for user 'postgres'")
        mock_tool_fn = AsyncMock(side_effect=db_err)
        with patch("app.agents.admin_assistant.TOOL_FUNCTIONS", {"get_attendance_stats": mock_tool_fn}):
            state = {
                "query": "attendance",
                "history": [],
                "tool_calls": [{"name": "get_attendance_stats", "args": {"class_section": "10-A"}}],
                "tool_results": [],
                "answer": "",
                "decide_tools_usage": None,
                "generate_usage": None,
                "trace_steps": [],
            }

            new_state = await execute_tools_node(state)
            result = new_state["tool_results"][0]["result"]

            # Asserts raw exception details, credentials, and hostnames are not leaked
            assert result == {"error": "Reporting query execution failed safely."}
            assert "postgres" not in str(result)
            assert "password" not in str(result)


# =====================================================================
# 5. Approved Reporting Queries Execution Tests
# =====================================================================

class TestApprovedReportingExecution:
    """Verifies that valid, approved reporting queries execute and return proper data."""

    @pytest.mark.asyncio
    async def test_approved_counts_query_executes_cleanly(self):
        mock_counts = {"total_students": 150, "total_teachers": 18}

        with patch("app.agents.admin_assistant.TOOL_FUNCTIONS", {
            "get_student_teacher_counts": AsyncMock(return_value=mock_counts)
        }):
            state = {
                "query": "how many students and teachers",
                "history": [],
                "tool_calls": [{"name": "get_student_teacher_counts", "args": {}}],
                "tool_results": [],
                "answer": "",
                "decide_tools_usage": None,
                "generate_usage": None,
                "trace_steps": [],
            }

            new_state = await execute_tools_node(state)
            result = new_state["tool_results"][0]["result"]

            assert result == {"total_students": 150, "total_teachers": 18}
