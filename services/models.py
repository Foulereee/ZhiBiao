from __future__ import annotations

import enum
import sqlalchemy as sql
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey, Enum, JSON, UniqueConstraint
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import DeclarativeBase, relationship
from datetime import datetime, timezone
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
    FULL_CHECK = "full_check"
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


def _uuid_default():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    role = Column(String(20), default=UserRole.WRITER.value)
    avatar = Column(String(500), nullable=True)
    password_hash = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now, onupdate=lambda: datetime.now(timezone.utc))

    projects = relationship("Project", back_populates="user")


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    status = Column(String(50), default=ProjectStatus.CREATED.value, index=True)
    tender_doc_id = Column(String(36), ForeignKey("documents.id"), nullable=True)
    config = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now, onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="projects")
    documents = relationship("Document", back_populates="project", foreign_keys="Document.project_id")
    analysis = relationship("Analysis", back_populates="project", uselist=False)
    outline = relationship("Outline", back_populates="project", uselist=False)
    chapters = relationship("Chapter", back_populates="project")
    check_reports = relationship("CheckReport", back_populates="project")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    type = Column(String(20), default=DocumentType.TENDER.value)
    file_path = Column(String(500), nullable=False)
    original_name = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=True)
    parsed_content = Column(MEDIUMTEXT, nullable=True)
    doc_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="documents", foreign_keys=[project_id])


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, unique=True, index=True)
    dimensions = Column(JSON, default=dict)
    scoring_matrix = Column(JSON, default=dict)
    risk_flags = Column(JSON, default=dict)
    sections = Column(JSON, default=list)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now, onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="analysis")


class Outline(Base):
    __tablename__ = "outlines"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, unique=True, index=True)
    mode = Column(String(20), default="aligned")
    tree = Column(JSON, default=dict)
    score_mapping = Column(JSON, default=dict)
    reviewed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now, onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="outline")


class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    outline_id = Column(String(36), ForeignKey("outlines.id"), nullable=True)
    title = Column(String(500), nullable=False)
    content = Column(MEDIUMTEXT, nullable=True)
    mode = Column(String(10), default="A")
    status = Column(String(20), default="pending")
    word_count = Column(Integer, default=0)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now, onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="chapters")


class CheckReport(Base):
    __tablename__ = "check_reports"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    type = Column(String(30), nullable=False, index=True)
    results = Column(JSON, default=dict)
    risk_level = Column(String(20), default="low")
    summary = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="check_reports")


