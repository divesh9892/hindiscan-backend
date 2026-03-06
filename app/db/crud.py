from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.models import User, ExtractionLog, CreditTransaction
from app.core.logger import log

async def get_or_create_dev_user(db: AsyncSession, email: str = "dev@hindiscan.com") -> User:
    """Temporary helper to give us a user to bill before Clerk Auth is added."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    
    if not user:
        log.info(f"Creating default Dev User: {email}")
        user = User(clerk_id="dev_clerk_123", email=email, credit_balance=3)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        
        # Log the initial 3 free credits in the transaction ledger
        tx = CreditTransaction(user_id=user.id, amount=3, transaction_type="signup_bonus")
        db.add(tx)
        await db.commit()
        
    return user

async def log_and_bill_extraction(
    db: AsyncSession, 
    user_id: int, 
    original_filename: str, 
    pages: int, 
    success: bool, 
    error_msg: str = None
):
    """
    Atomic transaction: Logs the extraction attempt. 
    If successful, safely deducts 1 credit and logs the transaction.
    """
    try:
        # 1. Create the receipt for the extraction
        extraction_log = ExtractionLog(
            user_id=user_id,
            original_filename=original_filename,
            pages_processed=pages,
            status="success" if success else "failed",
            error_message=error_msg
        )
        db.add(extraction_log)

        # 2. Only deduct credits if the extraction was 100% successful
        if success:
            # 🚀 ENTERPRISE UPGRADE: Row-Level Locking
            # This locks the user's row so concurrent requests wait in line.
            result = await db.execute(
                select(User).where(User.id == user_id).with_for_update()
            )
            user = result.scalars().first()
            
            if user:
                user.credit_balance -= 1 
                
                tx = CreditTransaction(
                    user_id=user_id, 
                    amount=-1, 
                    transaction_type="extraction_deduction",
                    reference_id=original_filename
                )
                db.add(tx)

        # 3. Commit EVERYTHING together. If the server crashes here, nothing is saved.
        await db.commit()
        return True

    except Exception as e:
        log.error(f"Database Transaction Failed: {str(e)}")
        await db.rollback() # 🚀 The ACID Rollback! Protects the user's money.
        raise e