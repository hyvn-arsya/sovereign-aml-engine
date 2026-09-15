from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Float, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class Trust(Base):
    __tablename__ = "trusts"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String, unique=True, index=True, nullable=True)  # Nullable for legacy rows
    processing_key = Column(String, unique=True, index=True, nullable=True)  # Deterministic idempotency key
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


class Tenant(Base):
    """Tenant — identifies the API consumer that owns a job or key."""

    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    api_keys = relationship("ApiKey", back_populates="tenant", cascade="all, delete-orphan")


class ApiKey(Base):
    """Stored API key (salted SHA-256 hash).  The plaintext is never persisted."""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    key_hash = Column(String, unique=True, nullable=False, index=True)
    key_prefix = Column(String, nullable=False)  # first 8 chars of hex hash for display
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    tenant = relationship("Tenant", back_populates="api_keys")


class AnalysisJob(Base):
    """Async screening job (Phase 3+: maps to an SQS/Fargate worker)."""

    __tablename__ = "analysis_jobs"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String, unique=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    abn = Column(String, index=True, nullable=False)
    status = Column(String, index=True, default="queued")  # queued|running|completed|failed|blocked
    compliance_memo = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class PipelineRun(Base):
    """
    Idempotent execution record for a single pipeline run (Priority 2).

    One row per processing attempt; drives spot checks like
    AVG(duration_ms), AVG(chunk_count), AVG(entity_count), SUM(red_flag_count)
    over completed runs.
    """

    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String, unique=True, index=True)
    processing_key = Column(String, unique=True, index=True)  # Deterministic processing identity
    abn = Column(String, index=True, nullable=False)
    status = Column(String, index=True, default="running")  # running|completed|failed
    chunk_count = Column(Integer, default=0)
    entity_count = Column(Integer, default=0)
    red_flag_count = Column(Integer, default=0)
    duration_ms = Column(Integer, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class Entity(Base):
    """Canonical entity resolved from the trust deed (Priority 4)."""

    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, index=True)
    canonical_name = Column(String, index=True, nullable=False)
    entity_type = Column(String, index=True)  # Beneficiary|Trustee|Appointor|Corporate
    source_trust_id = Column(Integer, ForeignKey("trusts.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    aliases = relationship("EntityAlias", back_populates="entity", cascade="all, delete-orphan")
    matches = relationship("ScreeningMatch", back_populates="entity", cascade="all, delete-orphan")


class EntityAlias(Base):
    """Alternative names for an entity (nicknames, diminutives, legal variants)."""

    __tablename__ = "entity_aliases"

    id = Column(Integer, primary_key=True, index=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), index=True)
    alias = Column(String, index=True, nullable=False)
    alias_type = Column(String, default="nickname")  # nickname|diminutive|legal_variant

    entity = relationship("Entity", back_populates="aliases")


class ScreeningMatch(Base):
    """
    Persisted screening hit (Priority 4).

    match_method distinguishes a direct name match from one that required
    alias expansion (e.g. "Bob Smith" -> "Robert Smith").
    """

    __tablename__ = "screening_matches"

    id = Column(Integer, primary_key=True, index=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), index=True)
    watchlist_name = Column(String, index=True)
    watchlist_type = Column(String)
    match_score = Column(Float)
    match_method = Column(String, index=True)  # direct|alias_expansion
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    entity = relationship("Entity", back_populates="matches")
