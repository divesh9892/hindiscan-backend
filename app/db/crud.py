import traceback
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.models import User, ExtractionLog, CreditTransaction
from app.core.logger import log
from typing import Tuple, List, Optional
from app.db.models import CreditTransaction 

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
    If successful, safely deducts 1 credit PER PAGE and logs the transaction.
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

        # 2. Only deduct credits if extraction was 100% successful AND pages exist
        if success and pages > 0:
            # 🚀 Calculate the total cost (1 credit per page)
            total_cost = pages * 1 

            # 🚀 ENTERPRISE UPGRADE: Row-Level Locking
            result = await db.execute(
                select(User).where(User.id == user_id).with_for_update()
            )
            user = result.scalars().first()
            
            if user:
                # Deduct the dynamic total cost
                user.credit_balance -= total_cost 
                
                tx = CreditTransaction(
                    user_id=user_id, 
                    amount=-total_cost, # Log the dynamic total cost
                    transaction_type="extraction_deduction",
                    reference_id=original_filename
                )
                db.add(tx)

        # 3. Commit EVERYTHING together
        await db.commit()
        return True

    except Exception as e:
        log.error(f"Database Transaction Failed: {str(e)}")
        await db.rollback() # 🚀 The ACID Rollback! Protects the user's money.
        raise e

async def get_user_transactions(
    db: AsyncSession, 
    user_id: int, 
    limit: int = 10, 
    cursor: Optional[int] = None
) -> Tuple[List[CreditTransaction], bool, Optional[int]]:
    """
    Enterprise Cursor-Based Pagination for Financial Ledgers.
    """
    try:
        query = select(CreditTransaction).where(CreditTransaction.user_id == user_id)
        
        # Cursor filter: Only fetch rows strictly older than the provided ID
        if cursor:
            query = query.where(CreditTransaction.id < cursor)
            
        # Order by newest first, fetch LIMIT + 1 to detect if there's a next page
        query = query.order_by(CreditTransaction.id.desc()).limit(limit + 1)
        
        result = await db.execute(query)
        transactions = list(result.scalars().all())
        
        has_more = len(transactions) > limit
        next_cursor = None
        
        if has_more:
            # Drop the extra probe row
            transactions = transactions[:-1]
            # Set the cursor to the ID of the absolute last item in this batch
            next_cursor = transactions[-1].id
            
        return transactions, has_more, next_cursor

    except Exception as e:
        # 🚀 ENTERPRISE LOGGING: Capture the exact DB failure without crashing silently
        log.error(f"Database error fetching transactions for user {user_id}: {traceback.format_exc()}")
        raise e # Hand the error up to the router to convert into an HTTP response