from __future__ import annotations

import enum
import sqlalchemy as sql
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey, Enum, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, relationship
from datetime import datetime
import uuid


class Base(DeclarativeBase):
    pass


class ProjectStatus(str, enum.Enum):
    CREATED = "created"
    INTERPRETING = "interpreting"
    ANALYZING = "analyzing"
    OUTLINING = "outlining"
    GENERATING = "generating"
    CHECKING = "checking"
    FORMATTING = "formatting"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class DocumentType(str, enum.Enum):
    TENDER = "tender"
    BID = "bid"
    TEMPLATE = "template"
    REFERENCE = "reference"


class CheckType(str, enum.Enum):
    COMPLIANCE = "compliance"
    DISQUALIFICATION = "disqualification"
    DUPLICATE = "duplicate"
    CONSISTENCY = "consistency"
    FORMAT = "format"
    QUALIFICATION = "qualification"
    DEPOSIT = "deposit"
    SIGNATURE = "signature"
    PRICING = "pricing"
    MANDATORY = "mandatory"
    VALIDITY = "validity"
    SELFCHECK = "selfcheck"
    FIT_SCORE = "fit_score"
    AI_TEXT = "ai_text"
    CROSS_CHECK = "cross_check"
    SAMPLE_REPORT = "sample_report"
    JOINT_BID = "joint_bid"
    EBID_SUBMIT = "ebid_submit"
    PRICING_LOGIC = "pricing_logic"
    DOC_INTEGRITY = "doc_integrity"
    RISK_SCORE = "risk_score"


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    PROJECT_MANAGER = "project_manager"
    WRITER = "writer"
    REVIEWER = "reviewer"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.WRITER)
    avatar = Column(String(500), nullable=True)
    password_hash = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    projects = relationship("Project", back_populates="user")


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    status = Column(Enum(ProjectStatus), default=ProjectStatus.CREATED, index=True)
    tender_doc_id = Column(UUID, ForeignKey("documents.id"), nullable=True)
    config = Column(JSONB, default=dict)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    user = relationship("User", back_populates="projects")
    documents = relationship("Document", back_populates="project", foreign_keys="Document.project_id")
    analysis = relationship("Analysis", back_populates="project", uselist=False)
    outline = relationship("Outline", back_populates="project", uselist=False)
    chapters = relationship("Chapter", back_populates="project")
    check_reports = relationship("CheckReport", back_populates="project")


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID, ForeignKey("projects.id"), nullable=True, index=True)
    type = Column(Enum(DocumentType), default=DocumentType.TENDER)
    file_path = Column(String(500), nullable=False)
    original_name = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=True)
    parsed_content = Column(Text, nullable=True)
    metadata = Column(JSONB, default=dict)
    created_at = Column(DateTime, default=datetime.now)

    project = relationship("Project", back_populates="documents", foreign_keys=[project_id])


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID, ForeignKey("projects.id"), nullable=False, unique=True, index=True)
    dimensions = Column(JSONB, default=dict)
    scoring_matrix = Column(JSONB, default=dict)
    risk_flags = Column(JSONB, default=dict)
    sections = Column(JSONB, default=list)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    project = relationship("Project", back_populates="analysis")


class Outline(Base):
    __tablename__ = "outlines"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID, ForeignKey("projects.id"), nullable=False, unique=True, index=True)
    mode = Column(String(20), default="aligned")
    tree = Column(JSONB, default=dict)
    score_mapping = Column(JSONB, default=dict)
    reviewed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    project = relationship("Project", back_populates="outline")


class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID, ForeignKey("projects.id"), nullable=False, index=True)
    outline_id = Column(UUID, ForeignKey("outlines.id"), nullable=True)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=True)
    mode = Column(String(10), default="A")
    status = Column(String(20), default="pending")
    word_count = Column(Integer, default=0)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    project = relationship("Project", back_populates="chapters")


class CheckReport(Base):
    __tablename__ = "check_reports"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID, ForeignKey("projects.id"), nullable=False, index=True)
    type = Column(Enum(CheckType), nullable=False, index=True)
    results = Column(JSONB, default=dict)
    risk_level = Column(String(20), default="low")
    summary = Column(JSONB, default=dict)
    created_at = Column(DateTime, default=datetime.now)

    project = relationship("Project", back_populates="check_reports")


class SkillConfig(Base):
    __tablename__ = "skill_configs"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False)
    category = Column(String(50), nullable=False)
    version = Column(String(20), default="1.0.0")
    config = Column(JSONB, default=dict)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)


class AgentConfig(Base):
    __tablename__ = "agent_configs"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False)
    workflow_dsl = Column(JSONB, default=dict)
    skills = Column(JSONB, default=list)
    config = Column(JSONB, default=dict)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, ForeignKey("users.id"), nullable=False, index=True)
    channel = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(20), default="pending")
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    doc_count = Column(Integer, default=0)
    embedding_model = Column(String(100), default="text-embedding-v3")
    collection_name = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class MonitoringTask(Base):
    __tablename__ = "monitoring_tasks"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    keywords = Column(Text, nullable=False)
    exclude_keywords = Column(Text, default="")
    must_contain_keywords = Column(Text, default="")
    sites = Column(JSONB, default=list)
    interval_minutes = Column(Integer, default=60)
    enabled = Column(Boolean, default=True)
    last_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class CrawlResult(Base):
    __tablename__ = "crawl_results"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID, ForeignKey("monitoring_tasks.id"), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    url = Column(String(1000), nullable=False)
    source = Column(String(500), default="")
    pub_date = Column(String(50), nullable=True)
    content = Column(Text, nullable=True)
    keyword_score = Column(Float, default=0.0)
    relevance_score = Column(Float, default=0.0)
    category = Column(String(50), default="general")
    is_hot = Column(Boolean, default=False)
    hot_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.now)


class RBACRole(Base):
    __tablename__ = "rbac_roles"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    is_system = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)


class RBACPermission(Base):
    __tablename__ = "rbac_permissions"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    code = Column(String(200), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    category = Column(String(100), nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)


class RBACUserRole(Base):
    __tablename__ = "rbac_user_roles"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, ForeignKey("users.id"), nullable=False, index=True)
    role_id = Column(UUID, ForeignKey("rbac_roles.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now)


class RBACRolePermission(Base):
    __tablename__ = "rbac_role_permissions"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    role_id = Column(UUID, ForeignKey("rbac_roles.id"), nullable=False, index=True)
    permission_id = Column(UUID, ForeignKey("rbac_permissions.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now)