class SkillConfig(Base):
    __tablename__ = "skill_configs"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    name = Column(String(100), unique=True, nullable=False)
    category = Column(String(50), nullable=False)
    version = Column(String(20), default="1.0.0")
    config = Column(JSON, default=dict)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AgentConfig(Base):
    __tablename__ = "agent_configs"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    name = Column(String(100), unique=True, nullable=False)
    workflow_dsl = Column(JSON, default=dict)
    skills = Column(JSON, default=list)
    config = Column(JSON, default=dict)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    channel = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(20), default="pending")
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    name = Column(String(200), nullable=False)
    doc_count = Column(Integer, default=0)
    embedding_model = Column(String(100), default="text-embedding-v3")
    collection_name = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class MonitoringTask(Base):
    __tablename__ = "monitoring_tasks"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    keywords = Column(Text, nullable=False)
    exclude_keywords = Column(Text, default="")
    must_contain_keywords = Column(Text, default="")
    sites = Column(JSON, default=list)
    interval_minutes = Column(Integer, default=60)
    enabled = Column(Boolean, default=True)
    last_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class CrawlResult(Base):
    __tablename__ = "crawl_results"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    task_id = Column(String(36), ForeignKey("monitoring_tasks.id"), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    url = Column(String(1000), nullable=False)
    source = Column(String(500), default="")
    pub_date = Column(String(50), nullable=True)
    content = Column(MEDIUMTEXT, nullable=True)
    keyword_score = Column(Float, default=0.0)
    relevance_score = Column(Float, default=0.0)
    category = Column(String(50), default="general")
    is_hot = Column(Boolean, default=False)
    hot_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class RBACRole(Base):
    __tablename__ = "rbac_roles"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    is_system = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class RBACPermission(Base):
    __tablename__ = "rbac_permissions"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    code = Column(String(200), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    category = Column(String(100), nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class RBACUserRole(Base):
    __tablename__ = "rbac_user_roles"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    role_id = Column(String(36), ForeignKey("rbac_roles.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_rbac_user_role"),
    )


class RBACRolePermission(Base):
    __tablename__ = "rbac_role_permissions"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    role_id = Column(String(36), ForeignKey("rbac_roles.id"), nullable=False, index=True)
    permission_id = Column(String(36), ForeignKey("rbac_permissions.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_rbac_role_perm"),
    )


class NewsSourceRegistry(Base):
    """数据源注册表 (YAML -> DB 镜像)

    启动时由 services/news/source_registry.py 同步写入,
    管理员可在 UI 修改 enabled / weight 等字段。
    """
    __tablename__ = "news_source_registry"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    code = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    type = Column(String(20), default="rss", index=True)
    url = Column(String(1000), default="")
    industry_code = Column(String(20), default="12", index=True)
    weight = Column(Float, default=1.0)
    enabled = Column(Boolean, default=True, index=True)
    description = Column(Text, default="")
    extra_config = Column(JSON, default=dict)

    last_crawled_at = Column(DateTime, nullable=True)
    last_status = Column(String(20), default="")
    last_error = Column(Text, default="")

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now, onupdate=lambda: datetime.now(timezone.utc))


class HotspotItem(Base):
    """聚合后的商机/热点数据 (经过去重+评分+分类)"""
    __tablename__ = "hotspot_items"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    title = Column(String(500), nullable=False)
    url = Column(String(1000), nullable=False, index=True)
    source = Column(String(500), default="")
    sources = Column(JSON, default=list)
    pub_date = Column(String(50), nullable=True)
    content = Column(MEDIUMTEXT, nullable=True)
    source_code = Column(String(100), default="", index=True)
    industry_code = Column(String(20), default="12", index=True)
    region = Column(String(50), default="")
    amount = Column(Float, default=0.0)
    bid_deadline = Column(String(50), default="")
    owner_org = Column(String(200), default="")
    project_code = Column(String(100), default="", index=True)
    fingerprint = Column(String(255), default="", index=True)
    extra = Column(JSON, default=dict)

    score_total = Column(Float, default=0.0, index=True)
    score_urgency = Column(Float, default=0.0)
    score_match = Column(Float, default=0.0)
    score_amount = Column(Float, default=0.0)
    score_region = Column(Float, default=0.0)
    score_freshness = Column(Float, default=0.0)
    is_hot = Column(Boolean, default=False, index=True)

    is_converted = Column(Boolean, default=False, index=True)
    converted_project_id = Column(String(36), default="")

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now, onupdate=lambda: datetime.now(timezone.utc))


class LLMProviderConfig(Base):
    """LLM 供应商配置：一个供应商可有多条记录（多个 key 用于负载均衡 / 备用）。"""
    __tablename__ = "llm_provider_configs"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    provider_id = Column(String(64), nullable=False, index=True)
    display_name = Column(String(128), nullable=True)
    api_key = Column(String(512), nullable=False)
    api_base = Column(String(512), nullable=True)
    default_model = Column(String(128), nullable=True)
    is_default = Column(Boolean, default=False, nullable=False, index=True)
    enabled = Column(Boolean, default=True, nullable=False)
    note = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class ApiKey(Base):
    """API Key：桌面端 VIP 用户访问服务端数据/算力服务的凭证。

    取代传统 RBAC Bearer Token，简化桌面端-服务端认证。
    - 一个用户可拥有多个 ApiKey
    - type 区分：subscription (订阅制，数据服务) / credits (按量付费，算力服务)
    - 与 User 表弱关联：user_email 用于显示归属，不强约束外键
    """
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    key_hash = Column(String(128), nullable=False, unique=True, index=True)  # sha256(api_key_raw)
    key_prefix = Column(String(20), nullable=False)  # 显示用前缀 "bmp_xxxx..."
    user_email = Column(String(255), nullable=True, index=True)
    user_name = Column(String(100), nullable=True)
    tier = Column(String(20), default="free", nullable=False)  # free / pro / team
    type = Column(String(20), default="subscription", nullable=False)  # subscription / credits
    credits_remaining = Column(Integer, default=0, nullable=False)  # 仅 type=credits 时使用
    credits_total = Column(Integer, default=0, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    note = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class ApiKeyUsage(Base):
    """API Key 调用日志：用于计费、审计、限流"""
    __tablename__ = "api_key_usage"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    api_key_id = Column(String(36), ForeignKey("api_keys.id"), nullable=False, index=True)
    endpoint = Column(String(200), nullable=False)  # e.g. "/api/news/today-hot"
    method = Column(String(10), default="GET", nullable=False)
    status_code = Column(Integer, default=200, nullable=False)
    credits_cost = Column(Integer, default=0, nullable=False)  # 本次调用消耗的 credits
    user_agent = Column(String(256), nullable=True)
    client_ip = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
