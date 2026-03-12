import traceback
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.db.database import get_db
from app.db.models import User
from app.core.security import get_current_user
from app.db import crud
from app.core.logger import log

router = APIRouter()

@router.get("/history")
async def get_billing_history(
    limit: int = Query(10, ge=1, le=50, description="Max transactions per request"),
    cursor: Optional[int] = Query(None, description="The ID of the last transaction seen"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetches the user's transaction ledger using secure cursor-based pagination.
    """
    try:
        log.info(f"Fetching billing history for user {user.id} | Limit: {limit} | Cursor: {cursor}")
        
        transactions, has_more, next_cursor = await crud.get_user_transactions(
            db=db, 
            user_id=user.id, 
            limit=limit, 
            cursor=cursor
        )
        
        # Sanitize and format data for the frontend
        formatted_tx = [
            {
                "id": tx.id,
                "amount": tx.amount,
                "transaction_type": tx.transaction_type,
                "reference_id": tx.reference_id,
                "created_at": tx.created_at.isoformat() if tx.created_at else None
            }
            for tx in transactions
        ]
        
        log.info(f"Successfully retrieved {len(formatted_tx)} transactions for user {user.id}.")
        
        return {
            "data": formatted_tx,
            "pagination": {
                "has_more": has_more,
                "next_cursor": next_cursor
            }
        }
        
    except Exception as e:
        # 🚀 SAFEGUARD: The user gets a clean error; your server logs get the raw traceback.
        log.error(f"Failed to fetch billing history for user {user.id}: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, 
            detail="An internal error occurred while retrieving your billing history. Please try again later."
        )