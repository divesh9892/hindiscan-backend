from fastapi import APIRouter, Depends, HTTPException, Body, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import OperationalError
from pydantic import EmailStr # 🚀 ADDED: Strict Email Validation

from app.db.database import get_db
from app.db.models import User, CreditTransaction
from app.core.security import get_admin_user
from app.core.logger import log
from app.core.limiter import limiter

router = APIRouter()

@router.post("/grant-god-mode")
@limiter.limit("5/minute")
async def grant_god_mode(
    request: Request,
    # 🚀 FIX 1: Reject malformed strings. Must be a valid email format.
    target_email: EmailStr = Body(..., embed=True), 
    
    # 🚀 FIX 2: Boundary Enforcement. Must be between 1 and 100. No negatives, no overflows.
    credits_to_add: int = Body(100, embed=True, gt=0, le=100), 
    
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Enterprise endpoint to refill ANY user's credits securely."""
    try:
        # Lock the target user's row, nowait=True prevents the DB from freezing on spam clicks
        result = await db.execute(
            select(User).where(User.email == target_email).with_for_update(nowait=True)
        )
        target_user = result.scalars().first()
        
        if not target_user:
            raise HTTPException(status_code=404, detail=f"User {target_email} not found.")
        
        # Add the validated credits to the target user
        target_user.credit_balance += credits_to_add
        
        # Log the receipt in the ledger
        tx = CreditTransaction(
            user_id=target_user.id,
            amount=credits_to_add,
            transaction_type="god_mode_grant",
            reference_id=f"Granted by Admin: {admin.email}"
        )
        db.add(tx)
        
        # EXPLICIT COMMIT: Manually seal the transaction here
        await db.commit()
        await db.refresh(target_user)
        
        log.warning(f"🚨 GOD MODE: {admin.email} granted {credits_to_add} credits to {target_email}.")
        return {
            "status": "success",
            "message": f"Successfully granted {credits_to_add} credits to {target_email}.",
            "new_balance": target_user.credit_balance
        }
        
    except OperationalError:
        # Catch the spam click lock rejection
        await db.rollback()
        raise HTTPException(status_code=429, detail="Transaction in progress. Please click once and wait.")
    
    except HTTPException as http_exc:
        # Clean rollback for 404s
        await db.rollback()
        raise http_exc
       
    except Exception as e:
        # Global rollback for unexpected errors
        await db.rollback()
        log.error(f"Failed to grant God Mode credits: {str(e)}")
        raise HTTPException(status_code=500, detail="Database transaction failed during admin grant.")