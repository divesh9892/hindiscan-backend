from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, func
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    # clerk_id is the unique identifier given by Clerk (whether they use Google Auth or Email)
    clerk_id = Column(String, unique=True, index=True, nullable=False) 
    email = Column(String, unique=True, index=True, nullable=False)
    
    # Billing
    credit_balance = Column(Integer, default=3) # Everyone starts with 3 free credits
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    extractions = relationship("ExtractionLog", back_populates="owner")
    transactions = relationship("CreditTransaction", back_populates="owner")

class ExtractionLog(Base):
    __tablename__ = "extraction_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    original_filename = Column(String, nullable=False)
    pages_processed = Column(Integer, nullable=False)
    
    status = Column(String, default="success") # "success" or "failed"
    error_message = Column(Text, nullable=True) # If failed, what was the exact Python/Gemini error?
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship back to the user
    owner = relationship("User", back_populates="extractions")

class CreditTransaction(Base):
    """An immutable ledger of every time a user's credit balance changes."""
    __tablename__ = "credit_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    amount = Column(Integer, nullable=False) # e.g., +50 (purchase), -2 (extraction), +10000 (admin grant)
    transaction_type = Column(String, nullable=False) # e.g., "signup_bonus", "extraction_deduction", "admin_grant", "razorpay_purchase"
    reference_id = Column(String, nullable=True) # E.g., The Razorpay Payment ID or the ExtractionLog ID
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship back to the user
    owner = relationship("User", back_populates="transactions")

class PaymentOrder(Base):
    __tablename__ = "payment_orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # 🚀 The Razorpay Identifiers
    razorpay_order_id = Column(String(255), unique=True, index=True, nullable=False)
    razorpay_payment_id = Column(String(255), unique=True, index=True, nullable=True)
    razorpay_signature = Column(String(255), nullable=True)
    
    # 💰 The Financials
    amount_paise = Column(Integer, nullable=False) # Always store money in the smallest unit (paise/cents) to avoid float math errors
    currency = Column(String(3), default="INR", nullable=False)
    status = Column(String(50), default="created", nullable=False) # created, paid, failed
    
    # 📦 What did they buy?
    plan_id = Column(String(50), nullable=False) # e.g., "essential", "pro"
    credits_added = Column(Integer, nullable=False) # How many credits to grant upon success
    
    # 🕒 Audit Trail
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship to User
    user = relationship("User", backref="payment_orders")

class ExtractionTask(Base):
    """Replaces the in-memory TASK_STORE for horizontally scalable, multi-worker task tracking."""
    __tablename__ = "extraction_tasks"

    id = Column(String(36), primary_key=True, index=True) # UUID
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Task State
    status = Column(String(50), default="processing", nullable=False)
    progress = Column(Integer, default=0)
    message = Column(String(255), default="Initializing...")
    
    # File References
    temp_dir = Column(String(255), nullable=True)
    excel_path = Column(String(255), nullable=True)
    json_path = Column(String(255), nullable=True)
    export_filename = Column(String(255), nullable=True)
    error_detail = Column(Text, nullable=True)
    
    # Lifecycle Management (For the Garbage Collector)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True) 

    user = relationship("User", backref="extraction_tasks")