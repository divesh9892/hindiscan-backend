from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.db.models import User, CreditTransaction
from app.core.security import get_admin_user
from app.core.logger import log

router = APIRouter()

@router.post("/grant-god-mode")
async def grant_god_mode(
    amount: int = 10000,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user) # 🚀 PROTECTED BY THE ADMIN GATEKEEPER
):
    """Secret endpoint to refill the admin's testing credits securely."""
    try:
        # 🚀 ENTERPRISE UPGRADE: Strict ACID Transaction Block
        async with db.begin():
            # 1. Add the credits to the user
            admin.credit_balance += amount
            
            # 2. Log the receipt in the ledger so the math stays perfect
            tx = CreditTransaction(
                user_id=admin.id,
                amount=amount,
                transaction_type="admin_grant",
                reference_id="god_mode_activation"
            )
            
            db.add(tx)
            
        # 🚀 If we reach this line, SQLAlchemy safely COMMITS everything.
        log.info(f"⚡ God Mode activated for admin: {admin.email} (+{amount} credits)")
        return {
            "status": "success",
            "message": "God Mode Activated ⚡",
            "email": admin.email,
            "new_balance": admin.credit_balance
        }
        
    except Exception as e:
        # 🚀 If ANYTHING fails inside the block, SQLAlchemy automatically ROLLS BACK.
        log.error(f"Failed to grant God Mode credits: {str(e)}")
        raise HTTPException(status_code=500, detail="Database transaction failed during admin grant.")