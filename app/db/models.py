from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
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