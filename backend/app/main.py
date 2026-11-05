import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.admin.router import router as admin_router
from app.agents.router import router as agents_router
from app.announcements.router import router as announcements_router
from app.auth.router import router as auth_router
from app.core.config import settings
from app.core.database import engine
from app.institutions.router import router as institutions_router
from app.ml.router import router as ml_router
from app.observability.router import router as observability_router
from app.ocr.router import router as ocr_router
from app.rag.router import router as rag_router
from app.reports.router import router as reports_router
from app.student.router import router as student_router
from app.teacher.router import router as teacher_router
from app.users.router import router as users_router


async def verify_unprivileged_db_user(db_engine=None):
    """
    Startup assertion: verifies that runtime database role does NOT have
    SUPERUSER, BYPASSRLS, CREATEROLE, or CREATEDB directly, via inheritance, or via SET ROLE.
    In PostgreSQL 16, traverses pg_auth_members considering inherit_option and set_option.
    """
    if db_engine is None:
        db_engine = engine

    check_query = text(
        """
        WITH RECURSIVE role_tree AS (
            SELECT r.oid, r.rolname, r.rolsuper, r.rolbypassrls, r.rolcreaterole, r.rolcreatedb,
                   true AS can_inherit, true AS can_set
            FROM pg_roles r
            WHERE r.rolname = current_user
            UNION
            SELECT parent.oid, parent.rolname, parent.rolsuper, parent.rolbypassrls,
                   parent.rolcreaterole, parent.rolcreatedb,
                   (rt.can_inherit AND m.inherit_option) AS can_inherit,
                   (rt.can_set AND m.set_option) AS can_set
            FROM pg_auth_members m
            JOIN role_tree rt ON m.member = rt.oid
            JOIN pg_roles parent ON m.roleid = parent.oid
        )
        SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, can_inherit, can_set
        FROM role_tree
        WHERE (can_inherit AND (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb))
           OR (can_set AND (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb));
        """
    )
    async with db_engine.connect() as conn:
        res = await conn.execute(check_query)
        violating_roles = res.fetchall()
        if violating_roles:
            role_details = [
                f"{r.rolname} (rolsuper={r.rolsuper}, rolbypassrls={r.rolbypassrls}, "
                f"rolcreaterole={r.rolcreaterole}, rolcreatedb={r.rolcreatedb})"
                for r in violating_roles
            ]
            raise RuntimeError(
                f"FATAL: Database connection role has unconstrained superuser, bypassrls, "
                f"createrole, or createdb privileges: {role_details}. "
                "Row-Level Security cannot be guaranteed. The application database user must be unprivileged."
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify unprivileged database role on startup
    try:
        await verify_unprivileged_db_user()
    except Exception as exc:
        if settings.ENVIRONMENT == "production":
            raise RuntimeError(
                f"FATAL: Database privilege check failed in production: {exc}"
            ) from exc
        print(f"[startup] WARNING: Database privilege check skipped in {settings.ENVIRONMENT} mode: {exc}")
    yield


app = FastAPI(title="EduIntel AI", lifespan=lifespan)


def is_maintenance_mode() -> bool:
    """Checks whether system-wide quiescence / maintenance mode is active."""
    flag_path = getattr(settings, "MAINTENANCE_FLAG_PATH", "/tmp/eduintel_maintenance.flag")
    return os.path.exists(flag_path)


@app.middleware("http")
async def maintenance_mode_middleware(request: Request, call_next):
    """
    Coordinated Deployment-Wide Quiescence Middleware (ADR-0009):
    When maintenance flag is engaged across container replicas, immediately blocks
    incoming mutating writes (POST, PUT, PATCH, DELETE) with HTTP 503 and Retry-After header.
    Read requests (GET, HEAD, OPTIONS) and health probes are permitted.
    """
    if is_maintenance_mode():
        if request.url.path not in ("/health", "/health/") and request.method in ("POST", "PUT", "PATCH", "DELETE"):
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Service Unavailable: System undergoing consistent backup snapshot. Writes are paused.",
                    "code": "MAINTENANCE_MODE_ACTIVE",
                },
                headers={"Retry-After": "30"},
            )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://13.205.55.115", "https://eduintelai.in", "https://www.eduintelai.in"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(institutions_router)
app.include_router(student_router)
app.include_router(teacher_router)
app.include_router(admin_router)
app.include_router(ocr_router)
app.include_router(rag_router)
app.include_router(announcements_router)
app.include_router(agents_router)
app.include_router(ml_router)
app.include_router(reports_router)
app.include_router(observability_router)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "maintenance": is_maintenance_mode(),
    }

