from fastapi import APIRouter, Depends
from app.db.models import User
from app.core.security import get_current_user

router = APIRouter()

@router.get("/me")
async def get_my_profile(user: User = Depends(get_current_user)):
    """Fetches the live credit balance for the dashboard header."""
    return {
        "email": user.email,
        "credit_balance": user.credit_balance
    }