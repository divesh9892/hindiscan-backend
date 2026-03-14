import os
import jwt
import asyncio
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from clerk_backend_api import Clerk

from app.db.database import get_db
from app.db.models import User, CreditTransaction
from app.core.logger import log, request_user_ctx # 🚀 Imported the context vault

security = HTTPBearer()
clerk_client = Clerk(bearer_auth=os.environ.get("CLERK_SECRET_KEY"))
CLERK_PUBLIC_KEY = os.environ.get("CLERK_PUBLIC_KEY")

def fetch_clerk_user_sync(clerk_id: str):
    """Isolates the synchronous Clerk SDK call so we can thread it."""
    return clerk_client.users.get(user_id=clerk_id)

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    
    token = credentials.credentials
    
    if not CLERK_PUBLIC_KEY:
        log.error("CLERK_PUBLIC_KEY is missing from .env!")
        raise HTTPException(status_code=500, detail="Server auth misconfiguration")

    # --- 1. LOCAL CRYPTOGRAPHIC VALIDATION ---
    try:
        payload = jwt.decode(token, key=CLERK_PUBLIC_KEY, algorithms=["RS256"])
        clerk_id = payload.get("sub") 
        if not clerk_id:
            raise HTTPException(status_code=401, detail="Invalid token payload.")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Authentication session has expired. Please log in again.")
    except jwt.PyJWTError as e:
        log.error(f"JWT Validation failed: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid authentication token.")

    # --- 2. DATABASE SYNC ---
    result = await db.execute(select(User).where(User.clerk_id == clerk_id))
    user = result.scalars().first()

    if not user:
        try:
            # 🚀 LOOPHOLE CLOSED: Threaded the synchronous Clerk API call
            clerk_user_info = await asyncio.to_thread(fetch_clerk_user_sync, clerk_id)
            email = clerk_user_info.email_addresses[0].email_address
        except Exception as e:
            log.error(f"Failed to fetch user email from Clerk: {str(e)}")
            email = f"{clerk_id}@unknown.com" 
            
        log.info(f"🎉 New user registration detected: {email}")
        
        user = User(clerk_id=clerk_id, email=email, credit_balance=3)
        db.add(user)
        
        try:
            await db.flush() 
            
            tx = CreditTransaction(
                user_id=user.id, 
                amount=3, 
                transaction_type="signup_bonus",
                reference_id="signup_bonus"
            )
            db.add(tx)
            
            await db.commit()
            await db.refresh(user)
            
        except IntegrityError:
            await db.rollback()
            log.warning(f"Concurrent registration caught for {email}. Fetching existing user.")
            
            result = await db.execute(select(User).where(User.clerk_id == clerk_id))
            user = result.scalars().first()
            
            if not user:
                raise HTTPException(status_code=401, detail="Authentication collision. Please try again.")

    # 🚀 THE MAGIC: Stamp the current context with the user's email for the logger!
    request_user_ctx.set(user.email)
    
    return user

async def get_admin_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Strict Admin Gatekeeper. 
    Verifies the token, fetches the live user profile from Clerk, and checks for the Admin tag.
    """
    token = credentials.credentials
    
    try:
        payload = jwt.decode(token, key=CLERK_PUBLIC_KEY, algorithms=["RS256"])
        clerk_id = payload.get("sub")
        if not clerk_id:
            raise HTTPException(status_code=401, detail="Invalid token payload.")
        
        try:
            # 🚀 LOOPHOLE CLOSED: Threaded the synchronous Clerk API call
            clerk_user_info = await asyncio.to_thread(fetch_clerk_user_sync, clerk_id)
            metadata = clerk_user_info.public_metadata or {}
            
            if metadata.get("role") != "admin":
                log.warning(f"Unauthorized admin access attempt by {clerk_id}")
                raise HTTPException(status_code=403, detail="Forbidden. Enterprise Admin access required.")
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            log.error(f"Clerk API error verifying admin: {str(e)}")
            raise HTTPException(status_code=403, detail="Forbidden. Admin verification failed.")
            
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")

    result = await db.execute(select(User).where(User.clerk_id == clerk_id))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Admin user not found in database.")
        
    # 🚀 Stamp the admin's context
    request_user_ctx.set(f"ADMIN: {user.email}")
        
    return user