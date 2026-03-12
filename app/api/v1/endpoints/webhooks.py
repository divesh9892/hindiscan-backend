import os
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from svix.webhooks import Webhook, WebhookVerificationError

from app.db.database import get_db
from app.db.models import User, CreditTransaction
from app.core.logger import log

router = APIRouter()

@router.post("/clerk")
async def clerk_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Receives secure lifecycle events directly from Clerk servers."""
    
    # Fetching inside the function ensures it grabs the latest env var
    CLERK_WEBHOOK_SECRET = os.environ.get("CLERK_WEBHOOK_SECRET")
    
    if not CLERK_WEBHOOK_SECRET:
        log.error("🚨 CLERK_WEBHOOK_SECRET is missing. Webhook rejected.")
        raise HTTPException(status_code=500, detail="Server configuration error.")

    # 1. Extract raw body and headers (Svix needs raw bytes to verify the hash)
    payload = await request.body()
    headers = request.headers

    # 2. Verify Cryptographic Signature using Svix
    # This automatically prevents Replay Attacks and Forgery
    wh = Webhook(CLERK_WEBHOOK_SECRET)
    try:
        event = wh.verify(payload, headers)
    except WebhookVerificationError as e:
        log.warning(f"🚨 Hacker Attempt - Webhook verification failed: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    except Exception as e:
        log.error(f"Unexpected error during webhook verification: {str(e)}")
        raise HTTPException(status_code=400, detail="Bad Request")

    # 3. Process the Event
    event_type = event.get("type")
    
    if event_type == "user.deleted":
        clerk_id = event["data"].get("id")
        
        if not clerk_id:
            return {"success": True, "message": "No user ID provided"}

        try:
            # 🚀 ACID Transaction for strict data cleanup
            async with db.begin():
                result = await db.execute(select(User).where(User.clerk_id == clerk_id))
                user = result.scalars().first()
                
                if user:
                    # 1. Delete all associated credit transactions first to prevent Foreign Key constraint crashes
                    await db.execute(CreditTransaction.__table__.delete().where(CreditTransaction.user_id == user.id))
                    
                    # 2. Delete the user
                    await db.delete(user)
                    log.warning(f"🚨 GDPR COMPLIANCE: User {user.email} and all billing records permanently wiped.")
                else:
                    log.info(f"Webhook received for deleted Clerk ID {clerk_id}, but they were already wiped from our DB.")
                    
        except Exception as e:
            # 🚀 WE MUST RAISE A 500 HERE! 
            # If we return 200, Clerk thinks it succeeded and won't retry.
            # If the DB fails, we want Clerk to retry later.
            log.error(f"Database error while deleting user {clerk_id}: {str(e)}")
            raise HTTPException(status_code=500, detail="Internal server error processing webhook")

    # Always return 200 OK for unhandled events or successful deletions so Clerk stops retrying
    return {"success": True}