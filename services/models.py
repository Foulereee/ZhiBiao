from __future__ import annotations

import enum
import sqlalchemy as sql
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey, Enum, JSON, UniqueConstraint
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import DeclarativeBase, relationship
from datetime import datetime, timezone
import uuid

# 内容字段类型：MySQL 下使用 MEDIUMTEXT(16MB)；PostgreSQL 等其他方言回退为 TEXT
# （MEDIUMTEXT 无法在 PostgreSQL 下编译，会抛 CompileError）
MEDIUM_TEXT = MEDIUMTEXT().with_variant(Text(), "postgresql", "sqlite")


def utcnow() -> datetime:
    """返回无时区的 UTC 时间（naive）。

    DateTime 列未声明 timezone=True，映射到 PostgreSQL 的 timestamp without time zone；
    asyncpg 会拒绝带时区的 aware datetime，因此统一返回 naive 的 UTC 时间。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso_utc(dt: datetime | None) -> str | None:
    """把库里存的 naive UTC 时间序列化成"带时区"的 ISO 串。

    为什么必须这么写：列存的是 naive UTC，直接 dt.isoformat() 得到
    "2026-09-19T13:06:33"（没有 Z、没有偏移）。浏览器 new Date() 对"没有时区的
    ISO 串"按**当地时间**解析，于是同一份报告在界面上显示 13:06，实际本地时间
    是 21:06 —— 整体偏 8 小时（用户反馈的"检查报告时间不对"正是这个）。

    补上 +00:00 之后，前端 toLocaleString() 会换算成浏览器所在时区，各时区都对。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def iso_local(dt: datetime | None) -> str | None:
    """naive UTC -> 服务器本地时间的 ISO 串（带本地偏移）。

    用于 docx 导出这类"给人看的字符串"场景。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().isoformat()


def local_str(dt: datetime | None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """naive UTC -> 本地时间字符串，例如 2026-09-19 21:06:33。"""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime(fmt)


def iso_now_local() -> str:
    """当前"本地时间"的 ISO 串（带本地偏移），用于 datetime.now() 这类值。

    和 iso_utc 相反：这类值本来就是本地时间，若不加偏移，浏览器会按本地解析——
    在中国看着正常，换个时区就错。
    """
    return datetime.now().astimezone().isoformat()


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
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    projects = relationship("Project", back_populates="user")


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    status = Column(String(50), default=ProjectStatus.CREATED.value, index=True)
    tender_doc_id = Column(String(36), ForeignKey("documents.id"), nullable=True)
    config = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

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
    parsed_content = Column(MEDIUM_TEXT, nullable=True)
    doc_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utcnow)

    project = relationship("Project", back_populates="documents", foreign_keys=[project_id])


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, unique=True, index=True)
    dimensions = Column(JSON, default=dict)
    scoring_matrix = Column(JSON, default=dict)
    risk_flags = Column(JSON, default=dict)
    sections = Column(JSON, default=list)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    project = relationship("Project", back_populates="analysis")


class Outline(Base):
    __tablename__ = "outlines"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, unique=True, index=True)
    mode = Column(String(20), default="aligned")
    tree = Column(JSON, default=dict)
    score_mapping = Column(JSON, default=dict)
    reviewed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    project = relationship("Project", back_populates="outline")


class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    outline_id = Column(String(36), ForeignKey("outlines.id"), nullable=True)
    title = Column(String(500), nullable=False)
    content = Column(MEDIUM_TEXT, nullable=True)
    mode = Column(String(10), default="A")
    status = Column(String(20), default="pending")
    word_count = Column(Integer, default=0)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    project = relationship("Project", back_populates="chapters")


class CheckReport(Base):
    __tablename__ = "check_reports"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    type = Column(String(30), nullable=False, index=True)
    results = Column(JSON, default=dict)
    risk_level = Column(String(20), default="low")
    summary = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utcnow)

    project = relationship("Project", back_populates="check_reports")


class SkillConfig(Base):
    __tablename__ = "skill_configs"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    name = Column(String(100), unique=True, nullable=False)
    category = Column(String(50), nullable=False)
    version = Column(String(20), default="1.0.0")
    config = Column(JSON, default=dict)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)


class AgentConfig(Base):
    __tablename__ = "agent_configs"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    name = Column(String(100), unique=True, nullable=False)
    workflow_dsl = Column(JSON, default=dict)
    skills = Column(JSON, default=list)
    config = Column(JSON, default=dict)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    channel = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(20), default="pending")
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    name = Column(String(200), nullable=False)
    doc_count = Column(Integer, default=0)
    embedding_model = Column(String(100), default="text-embedding-v3")
    collection_name = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=utcnow)


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
    created_at = Column(DateTime, default=utcnow)


class CrawlResult(Base):
    __tablename__ = "crawl_results"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    task_id = Column(String(36), ForeignKey("monitoring_tasks.id"), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    url = Column(String(1000), nullable=False)
    source = Column(String(500), default="")
    pub_date = Column(String(50), nullable=True)
    content = Column(MEDIUM_TEXT, nullable=True)
    keyword_score = Column(Float, default=0.0)
    relevance_score = Column(Float, default=0.0)
    category = Column(String(50), default="general")
    is_hot = Column(Boolean, default=False)
    hot_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utcnow)


class RBACRole(Base):
    __tablename__ = "rbac_roles"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    is_system = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)


class RBACPermission(Base):
    __tablename__ = "rbac_permissions"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    code = Column(String(200), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    category = Column(String(100), nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)


class RBACUserRole(Base):
    __tablename__ = "rbac_user_roles"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    role_id = Column(String(36), ForeignKey("rbac_roles.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_rbac_user_role"),
    )


class RBACRolePermission(Base):
    __tablename__ = "rbac_role_permissions"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    role_id = Column(String(36), ForeignKey("rbac_roles.id"), nullable=False, index=True)
    permission_id = Column(String(36), ForeignKey("rbac_permissions.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow)

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

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class HotspotItem(Base):
    """聚合后的商机/热点数据 (经过去重+评分+分类)"""
    __tablename__ = "hotspot_items"

    id = Column(String(36), primary_key=True, default=_uuid_default)
    title = Column(String(500), nullable=False)
    url = Column(String(1000), nullable=False, index=True)
    source = Column(String(500), default="")
    sources = Column(JSON, default=list)
    pub_date = Column(String(50), nullable=True)
    content = Column(MEDIUM_TEXT, nullable=True)
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

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


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
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


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
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


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
    created_at = Column(DateTime, default=utcnow, index=True)
