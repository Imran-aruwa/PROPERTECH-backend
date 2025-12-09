from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.models.user import User, UserRole
from app.dependencies import get_current_user, require_role

router = APIRouter(prefix="/agent", tags=["agent"])

@router.get("/dashboard")
async def agent_dashboard(current_user: User = Depends(require_role(UserRole.AGENT)), db: AsyncSession = Depends(get_db)):
    return {"message": "Agent Dashboard", "user_id": current_user.id}

@router.get("/earnings")
async def agent_earnings(current_user: User = Depends(require_role(UserRole.AGENT)), db: AsyncSession = Depends(get_db)):
    return {"message": "Agent Earnings"}

@router.get("/properties")
async def agent_properties(current_user: User = Depends(require_role(UserRole.AGENT)), db: AsyncSession = Depends(get_db)):
    return {"message": "Agent Properties"}