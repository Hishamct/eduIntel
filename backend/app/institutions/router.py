import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import PasswordResetToken
from app.auth.security import hash_password
from app.auth.service import _hash_token, send_institution_admin_invitation_email
from app.core.database import get_db
from app.core.tenant import TenantContext, get_platform_admin_db, get_tenant_context
from app.institutions.models import Institution, InstitutionMembership
from app.institutions.schemas import (
    InstitutionListItemResponse,
    InstitutionOnboardRequest,
    InstitutionOnboardResponse,
    InstitutionResponse,
    InstitutionStatusUpdate,
)
from app.users.dependencies import get_current_user, require_platform_admin
from app.users.models import AdminProfile, User

router = APIRouter(prefix="/institutions", tags=["institutions"])


class UserInstitutionMembershipResponse(BaseModel):
    membership_id: uuid.UUID
    institution: InstitutionResponse
    role: str
    status: str


@router.get("", response_model=list[InstitutionListItemResponse])
async def list_institutions(
    current_admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_platform_admin_db),
) -> list[InstitutionListItemResponse]:
    """
    Returns all institutions with aggregated membership counts.
    Strictly restricted to verified Platform Administrators.
    """
    stmt = select(Institution).order_by(Institution.created_at.desc())
    result = await db.execute(stmt)
    institutions = result.scalars().all()

    counts_stmt = (
        select(
            InstitutionMembership.institution_id,
            InstitutionMembership.role,
            func.count(InstitutionMembership.id).label("count"),
        )
        .where(InstitutionMembership.status == "active")
        .group_by(InstitutionMembership.institution_id, InstitutionMembership.role)
    )
    counts_result = await db.execute(counts_stmt)
    counts_rows = counts_result.all()

    counts_map: dict[uuid.UUID, dict[str, int]] = {}
    for inst_id, role, cnt in counts_rows:
        if inst_id not in counts_map:
            counts_map[inst_id] = {"student": 0, "teacher": 0, "admin": 0}
        if role in counts_map[inst_id]:
            counts_map[inst_id][role] = int(cnt)

    output: list[InstitutionListItemResponse] = []
    for inst in institutions:
        c = counts_map.get(inst.id, {"student": 0, "teacher": 0, "admin": 0})
        output.append(
            InstitutionListItemResponse(
                id=inst.id,
                name=inst.name,
                slug=inst.slug,
                contact_email=inst.contact_email,
                is_active=inst.is_active,
                created_at=inst.created_at,
                updated_at=inst.updated_at,
                student_count=c["student"],
                teacher_count=c["teacher"],
                admin_count=c["admin"],
                total_memberships=c["student"] + c["teacher"] + c["admin"],
            )
        )
    return output


@router.post("", response_model=InstitutionOnboardResponse, status_code=status.HTTP_201_CREATED)
async def onboard_institution(
    data: InstitutionOnboardRequest,
    current_admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_platform_admin_db),
) -> InstitutionOnboardResponse:
    """
    Atomically provisions a new institution, its initial administrator, membership,
    and a 48-hour single-use SHA-256 hashed activation token.

    Production Safeguards:
    1. Initial admin account is created with is_active=False and an unusable 64-char random hash.
    2. Zero possibility of pre-activation login.
    3. Activation token is delivered through the configured invitation channel (SMTP).
    4. The raw token is returned strictly once to the authorized Platform Admin.
    5. Database stores strictly the SHA-256 hash.
    6. Rollback is 100% atomic on duplicate slugs, taken emails, or any DB error.
    """
    clean_slug = data.slug.strip().lower()
    clean_email = data.admin_email.strip().lower()

    # 1. Uniqueness pre-checks
    slug_check = await db.execute(select(Institution).where(Institution.slug == clean_slug))
    if slug_check.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An institution with slug '{clean_slug}' already exists.",
        )

    user_check = await db.execute(select(User).where(User.email == clean_email))
    if user_check.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with email '{clean_email}' already exists.",
        )

    # 2. Create Institution
    new_inst = Institution(
        name=data.name.strip(),
        slug=clean_slug,
        contact_email=data.contact_email.strip() if data.contact_email else None,
        is_active=True,
    )
    db.add(new_inst)
    await db.flush()

    # 3. Create Inactive Administrator (cannot log in until activation flow completes)
    unusable_random_password = secrets.token_urlsafe(64)
    admin_user = User(
        email=clean_email,
        name=data.admin_name.strip(),
        hashed_password=hash_password(unusable_random_password),
        role="admin",
        is_active=False,  # Inactive until activation flow completes!
        is_platform_admin=False,
    )
    db.add(admin_user)
    await db.flush()

    # 4. Set session institution_id so RLS WITH CHECK on admin_profiles is satisfied
    await db.execute(
        text("SELECT set_config('app.current_institution_id', :inst_id, true)"),
        {"inst_id": str(new_inst.id)},
    )

    # 5. Create Admin Profile and Institution Membership
    admin_profile = AdminProfile(
        institution_id=new_inst.id,
        user_id=admin_user.id,
        designation="Institution Administrator",
    )
    membership = InstitutionMembership(
        institution_id=new_inst.id,
        user_id=admin_user.id,
        role="admin",
        status="active",
    )
    db.add_all([admin_profile, membership])

    # 6. Generate 48h activation token (store SHA-256 hash in password_reset_tokens)
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(UTC) + timedelta(hours=48)
    reset_token = PasswordResetToken(
        user_id=admin_user.id,
        token=token_hash,
        expires_at=expires_at,
        used=False,
    )
    db.add(reset_token)
    await db.flush()

    # 7. Deliver token through configured invitation email channel
    delivery_outcome = send_institution_admin_invitation_email(
        raw_token=raw_token,
        recipient_email=admin_user.email,
        recipient_name=admin_user.name or "Administrator",
        institution_name=new_inst.name,
    )
    email_delivered = delivery_outcome.get("status") == "sent"
    invitation_status = delivery_outcome.get("status", "failed")

    return InstitutionOnboardResponse(
        institution_id=new_inst.id,
        name=new_inst.name,
        slug=new_inst.slug,
        contact_email=new_inst.contact_email,
        admin_user_id=admin_user.id,
        admin_email=admin_user.email,
        admin_name=admin_user.name or "",
        activation_token=raw_token,
        expires_at=expires_at,
        invitation_sent=email_delivered,
        invitation_status=invitation_status,
    )


