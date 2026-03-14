import traceback
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.db.database import get_db
from app.db.models import User, PaymentOrder, CreditTransaction
from app.core.security import get_current_user
from app.db import crud
from app.core.logger import log

from pydantic import BaseModel
from sqlalchemy.future import select
from app.core.payment_gateway import gateway

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
    


# 🚀 1. PRICING DICTIONARY (Single Source of Truth)
# Hackers cannot change prices if the backend dictates them.
PLAN_PRICING = {
    "essential": {"price_inr": 49, "credits": 50},
    "pro": {"price_inr": 99, "credits": 120}
}

# 🚀 2. DTO SCHEMAS
class CreateOrderRequest(BaseModel):
    plan_id: str # "essential" or "pro"

class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str

# 🚀 3. ENDPOINT: CREATE ORDER
@router.post("/create-order")
async def create_payment_order(
    payload: CreateOrderRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    plan = PLAN_PRICING.get(payload.plan_id.lower())
    if not plan:
        raise HTTPException(status_code=400, detail="Invalid plan selected.")

    amount_paise = plan["price_inr"] * 100 # Convert to smallest currency unit
    
    # 1. Ask the Gateway (Mock or Real) for an Order ID
    try:
        razorpay_order = gateway.create_order(
            amount_paise=amount_paise,
            receipt_id=f"receipt_user_{user.id}"
        )
    except Exception as e:
        log.error(f"Failed to communicate with payment gateway: {str(e)}")
        raise HTTPException(status_code=502, detail="Payment gateway is currently unavailable.")

    # 2. Save the pending order to our Database
    new_order = PaymentOrder(
        user_id=user.id,
        razorpay_order_id=razorpay_order["id"],
        amount_paise=amount_paise,
        plan_id=payload.plan_id,
        credits_added=plan["credits"],
        status="created"
    )
    
    db.add(new_order)
    await db.commit()
    
    return {
        "order_id": razorpay_order["id"],
        "amount": amount_paise,
        "currency": "INR"
    }

# 🚀 4. ENDPOINT: VERIFY PAYMENT & GRANT CREDITS
@router.post("/verify-payment")
async def verify_payment(
    payload: VerifyPaymentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    # 1. Fetch the order from DB using a strict Row Lock (prevents concurrent double-spend attacks)
    result = await db.execute(
        select(PaymentOrder)
        .where(PaymentOrder.razorpay_order_id == payload.razorpay_order_id)
        .with_for_update(nowait=True)
    )
    order = result.scalars().first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    
    # Security Check 1: Does this order belong to the person asking?
    if order.user_id != user.id:
        raise HTTPException(status_code=403, detail="Unauthorized.")
        
    # Security Check 2: Prevent Replay Attacks (Has this already been paid?)
    if order.status == "paid":
        return {"status": "success", "message": "Already processed", "new_balance": user.credit_balance}

    # 2. Cryptographic Signature Verification
    is_valid = gateway.verify_signature(
        order_id=payload.razorpay_order_id,
        payment_id=payload.razorpay_payment_id,
        signature=payload.razorpay_signature
    )

    if not is_valid:
        order.status = "failed"
        await db.commit()
        raise HTTPException(status_code=400, detail="Payment signature verification failed. Potential fraud detected.")

    # 3. Success! Grant the credits to the user
    user.credit_balance += order.credits_added
    
    # 4. Mark Order as Paid and save identifiers
    order.status = "paid"
    order.razorpay_payment_id = payload.razorpay_payment_id
    order.razorpay_signature = payload.razorpay_signature

    # 5. Create a financial audit log
    tx = CreditTransaction(
        user_id=user.id,
        amount=order.credits_added,
        transaction_type="purchase",
        reference_id=f"Razorpay Payment: {payload.razorpay_payment_id}"
    )
    db.add(tx)
    
    await db.commit()
    await db.refresh(user)

    log.info(f"💰 SUCCESS: User {user.email} bought {order.credits_added} credits via Mock Gateway.")

    return {
        "status": "success",
        "message": f"Successfully added {order.credits_added} credits!",
        "new_balance": user.credit_balance
    }