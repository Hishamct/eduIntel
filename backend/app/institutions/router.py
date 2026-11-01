import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import TenantContext, get_tenant_context
from app.institutions.models import Institution, InstitutionMembership
from app.institutions.schemas import InstitutionResponse
from app.users.dependencies import get_current_user
from app.users.models import User

router = APIRouter(prefix="/institutions", tags=["institutions"])


class UserInstitutionMembershipResponse(BaseModel):
    membership_id: uuid.UUID
    institution: InstitutionResponse
    role: str
    status: str


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