@router.get("/me", response_model=list[UserInstitutionMembershipResponse])
async def get_my_institutions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UserInstitutionMembershipResponse]:
    """
    Returns all active institutions the current user is a member of.
    """
    stmt = (
        select(InstitutionMembership, Institution)
        .join(Institution, Institution.id == InstitutionMembership.institution_id)
        .where(
            InstitutionMembership.user_id == current_user.id,
            InstitutionMembership.status == "active",
            Institution.is_active.is_(True),
        )
    )
    result = await db.execute(stmt)
    records = result.all()

    return [
        UserInstitutionMembershipResponse(
            membership_id=m.id,
            institution=InstitutionResponse.model_validate(inst),
            role=m.role,
            status=m.status,
        )
        for m, inst in records
    ]


@router.get("/current", response_model=InstitutionResponse)
async def get_current_institution(
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> InstitutionResponse:
    """
    Returns the currently active tenant institution resolved from X-Institution-Id
    or single-tenant membership.
    """
    stmt = select(Institution).where(Institution.id == tenant.institution_id)
    result = await db.execute(stmt)
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Current institution not found.",
        )
    return InstitutionResponse.model_validate(inst)


@router.get("/{institution_id}", response_model=InstitutionListItemResponse)
async def get_institution_detail(
    institution_id: uuid.UUID,
    current_admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_platform_admin_db),
) -> InstitutionListItemResponse:
    """
    Retrieves full institution details and membership breakdown.
    Restricted to verified Platform Administrators.
    """
    stmt = select(Institution).where(Institution.id == institution_id)
    result = await db.execute(stmt)
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Institution with id '{institution_id}' not found.",
        )

    counts_stmt = (
        select(
            InstitutionMembership.role,
            func.count(InstitutionMembership.id).label("count"),
        )
        .where(
            InstitutionMembership.institution_id == institution_id,
            InstitutionMembership.status == "active",
        )
        .group_by(InstitutionMembership.role)
    )
    counts_result = await db.execute(counts_stmt)
    counts = {"student": 0, "teacher": 0, "admin": 0}
    for role, cnt in counts_result.all():
        if role in counts:
            counts[role] = int(cnt)

    return InstitutionListItemResponse(
        id=inst.id,
        name=inst.name,
        slug=inst.slug,
        contact_email=inst.contact_email,
        is_active=inst.is_active,
        created_at=inst.created_at,
        updated_at=inst.updated_at,
        student_count=counts["student"],
        teacher_count=counts["teacher"],
        admin_count=counts["admin"],
        total_memberships=counts["student"] + counts["teacher"] + counts["admin"],
    )


@router.patch("/{institution_id}/status", response_model=InstitutionResponse)
async def update_institution_status(
    institution_id: uuid.UUID,
    data: InstitutionStatusUpdate,
    current_admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_platform_admin_db),
) -> InstitutionResponse:
    """
    Suspends or reactivates an institution.
    Restricted to verified Platform Administrators.
    """
    stmt = select(Institution).where(Institution.id == institution_id)
    result = await db.execute(stmt)
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Institution with id '{institution_id}' not found.",
        )

    inst.is_active = data.is_active
    await db.flush()
    await db.refresh(inst)
    return InstitutionResponse.model_validate(inst)

