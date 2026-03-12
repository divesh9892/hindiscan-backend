import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.future import select

from app.db.database import Base
from app.db.models import User, ExtractionLog, CreditTransaction
from app.db import crud

# 🚀 Use an invisible, in-memory database for lightning-fast testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# Setup the isolated test engine
engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    """Creates fresh tables before every single test, and drops them after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest_asyncio.fixture
async def db_session():
    """Provides a fresh database session for the test."""
    async with TestingSessionLocal() as session:
        yield session

@pytest.mark.asyncio
async def test_dev_user_creation(db_session):
    """Proves the system correctly sets up a new user with 3 free credits."""
    user = await crud.get_or_create_dev_user(db_session)
    
    assert user.email == "dev@hindiscan.com"
    assert user.credit_balance == 3
    
    # Check if the signup bonus was logged in the ledger
    result = await db_session.execute(select(CreditTransaction).where(CreditTransaction.user_id == user.id))
    transactions = result.scalars().all()
    
    assert len(transactions) == 1
    assert transactions[0].amount == 3
    assert transactions[0].transaction_type == "signup_bonus"

@pytest.mark.asyncio
async def test_successful_extraction_billing(db_session):
    """Proves a successful extraction deducts exactly 1 credit PER PAGE and logs all receipts."""
    user = await crud.get_or_create_dev_user(db_session)
    
    await crud.log_and_bill_extraction(
        db=db_session,
        user_id=user.id,
        original_filename="test_doc.pdf",
        pages=2,
        success=True
    )
    
    # 1. Did the balance drop?
    updated_user = await db_session.get(User, user.id)
    assert updated_user.credit_balance == 1
    
    # 2. Was the extraction receipt created?
    result_logs = await db_session.execute(select(ExtractionLog).where(ExtractionLog.user_id == user.id))
    logs = result_logs.scalars().all()
    assert len(logs) == 1
    assert logs[0].status == "success"
    assert logs[0].pages_processed == 2
    
    # 3. Was the exact -1 deduction logged in the bank ledger?
    result_tx = await db_session.execute(
            select(CreditTransaction)
            .where(CreditTransaction.user_id == user.id)
            .where(CreditTransaction.transaction_type == "extraction_deduction")
        )
    deductions = result_tx.scalars().all()
    assert len(deductions) == 1
    assert deductions[0].amount == -2

@pytest.mark.asyncio
async def test_failed_extraction_protection(db_session):
    """Proves a failed extraction logs the error but KEEPS the user's credits safe."""
    user = await crud.get_or_create_dev_user(db_session)
    
    await crud.log_and_bill_extraction(
        db=db_session,
        user_id=user.id,
        original_filename="broken_doc.pdf",
        pages=0,
        success=False,
        error_msg="AI failed to read blurred image"
    )
    
    # 1. Did we protect their money? Balance should still be 3.
    updated_user = await db_session.get(User, user.id)
    assert updated_user.credit_balance == 3
    
    # 2. Was the failure logged so the admin can debug it?
    result_logs = await db_session.execute(select(ExtractionLog).where(ExtractionLog.user_id == user.id))
    logs = result_logs.scalars().all()
    assert len(logs) == 1
    assert logs[0].status == "failed"
    assert logs[0].error_message == "AI failed to read blurred image"
    
    # 3. Prove NO deductions were added to the ledger
    result_tx = await db_session.execute(select(CreditTransaction).where(CreditTransaction.amount == -1))
    deductions = result_tx.scalars().all()
    assert len(deductions) == 0

@pytest.mark.asyncio
async def test_cursor_pagination_logic(db_session):
    """
    Proves that the enterprise cursor fetches the exact correct batches 
    without duplicating or dropping any transactions.
    """
    # 1. Create an isolated test user
    test_user = User(clerk_id="paginator_123", email="page@hindiscan.com", credit_balance=50)
    db_session.add(test_user)
    await db_session.flush()

    # 2. Inject exactly 15 transactions
    for i in range(15):
        tx = CreditTransaction(
            user_id=test_user.id,
            amount=-1,
            transaction_type="test_deduction",
            reference_id=f"doc_scan_{i}"
        )
        db_session.add(tx)
    
    await db_session.commit()

    # 🚀 3. FETCH PAGE 1 (Limit 10)
    page1, has_more1, next_cursor1 = await crud.get_user_transactions(
        db=db_session, 
        user_id=test_user.id, 
        limit=10
    )
    
    assert len(page1) == 10
    assert has_more1 is True
    assert next_cursor1 is not None
    # Ensure it's sorted newest to oldest (ID descending)
    assert page1[0].id > page1[-1].id 

    # 🚀 4. FETCH PAGE 2 (Using the cursor from Page 1)
    page2, has_more2, next_cursor2 = await crud.get_user_transactions(
        db=db_session, 
        user_id=test_user.id, 
        limit=10, 
        cursor=next_cursor1
    )
    
    assert len(page2) == 5 # 15 total - 10 from page 1 = 5 remaining
    assert has_more2 is False
    assert next_cursor2 is None

    # 🚀 5. THE ULTIMATE SECURITY CHECK: Zero Duplication
    page1_ids = {tx.id for tx in page1}
    page2_ids = {tx.id for tx in page2}
    
    # The intersection of both sets must be completely empty
    assert len(page1_ids.intersection(page2_ids)) == 0