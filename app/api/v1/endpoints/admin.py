from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.db.models import User, CreditTransaction
from app.core.security import get_admin_user

router = APIRouter()

@router.post("/grant-god-mode")
async def grant_god_mode(
    amount: int = 10000,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user) # 🚀 PROTECTED BY THE ADMIN GATEKEEPER
):
    """Secret endpoint to refill the admin's testing credits."""
    
    # 1. Add the credits
    admin.credit_balance += amount
    
    # 2. Log the receipt in the ledger so the math stays perfect
    tx = CreditTransaction(
        user_id=admin.id,
        amount=amount,
        transaction_type="admin_grant",
        reference_id="god_mode_activation"
    )
    
    db.add(tx)
    await db.commit()
    
    return {
        "status": "success",
        "message": "God Mode Activated ⚡",
        "email": admin.email,
        "new_balance": admin.credit_balance
    }