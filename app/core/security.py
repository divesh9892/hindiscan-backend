import os
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError # 🚀 ADD THIS IMPORT
from clerk_backend_api import Clerk

from app.db.database import get_db
from app.db.models import User, CreditTransaction
from app.core.logger import log

security = HTTPBearer()
clerk_client = Clerk(bearer_auth=os.environ.get("CLERK_SECRET_KEY"))
CLERK_PUBLIC_KEY = os.environ.get("CLERK_PUBLIC_KEY")

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
            # Note: For production, using async httpx to call Clerk's API is faster, 
            # but the synchronous Clerk SDK is perfectly fine for MVP user creation.
            clerk_user_info = clerk_client.users.get(user_id=clerk_id)
            email = clerk_user_info.email_addresses[0].email_address
        except Exception as e:
            log.error(f"Failed to fetch user email from Clerk: {str(e)}")
            email = f"{clerk_id}@unknown.com" 
            
        log.info(f"🎉 New user registration detected: {email}")
        
        user = User(clerk_id=clerk_id, email=email, credit_balance=3)
        db.add(user)
        
        tx = CreditTransaction(
            user_id=user.id, 
            amount=3, 
            transaction_type="signup_bonus",
            reference_id="clerk_signup"
        )
        db.add(tx)
        
        try:
            # Attempt to save the user and credits
            await db.commit()
            await db.refresh(user)
        except IntegrityError:
            # 🚀 RACE CONDITION CAUGHT!
            # Another request just created this user. Rollback our attempt.
            await db.rollback()
            log.warning(f"Concurrent registration caught for {email}. Fetching existing user.")
            
            # Re-fetch the newly created user
            result = await db.execute(select(User).where(User.clerk_id == clerk_id))
            user = result.scalars().first()

    return user

async def get_admin_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Strict Admin Gatekeeper. 
    Verifies the token, checks for the Admin cryptographic tag, and returns the DB user.
    """
    token = credentials.credentials
    
    try:
        # Decode the token locally
        payload = jwt.decode(token, key=CLERK_PUBLIC_KEY, algorithms=["RS256"])
        clerk_id = payload.get("sub")
        
        # 🚀 CHECK THE METADATA WE JUST ADDED IN THE DASHBOARD
        public_metadata = payload.get("public_metadata", {})
        if public_metadata.get("role") != "admin":
            log.warning(f"Unauthorized admin access attempt by {clerk_id}")
            raise HTTPException(status_code=403, detail="Forbidden. Enterprise Admin access required.")
            
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")

    # Fetch the user from the database
    result = await db.execute(select(User).where(User.clerk_id == clerk_id))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Admin user not found in database.")
        
    return user