from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Float, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class Trust(Base):
    __tablename__ = "trusts"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String, unique=True, index=True, nullable=True)  # Nullable for legacy rows
    reference_number = Column(String, unique=True, index=True)
    abn = Column(String, index=True, nullable=False)
    trust_name = Column(String, nullable=True)
    trustee_company = Column(String, nullable=True)
    is_high_risk = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    beneficiaries = relationship("Beneficiary", back_populates="trust", cascade="all, delete-orphan")
    red_flags = relationship("RedFlag", back_populates="trust", cascade="all, delete-orphan")
    reports = relationship("ComplianceReport", back_populates="trust", cascade="all, delete-orphan")

class Beneficiary(Base):
    __tablename__ = "beneficiaries"

    id = Column(Integer, primary_key=True, index=True)
    trust_id = Column(Integer, ForeignKey("trusts.id"))
    name = Column(String, index=True)
    role = Column(String)  # 'Beneficiary', 'Trustee', 'Appointor'
    is_corporate = Column(Boolean, default=False)

    trust = relationship("Trust", back_populates="beneficiaries")

class RedFlag(Base):
    __tablename__ = "red_flags"

    id = Column(Integer, primary_key=True, index=True)
    trust_id = Column(Integer, ForeignKey("trusts.id"))
    extracted_name = Column(String, index=True)
    watchlist_name = Column(String)
    match_score = Column(Float)
    action_required = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    trust = relationship("Trust", back_populates="red_flags")

class ComplianceReport(Base):
    __tablename__ = "compliance_reports"

    id = Column(Integer, primary_key=True, index=True)
    trust_id = Column(Integer, ForeignKey("trusts.id"))
    report_text = Column(String) # Stores the Claude markdown
    s3_key = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    trust = relationship("Trust", back_populates="reports")
