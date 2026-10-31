"""
backend/tests/test_rag_tenant_isolation.py

Comprehensive test suite verifying SEC-08 remediation:
- RAG Cross-Tenant Vector Leakage protections in ChromaDB vector store:
    1. POST /rag/query
    2. GET /rag/debug-query
    3. retrieve_and_generate()
    4. ingest_study_material()
    5. debug_query_study_materials()
    6. get_recommendations_for_weak_topics()
- Trusted tenant resolution from server context only (client-supplied tenant injection rejected).
- Fail-closed enforcement on study_materials when trusted tenant context is unavailable.
- Isolation of study_materials vector similarity queries with mandatory where={"institution_id": ...}.
- Global collection status for portal_help_docs (no tenant constraint required).
- Debug query endpoint restricted strictly to administrators.
- Ingestion enforces trusted tenant metadata; untagged chunks remain inaccessible.

TEST EXECUTION ENVIRONMENT NOTE:
These automated unit and route-contract tests utilize FastAPI ASGITransport with
dependency injection overrides and MagicMock/AsyncMock fixtures. Live PostgreSQL
integration testing with disposable test databases is scheduled for Phase 4.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.security import create_access_token, hash_password
from app.core.config import settings
from app.core.database import get_db
from app.core.tenant import get_trusted_tenant_id
from app.main import app
from app.ml.recommendations import get_recommendations_for_weak_topics
from app.rag.service import (
    debug_query_study_materials,
    ingest_study_material,
    retrieve_and_generate,
)
from app.users.dependencies import get_current_user
from app.users.models import AdminProfile, StudentProfile, TeacherProfile, User


def create_mock_user(
    role: str,
    user_id: uuid.UUID | None = None,
    institution_id: str | None = None,
) -> User:
    uid = user_id or uuid.uuid4()
    user = User(
        id=uid,
        email=f"user_{role}_{uid.hex[:6]}@example.com",
        name=f"Mock {role.capitalize()}",
        hashed_password=hash_password("MockPass123!"),
        role=role,
        is_active=True,
    )
    if institution_id:
        # Dynamically attach trusted server-side institution_id for multi-tenant simulation
        user.institution_id = institution_id

    if role == "student":
        user.student_profile = StudentProfile(
            id=uuid.uuid4(),
            user_id=uid,
            grade="10",
            section="A",
            parent_email="parent@example.com",
        )
    elif role == "teacher":
        user.teacher_profile = TeacherProfile(
            id=uuid.uuid4(),
            user_id=uid,
            department="Science",
            subjects="Physics",
        )
    elif role == "admin":
        user.admin_profile = AdminProfile(
            id=uuid.uuid4(),
            user_id=uid,
            designation="Administrator",
        )
    return user


def make_auth_header(user: User) -> dict:
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": f"Bearer {token}"}


class TestRagAuthenticationAndRoleGuards:
    """Verifies authentication guards and administrative restriction on debug endpoints."""

    @pytest.mark.asyncio
    async def test_rag_query_anonymous_rejected_401(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/rag/query", json={"query": "test query", "collection": "portal_help_docs"}
            )
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_debug_query_anonymous_rejected_401(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/rag/debug-query?q=test")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_debug_query_student_role_rejected_403(self):
        student = create_mock_user("student", institution_id="inst-pilot")
        app.dependency_overrides[get_current_user] = lambda: student
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/rag/debug-query?q=mechanics", headers=make_auth_header(student)
                )
                assert resp.status_code == 403
                assert "requires one of these roles: admin" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @pytest.mark.asyncio
    async def test_debug_query_teacher_role_rejected_403(self):
        teacher = create_mock_user("teacher", institution_id="inst-pilot")
        app.dependency_overrides[get_current_user] = lambda: teacher
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/rag/debug-query?q=mechanics", headers=make_auth_header(teacher)
                )
                assert resp.status_code == 403
                assert "requires one of these roles: admin" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @pytest.mark.asyncio
    async def test_debug_query_admin_role_accepted_200(self):
        admin = create_mock_user("admin", institution_id="inst-pilot")
        app.dependency_overrides[get_current_user] = lambda: admin
        with patch("app.rag.router.debug_query_study_materials") as mock_debug:
            mock_debug.return_value = [
                {
                    "chunk_text": "Physics principles",
                    "distance": 0.12,
                    "metadata": {"subject": "Physics", "title": "Intro"},
                }
            ]
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(
                        "/rag/debug-query?q=physics", headers=make_auth_header(admin)
                    )
                    assert resp.status_code == 200
                    data = resp.json()
                    assert len(data) == 1
                    assert data[0]["chunk_text"] == "Physics principles"
            finally:
                app.dependency_overrides.pop(get_current_user, None)


class TestClientTenantInjectionRejection:
    """Verifies that client payload attempts to specify institution_id are forbidden."""

    @pytest.mark.asyncio
    async def test_rag_query_rejects_client_supplied_institution_id(self):
        student = create_mock_user("student", institution_id="inst-pilot")
        app.dependency_overrides[get_current_user] = lambda: student
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Client attempts to pass institution_id to bypass tenant boundary
                resp = await client.post(
                    "/rag/query",
                    json={
                        "query": "What are newton laws?",
                        "collection": "study_materials",
                        "institution_id": "malicious-competing-institute",
                    },
                    headers=make_auth_header(student),
                )
                assert resp.status_code == 422
                assert "extra" in resp.text.lower() or "forbidden" in resp.text.lower()
        finally:
            app.dependency_overrides.pop(get_current_user, None)


class TestFailClosedTenantEnforcement:
    """Verifies fail-closed behavior for study_materials when trusted tenant context is absent."""

    @pytest.mark.asyncio
    async def test_rag_query_study_materials_fails_closed_without_tenant(self):
        # User has no institution_id and legacy pilot namespace is disabled
        user_no_tenant = create_mock_user("student", institution_id=None)
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: user_no_tenant
        app.dependency_overrides[get_db] = lambda: mock_db
        with patch.object(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", False):
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/rag/query",
                        json={"query": "test query", "collection": "study_materials"},
                        headers=make_auth_header(user_no_tenant),
                    )
                    assert resp.status_code == 403
                    assert "Tenant context required for study materials access" in resp.json()["detail"]
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_debug_query_study_materials_fails_closed_without_tenant(self):
        admin_no_tenant = create_mock_user("admin", institution_id=None)
        app.dependency_overrides[get_current_user] = lambda: admin_no_tenant
        with patch.object(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", False):
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(
                        "/rag/debug-query?q=optics&collection=study_materials",
                        headers=make_auth_header(admin_no_tenant),
                    )
                    assert resp.status_code == 403
                    assert "Tenant context required for study materials access" in resp.json()["detail"]
            finally:
                app.dependency_overrides.pop(get_current_user, None)

    def test_retrieve_and_generate_raises_value_error_without_tenant_on_study_materials(self):
        with pytest.raises(ValueError, match="Trusted institution_id is required"):
            retrieve_and_generate(
                query="physics notes",
                collection_name="study_materials",
                institution_id=None,
            )

    def test_debug_query_study_materials_raises_value_error_without_tenant(self):
        with pytest.raises(ValueError, match="Trusted institution_id is required"):
            debug_query_study_materials(
                query="physics notes",
                collection_name="study_materials",
                institution_id=None,
            )


class TestGlobalPortalHelpDocsExemption:
    """Verifies that portal_help_docs queries succeed globally without tenant filtering."""

    @pytest.mark.asyncio
    async def test_portal_help_docs_accessible_without_tenant_context(self):
        user_no_tenant = create_mock_user("student", institution_id=None)
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: user_no_tenant
        app.dependency_overrides[get_db] = lambda: mock_db
        with patch("app.rag.router.retrieve_and_generate") as mock_rag:
            mock_rag.return_value = {
                "answer": "To submit homework, visit the Homework tab.",
                "sources": [{"chunk_text": "Help chunk", "title": "Help", "subject": "General"}],
                "llm_usage": None,
            }
            with patch.object(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", False):
                try:
                    async with AsyncClient(
                        transport=ASGITransport(app=app), base_url="http://test"
                    ) as client:
                        resp = await client.post(
                            "/rag/query",
                            json={"query": "how to submit homework?", "collection": "portal_help_docs"},
                            headers=make_auth_header(user_no_tenant),
                        )
                        assert resp.status_code == 200
                        data = resp.json()
                        assert "Homework tab" in data["answer"]
                finally:
                    app.dependency_overrides.pop(get_current_user, None)
                    app.dependency_overrides.pop(get_db, None)

    def test_retrieve_and_generate_portal_help_does_not_filter_tenant(self):
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [["Portal help content"]],
            "metadatas": [[{"title": "FAQ", "subject": "General"}]],
        }

        with patch("app.rag.client.get_collection_by_name", return_value=mock_collection), \
             patch("app.rag.service.generate_text_with_usage", return_value=("Help answer", None)):
            result = retrieve_and_generate(
                query="How do I upload?",
                collection_name="portal_help_docs",
                institution_id=None,
            )
            # Verify collection.query was called WITHOUT a where={"institution_id": ...} argument
            mock_collection.query.assert_called_once_with(
                query_texts=["How do I upload?"],
                n_results=3,
            )
            assert result["answer"] == "Help answer"


class TestCrossTenantVectorIsolation:
    """Verifies that ChromaDB queries strictly enforce where={'institution_id': ...}."""

    def test_study_materials_retrieval_applies_mandatory_tenant_filter(self):
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [["Tenant Alpha Private Chemistry Notes"]],
            "metadatas": [[{"title": "Chem Notes", "subject": "Chemistry", "institution_id": "inst-alpha"}]],
        }

        with patch("app.rag.client.get_collection_by_name", return_value=mock_collection), \
             patch("app.rag.service.generate_text_with_usage", return_value=("Synthesized answer", None)):
            result = retrieve_and_generate(
                query="Explain covalent bonds",
                collection_name="study_materials",
                institution_id="inst-alpha",
            )
            # Mandatory security verification: where clause with tenant ID was applied
            mock_collection.query.assert_called_once_with(
                query_texts=["Explain covalent bonds"],
                n_results=3,
                where={"institution_id": "inst-alpha"},
            )
            assert result["answer"] == "Synthesized answer"

    def test_cross_tenant_isolation_boundary(self):
        """Simulates two distinct institutions querying the same vector index."""
        collection_queries = []

        def fake_query(query_texts, n_results, where=None):
            collection_queries.append({"query_texts": query_texts, "where": where})
            tenant = where.get("institution_id") if where else None
            if tenant == "inst-alpha":
                return {
                    "documents": [["Alpha Proprietary Notes"]],
                    "metadatas": [[{"title": "Alpha Document", "subject": "Physics", "institution_id": "inst-alpha"}]],
                }
            elif tenant == "inst-beta":
                return {
                    "documents": [["Beta Proprietary Notes"]],
                    "metadatas": [[{"title": "Beta Document", "subject": "Physics", "institution_id": "inst-beta"}]],
                }
            return {"documents": [[]], "metadatas": [[]]}

        mock_collection = MagicMock()
        mock_collection.query.side_effect = fake_query

        with patch("app.rag.client.get_collection_by_name", return_value=mock_collection), \
             patch("app.rag.service.generate_text_with_usage", return_value=("Answer", None)):
            # User from Tenant Alpha queries
            res_alpha = retrieve_and_generate(
                query="physics curriculum",
                collection_name="study_materials",
                institution_id="inst-alpha",
            )
            assert res_alpha["sources"][0]["title"] == "Alpha Document"

            # User from Tenant Beta queries identical search term
            res_beta = retrieve_and_generate(
                query="physics curriculum",
                collection_name="study_materials",
                institution_id="inst-beta",
            )
            assert res_beta["sources"][0]["title"] == "Beta Document"

            # Assert each query strictly filtered by its own tenant
            assert collection_queries[0]["where"] == {"institution_id": "inst-alpha"}
            assert collection_queries[1]["where"] == {"institution_id": "inst-beta"}


class TestIngestionTenantMetadataAssignment:
    """Verifies that vector ingestion enforces tenant tagging and rejects un-namespaced chunks."""

    def test_ingestion_refuses_chunks_without_tenant_id(self):
        res = ingest_study_material(
            material_id=str(uuid.uuid4()),
            subject="Mathematics",
            title="Calculus Guide",
            extracted_text="Sample calculus equations",
            institution_id=None,
        )
        assert res["ingested"] is False
        assert "Trusted institution_id required" in res["reason"]

    def test_ingestion_tags_all_chunks_with_tenant_id(self):
        mock_collection = MagicMock()
        with patch("app.rag.service.get_study_materials_collection", return_value=mock_collection):
            mat_id = str(uuid.uuid4())
            res = ingest_study_material(
                material_id=mat_id,
                subject="Biology",
                title="Genetics Notes",
                extracted_text="Long text describing genetic inheritance and DNA sequences.",
                institution_id="inst-school-1",
            )
            assert res["ingested"] is True
            assert res["chunk_count"] > 0

            # Verify collection.upsert received institution_id in metadatas
            assert mock_collection.upsert.called
            call_kwargs = mock_collection.upsert.call_args[1]
            metadatas = call_kwargs["metadatas"]
            assert len(metadatas) == res["chunk_count"]
            for meta in metadatas:
                assert meta["institution_id"] == "inst-school-1"
                assert meta["material_id"] == mat_id
                assert meta["subject"] == "Biology"


class TestDownstreamCallersTenantIsolation:
    """Verifies that recommendation and helper callers properly pass tenant context."""

    def test_get_recommendations_fails_closed_without_tenant_id(self):
        weak_topics = [{"subject": "Mathematics", "topic": "Trigonometry"}]
        # When tenant_id is None, must return fallback guidance with empty sources without querying RAG
        recs = get_recommendations_for_weak_topics(weak_topics, tenant_id=None)
        assert len(recs) == 1
        assert recs[0]["sources"] == []
        assert "Review foundational materials" in recs[0]["recommendation"]

    def test_get_recommendations_passes_tenant_id_to_retrieve_and_generate(self):
        weak_topics = [{"subject": "Physics", "topic": "Kinematics"}]
        with patch("app.ml.recommendations.retrieve_and_generate") as mock_rag:
            mock_rag.return_value = {
                "answer": "Focus on velocity-time graphs.",
                "sources": [{"title": "Kinematics Chapter 1", "subject": "Physics"}],
            }
            recs = get_recommendations_for_weak_topics(weak_topics, tenant_id="inst-gamma")
            assert len(recs) == 1
            assert recs[0]["recommendation"] == "Focus on velocity-time graphs."
            assert recs[0]["sources"][0]["title"] == "Kinematics Chapter 1"

            mock_rag.assert_called_once()
            assert mock_rag.call_args[1]["institution_id"] == "inst-gamma"
            assert mock_rag.call_args[1]["collection_name"] == "study_materials"


class TestTrustedTenantResolver:
    """Verifies get_trusted_tenant_id behavior with and without legacy pilot setting."""

    def test_user_with_explicit_institution_id_takes_precedence(self):
        user = create_mock_user("teacher", institution_id="inst-custom")
        with patch.object(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", True), \
             patch.object(settings, "DEFAULT_INSTITUTION_ID", "eduintel-pilot"):
            assert get_trusted_tenant_id(user) == "inst-custom"

    def test_legacy_mode_enabled_falls_back_to_pilot_setting(self):
        user = create_mock_user("teacher", institution_id=None)
        with patch.object(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", True), \
             patch.object(settings, "DEFAULT_INSTITUTION_ID", "eduintel-pilot"):
            assert get_trusted_tenant_id(user) == "eduintel-pilot"

    def test_legacy_mode_disabled_fails_closed_when_user_lacks_institution_id(self):
        user = create_mock_user("teacher", institution_id=None)
        with patch.object(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", False):
            assert get_trusted_tenant_id(user) is None
            assert get_trusted_tenant_id(None) is None
