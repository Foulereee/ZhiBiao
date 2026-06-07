-- ============================================================
-- BidMaster Pro 数据库初始化脚本
-- 适配 PostgreSQL 16+
-- ============================================================
--
-- 使用说明:
--   1. 创建数据库: CREATE DATABASE bidmaster;
--   2. 执行初始化: psql -U postgres -d bidmaster -f init_pg.sql
--
-- 注意：以下表结构由 SQLAlchemy 自动创建（Base.metadata.create_all）
-- 此脚本仅用于手动初始化或参考
-- ============================================================

-- 启用 UUID 扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 一、用户与权限体系
-- ============================================================

-- 1.1 用户表 - 系统用户，关联 RBAC 角色
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(36) PRIMARY KEY,                        -- 用户唯一标识，UUID 字符串格式
    email VARCHAR(255) UNIQUE NOT NULL,                -- 登录邮箱，唯一标识用户
    name VARCHAR(100) NOT NULL,                        -- 用户姓名，显示名称
    role VARCHAR(20) DEFAULT 'writer',                 -- 内置角色标识：admin(管理员)/project_manager(项目经理)/writer(撰写员)/reviewer(审核员)
    avatar VARCHAR(500),                               -- 用户头像 URL 地址
    password_hash VARCHAR(255),                        -- 密码哈希值，使用 bcrypt 算法加密
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,    -- 用户创建时间
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP     -- 用户信息最后更新时间
);
COMMENT ON TABLE users IS '系统用户表 - 存储平台注册用户信息';
COMMENT ON COLUMN users.id IS '用户唯一标识，UUID 字符串格式';
COMMENT ON COLUMN users.email IS '登录邮箱，唯一标识用户';
COMMENT ON COLUMN users.name IS '用户姓名，显示名称';
COMMENT ON COLUMN users.role IS '内置角色标识：admin/project_manager/writer/reviewer';
COMMENT ON COLUMN users.avatar IS '用户头像 URL 地址';
COMMENT ON COLUMN users.password_hash IS '密码哈希值，使用 bcrypt 算法加密';
COMMENT ON COLUMN users.created_at IS '用户创建时间';
COMMENT ON COLUMN users.updated_at IS '用户信息最后更新时间';

-- 1.2 RBAC 角色表 - 权限角色定义
CREATE TABLE IF NOT EXISTS rbac_roles (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,                 -- 角色标识（英文）：admin/project_manager/writer/reviewer
    display_name VARCHAR(200) NOT NULL,                -- 角色显示名称（中文）
    description TEXT DEFAULT '',                       -- 角色详细描述说明
    is_system BOOLEAN DEFAULT FALSE,                   -- 是否为系统内置角色，内置角色不可删除
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE rbac_roles IS 'RBAC角色表 - 定义系统角色及其权限范围';
COMMENT ON COLUMN rbac_roles.id IS '角色唯一标识，UUID 字符串格式';
COMMENT ON COLUMN rbac_roles.name IS '角色标识（英文）：admin/project_manager/writer/reviewer';
COMMENT ON COLUMN rbac_roles.display_name IS '角色显示名称（中文）';
COMMENT ON COLUMN rbac_roles.description IS '角色详细描述说明';
COMMENT ON COLUMN rbac_roles.is_system IS '是否为系统内置角色，内置角色不可删除';
COMMENT ON COLUMN rbac_roles.created_at IS '角色创建时间';

-- 1.3 RBAC 权限表 - 细粒度权限码
CREATE TABLE IF NOT EXISTS rbac_permissions (
    id VARCHAR(36) PRIMARY KEY,
    code VARCHAR(200) UNIQUE NOT NULL,                 -- 权限码（英文）：project.create / interpret.upload 等
    name VARCHAR(200) NOT NULL,                        -- 权限名称（中文）
    category VARCHAR(100) NOT NULL,                    -- 权限分类：project/interpret/generate/check/format/knowledge/news/settings
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE rbac_permissions IS 'RBAC权限表 - 定义系统细粒度权限';
COMMENT ON COLUMN rbac_permissions.id IS '权限唯一标识，UUID 字符串格式';
COMMENT ON COLUMN rbac_permissions.code IS '权限码（英文）：project.create / interpret.upload 等';
COMMENT ON COLUMN rbac_permissions.name IS '权限名称（中文）';
COMMENT ON COLUMN rbac_permissions.category IS '权限分类：project/interpret/generate/check/format/knowledge/news/settings';
COMMENT ON COLUMN rbac_permissions.description IS '权限功能描述';
COMMENT ON COLUMN rbac_permissions.created_at IS '权限创建时间';

-- 1.4 用户-角色关联表
CREATE TABLE IF NOT EXISTS rbac_user_roles (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id VARCHAR(36) NOT NULL REFERENCES rbac_roles(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, role_id)                           -- 同一用户不可重复绑定同一角色
);
COMMENT ON TABLE rbac_user_roles IS '用户角色关联表 - 记录用户与角色的多对多关系';
COMMENT ON COLUMN rbac_user_roles.id IS '关联记录唯一标识，UUID 字符串格式';
COMMENT ON COLUMN rbac_user_roles.user_id IS '关联的用户ID';
COMMENT ON COLUMN rbac_user_roles.role_id IS '关联的角色ID';
COMMENT ON COLUMN rbac_user_roles.created_at IS '关联创建时间';

-- 1.5 角色-权限关联表
CREATE TABLE IF NOT EXISTS rbac_role_permissions (
    id VARCHAR(36) PRIMARY KEY,
    role_id VARCHAR(36) NOT NULL REFERENCES rbac_roles(id) ON DELETE CASCADE,
    permission_id VARCHAR(36) NOT NULL REFERENCES rbac_permissions(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(role_id, permission_id)
);
COMMENT ON TABLE rbac_role_permissions IS '角色权限关联表 - 记录角色与权限的多对多关系';
COMMENT ON COLUMN rbac_role_permissions.id IS '关联记录唯一标识，UUID 字符串格式';
COMMENT ON COLUMN rbac_role_permissions.role_id IS '关联的角色ID';
COMMENT ON COLUMN rbac_role_permissions.permission_id IS '关联的权限ID';
COMMENT ON COLUMN rbac_role_permissions.created_at IS '关联创建时间';

-- ============================================================
-- 二、项目管理核心
-- ============================================================

-- 2.1 项目表 - 投标项目主表
CREATE TABLE IF NOT EXISTS projects (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,  -- 项目创建者用户ID
    name VARCHAR(200) NOT NULL,                        -- 项目名称
    status VARCHAR(50) DEFAULT 'created',              -- 项目状态：created(创建)/interpreting(解读中)/analyzing(分析中)/outlining(大纲)/generating(生成中)/checking(检查中)/formatting(格式化)/completed(完成)/archived(归档)
    tender_doc_id VARCHAR(36) REFERENCES documents(id),-- 关联的招标文件文档ID
    config JSON,                                       -- 项目配置信息（模板选择、参数设置等）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE projects IS '项目表 - 投标项目主表，存储项目基本信息';
COMMENT ON COLUMN projects.id IS '项目唯一标识，UUID 字符串格式';
COMMENT ON COLUMN projects.user_id IS '项目创建者用户ID';
COMMENT ON COLUMN projects.name IS '项目名称';
COMMENT ON COLUMN projects.status IS '项目状态：created/interpreting/analyzing/outlining/generating/checking/formatting/completed/archived';
COMMENT ON COLUMN projects.tender_doc_id IS '关联的招标文件文档ID';
COMMENT ON COLUMN projects.config IS '项目配置信息（模板选择、参数设置等）';
COMMENT ON COLUMN projects.created_at IS '项目创建时间';
COMMENT ON COLUMN projects.updated_at IS '项目最后更新时间';

-- 2.2 文档表 - 招标文件/投标文件/模板/参考资料
CREATE TABLE IF NOT EXISTS documents (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) REFERENCES projects(id) ON DELETE CASCADE,  -- 所属项目ID，可为空（模板文档）
    type VARCHAR(20) DEFAULT 'tender',                 -- 文档类型：tender(招标文件)/bid(投标文件)/template(模板)/reference(参考资料)
    file_path VARCHAR(500) NOT NULL,                   -- 文件存储路径
    original_name VARCHAR(255),                        -- 上传时的原始文件名
    file_size INTEGER,                                 -- 文件大小（字节）
    parsed_content TEXT,                               -- 解析后的文本内容
    doc_metadata JSON,                                 -- 文档元数据（页数、表格数、章节结构等）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE documents IS '文档表 - 存储各类文档信息';
COMMENT ON COLUMN documents.id IS '文档唯一标识，UUID 字符串格式';
COMMENT ON COLUMN documents.project_id IS '所属项目ID，可为空（模板文档）';
COMMENT ON COLUMN documents.type IS '文档类型：tender/bid/template/reference';
COMMENT ON COLUMN documents.file_path IS '文件存储路径';
COMMENT ON COLUMN documents.original_name IS '上传时的原始文件名';
COMMENT ON COLUMN documents.file_size IS '文件大小（字节）';
COMMENT ON COLUMN documents.parsed_content IS '解析后的文本内容';
COMMENT ON COLUMN documents.doc_metadata IS '文档元数据（页数、表格数、章节结构等）';
COMMENT ON COLUMN documents.created_at IS '文档上传时间';

-- ============================================================
-- 三、招标解读模块
-- ============================================================

-- 3.1 分析表 - 招标文件解读结果
CREATE TABLE IF NOT EXISTS analyses (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) UNIQUE NOT NULL REFERENCES projects(id) ON DELETE CASCADE, -- 一对一关联项目
    dimensions JSON,                                   -- 解读维度（资质要求、评分标准、关键条款、废标条款等）
    scoring_matrix JSON,                               -- 评分矩阵（评分项、分值、权重、是否强制等）
    risk_flags JSON,                                   -- 风险标记（高风险条款、陷阱条款、需重点关注项等）
    sections JSON,                                     -- 章节结构（检测到的文档章节列表）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE analyses IS '分析表 - 存储招标文件智能解读结果';
COMMENT ON COLUMN analyses.id IS '分析记录唯一标识，UUID 字符串格式';
COMMENT ON COLUMN analyses.project_id IS '关联项目ID，一对一关系';
COMMENT ON COLUMN analyses.dimensions IS '解读维度（资质要求、评分标准、关键条款、废标条款等）';
COMMENT ON COLUMN analyses.scoring_matrix IS '评分矩阵（评分项、分值、权重、是否强制等）';
COMMENT ON COLUMN analyses.risk_flags IS '风险标记（高风险条款、陷阱条款、需重点关注项等）';
COMMENT ON COLUMN analyses.sections IS '章节结构（检测到的文档章节列表）';
COMMENT ON COLUMN analyses.created_at IS '分析创建时间';
COMMENT ON COLUMN analyses.updated_at IS '分析更新时间';

-- ============================================================
-- 四、投标生成模块
-- ============================================================

-- 4.1 大纲表 - 投标文件大纲
CREATE TABLE IF NOT EXISTS outlines (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) UNIQUE NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    mode VARCHAR(20) DEFAULT 'aligned',                -- 大纲模式：aligned(对齐评分标准)/free(自由模式)
    tree JSON,                                         -- 大纲树结构（层级章节数据）
    score_mapping JSON,                                -- 评分项映射（章节与评分项的对应关系）
    reviewed BOOLEAN DEFAULT FALSE,                    -- 大纲是否已审核确认
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE outlines IS '大纲表 - 存储投标文件大纲结构';
COMMENT ON COLUMN outlines.id IS '大纲唯一标识，UUID 字符串格式';
COMMENT ON COLUMN outlines.project_id IS '关联项目ID，一对一关系';
COMMENT ON COLUMN outlines.mode IS '大纲模式：aligned(对齐评分标准)/free(自由模式)';
COMMENT ON COLUMN outlines.tree IS '大纲树结构（层级章节数据）';
COMMENT ON COLUMN outlines.score_mapping IS '评分项映射（章节与评分项的对应关系）';
COMMENT ON COLUMN outlines.reviewed IS '大纲是否已审核确认';
COMMENT ON COLUMN outlines.created_at IS '大纲创建时间';
COMMENT ON COLUMN outlines.updated_at IS '大纲更新时间';

-- 4.2 章节表 - 投标文件各章节内容
CREATE TABLE IF NOT EXISTS chapters (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    outline_id VARCHAR(36) REFERENCES outlines(id) ON DELETE CASCADE,  -- 所属大纲ID
    title VARCHAR(500) NOT NULL,                       -- 章节标题
    content TEXT,                                      -- 章节正文内容
    mode VARCHAR(10) DEFAULT 'A',                      -- 生成模式：A(自动生成)/M(手动编辑)
    status VARCHAR(20) DEFAULT 'pending',              -- 章节状态：pending(待生成)/generating(生成中)/generated(已生成)/reviewed(已审核)
    word_count INTEGER DEFAULT 0,                      -- 字数统计
    sort_order INTEGER DEFAULT 0,                      -- 排序序号
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE chapters IS '章节表 - 存储投标文件各章节内容';
COMMENT ON COLUMN chapters.id IS '章节唯一标识，UUID 字符串格式';
COMMENT ON COLUMN chapters.project_id IS '所属项目ID';
COMMENT ON COLUMN chapters.outline_id IS '所属大纲ID';
COMMENT ON COLUMN chapters.title IS '章节标题';
COMMENT ON COLUMN chapters.content IS '章节正文内容';
COMMENT ON COLUMN chapters.mode IS '生成模式：A(自动生成)/M(手动编辑)';
COMMENT ON COLUMN chapters.status IS '章节状态：pending/generating/generated/reviewed';
COMMENT ON COLUMN chapters.word_count IS '章节字数统计';
COMMENT ON COLUMN chapters.sort_order IS '章节排序序号';
COMMENT ON COLUMN chapters.created_at IS '章节创建时间';
COMMENT ON COLUMN chapters.updated_at IS '章节更新时间';

-- ============================================================
-- 五、投标检查模块
-- ============================================================

-- 5.1 检查报告表 - 各类检查结果
CREATE TABLE IF NOT EXISTS check_reports (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    type VARCHAR(30) NOT NULL,                         -- 检查类型：compliance(合规性)/disqualification(废标项)/duplicate(重复检查)/consistency(一致性)/format(格式)/qualification(资质)/deposit(保证金)/signature(签章)/pricing(报价)/mandatory(必填项)/validity(有效期)/selfcheck(自检)/fit_score(匹配度)/ai_text(AI文本)/cross_check(交叉检查)/sample_report(样例报告)/joint_bid(联合体)/ebid_submit(电子投标)/pricing_logic(报价逻辑)/doc_integrity(文档完整性)/risk_score(风险评分)
    results JSON,                                      -- 检查结果详情（各检查项的具体结果）
    risk_level VARCHAR(20) DEFAULT 'low',              -- 风险等级：low(低)/medium(中)/high(高)/critical(严重)
    summary JSON,                                      -- 检查摘要（总数、合规数、不合规数、建议等）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE check_reports IS '检查报告表 - 存储各类投标检查结果';
COMMENT ON COLUMN check_reports.id IS '检查报告唯一标识，UUID 字符串格式';
COMMENT ON COLUMN check_reports.project_id IS '关联项目ID';
COMMENT ON COLUMN check_reports.type IS '检查类型：compliance/disqualification/duplicate/consistency/format/qualification/deposit/signature/pricing/mandatory/validity/selfcheck/fit_score/ai_text/cross_check/sample_report/joint_bid/ebid_submit/pricing_logic/doc_integrity/risk_score';
COMMENT ON COLUMN check_reports.results IS '检查结果详情（各检查项的具体结果）';
COMMENT ON COLUMN check_reports.risk_level IS '风险等级：low/medium/high/critical';
COMMENT ON COLUMN check_reports.summary IS '检查摘要（总数、合规数、不合规数、建议等）';
COMMENT ON COLUMN check_reports.created_at IS '检查时间';

-- ============================================================
-- 六、系统配置
-- ============================================================

-- 6.1 Skill 配置表 - 技能引擎配置
CREATE TABLE IF NOT EXISTS skill_configs (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,                 -- 技能名称（唯一）
    category VARCHAR(50) NOT NULL,                     -- 技能分类：interpret(解读)/generate(生成)/check(检查)/output(输出)
    version VARCHAR(20) DEFAULT '1.0.0',               -- 技能版本号
    config JSON,                                       -- 技能配置参数
    enabled BOOLEAN DEFAULT TRUE,                      -- 技能是否启用
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE skill_configs IS '技能配置表 - 存储技能引擎的配置信息';
COMMENT ON COLUMN skill_configs.id IS '技能配置唯一标识，UUID 字符串格式';
COMMENT ON COLUMN skill_configs.name IS '技能名称（唯一）';
COMMENT ON COLUMN skill_configs.category IS '技能分类：interpret/generate/check/output';
COMMENT ON COLUMN skill_configs.version IS '技能版本号';
COMMENT ON COLUMN skill_configs.config IS '技能配置参数';
COMMENT ON COLUMN skill_configs.enabled IS '技能是否启用';
COMMENT ON COLUMN skill_configs.created_at IS '配置创建时间';

-- 6.2 Agent 配置表 - Agent 工作流配置
CREATE TABLE IF NOT EXISTS agent_configs (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,                 -- Agent名称：interpret/outline/content/check/format/final_check/export
    workflow_dsl JSON,                                 -- 工作流DSL定义
    skills JSON,                                       -- 绑定的技能列表
    config JSON,                                       -- Agent配置（model、temperature、max_tokens等）
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE agent_configs IS 'Agent配置表 - 存储AI Agent的工作流配置';
COMMENT ON COLUMN agent_configs.id IS 'Agent配置唯一标识，UUID 字符串格式';
COMMENT ON COLUMN agent_configs.name IS 'Agent名称：interpret/outline/content/check/format/final_check/export';
COMMENT ON COLUMN agent_configs.workflow_dsl IS '工作流DSL定义';
COMMENT ON COLUMN agent_configs.skills IS '绑定的技能列表';
COMMENT ON COLUMN agent_configs.config IS 'Agent配置（model、temperature、max_tokens等）';
COMMENT ON COLUMN agent_configs.enabled IS 'Agent是否启用';
COMMENT ON COLUMN agent_configs.created_at IS '配置创建时间';

-- 6.3 通知表 - 系统通知
CREATE TABLE IF NOT EXISTS notifications (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel VARCHAR(50) NOT NULL,                      -- 通知渠道：email(邮件)/webhook(Web钩子)/dingtalk(钉钉)/wechat(微信)
    content TEXT NOT NULL,                             -- 通知内容
    status VARCHAR(20) DEFAULT 'pending',              -- 通知状态：pending(待发送)/sent(已发送)/failed(发送失败)
    sent_at TIMESTAMP,                                 -- 发送时间
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE notifications IS '通知表 - 存储系统通知消息';
COMMENT ON COLUMN notifications.id IS '通知唯一标识，UUID 字符串格式';
COMMENT ON COLUMN notifications.user_id IS '接收通知的用户ID';
COMMENT ON COLUMN notifications.channel IS '通知渠道：email/webhook/dingtalk/wechat';
COMMENT ON COLUMN notifications.content IS '通知内容';
COMMENT ON COLUMN notifications.status IS '通知状态：pending/sent/failed';
COMMENT ON COLUMN notifications.sent_at IS '实际发送时间';
COMMENT ON COLUMN notifications.created_at IS '通知创建时间';

-- ============================================================
-- 七、知识库与资讯
-- ============================================================

-- 7.1 知识库表 - 企业知识库
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,                        -- 知识库名称
    doc_count INTEGER DEFAULT 0,                       -- 知识库中文档数量
    embedding_model VARCHAR(100) DEFAULT 'text-embedding-v3', -- 嵌入模型名称
    collection_name VARCHAR(200),                      -- ChromaDB 集合名称
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE knowledge_bases IS '知识库表 - 存储企业知识库信息';
COMMENT ON COLUMN knowledge_bases.id IS '知识库唯一标识，UUID 字符串格式';
COMMENT ON COLUMN knowledge_bases.name IS '知识库名称';
COMMENT ON COLUMN knowledge_bases.doc_count IS '知识库中文档数量';
COMMENT ON COLUMN knowledge_bases.embedding_model IS '使用的嵌入模型名称';
COMMENT ON COLUMN knowledge_bases.collection_name IS 'ChromaDB 集合名称';
COMMENT ON COLUMN knowledge_bases.created_at IS '知识库创建时间';

-- 7.2 监控任务表 - 招投标资讯监控
CREATE TABLE IF NOT EXISTS monitoring_tasks (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,                        -- 任务名称
    keywords TEXT NOT NULL,                            -- 监控关键词（逗号分隔）
    exclude_keywords TEXT DEFAULT '',                  -- 排除关键词
    must_contain_keywords TEXT DEFAULT '',             -- 必须包含关键词
    sites JSON,                                        -- 监控站点列表（URL列表）
    interval_minutes INTEGER DEFAULT 60,               -- 监控间隔（分钟）
    enabled BOOLEAN DEFAULT TRUE,                      -- 任务是否启用
    last_run_at TIMESTAMP,                             -- 上次执行时间
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE monitoring_tasks IS '监控任务表 - 存储招投标资讯监控任务配置';
COMMENT ON COLUMN monitoring_tasks.id IS '监控任务唯一标识，UUID 字符串格式';
COMMENT ON COLUMN monitoring_tasks.user_id IS '创建任务的用户ID';
COMMENT ON COLUMN monitoring_tasks.name IS '任务名称';
COMMENT ON COLUMN monitoring_tasks.keywords IS '监控关键词（逗号分隔）';
COMMENT ON COLUMN monitoring_tasks.exclude_keywords IS '排除关键词（逗号分隔）';
COMMENT ON COLUMN monitoring_tasks.must_contain_keywords IS '必须包含的关键词（逗号分隔）';
COMMENT ON COLUMN monitoring_tasks.sites IS '监控站点列表（URL列表）';
COMMENT ON COLUMN monitoring_tasks.interval_minutes IS '监控间隔（分钟）';
COMMENT ON COLUMN monitoring_tasks.enabled IS '任务是否启用';
COMMENT ON COLUMN monitoring_tasks.last_run_at IS '上次执行时间';
COMMENT ON COLUMN monitoring_tasks.created_at IS '任务创建时间';

-- 7.3 爬取结果表 - 资讯爬取结果
CREATE TABLE IF NOT EXISTS crawl_results (
    id VARCHAR(36) PRIMARY KEY,
    task_id VARCHAR(36) NOT NULL REFERENCES monitoring_tasks(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,                       -- 资讯标题
    url VARCHAR(1000) NOT NULL,                        -- 资讯链接地址
    source VARCHAR(500) DEFAULT '',                    -- 来源网站名称
    pub_date VARCHAR(50),                              -- 发布日期
    content TEXT,                                      -- 资讯正文内容
    keyword_score FLOAT DEFAULT 0.0,                   -- 关键词匹配分数（0-1）
    relevance_score FLOAT DEFAULT 0.0,                 -- 语义相关分数（0-1）
    category VARCHAR(50) DEFAULT 'general',            -- 资讯分类：general(普通)/hot(热点)/business(商业)
    is_hot BOOLEAN DEFAULT FALSE,                      -- 是否为热门资讯
    hot_score FLOAT DEFAULT 0.0,                       -- 热度分数（keyword*0.4 + relevance*0.6）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE crawl_results IS '爬取结果表 - 存储资讯爬取结果';
COMMENT ON COLUMN crawl_results.id IS '爬取结果唯一标识，UUID 字符串格式';
COMMENT ON COLUMN crawl_results.task_id IS '关联的监控任务ID';
COMMENT ON COLUMN crawl_results.title IS '资讯标题';
COMMENT ON COLUMN crawl_results.url IS '资讯链接地址';
COMMENT ON COLUMN crawl_results.source IS '来源网站名称';
COMMENT ON COLUMN crawl_results.pub_date IS '发布日期';
COMMENT ON COLUMN crawl_results.content IS '资讯正文内容';
COMMENT ON COLUMN crawl_results.keyword_score IS '关键词匹配分数（0-1）';
COMMENT ON COLUMN crawl_results.relevance_score IS '语义相关分数（0-1）';
COMMENT ON COLUMN crawl_results.category IS '资讯分类：general/hot/business';
COMMENT ON COLUMN crawl_results.is_hot IS '是否为热门资讯';
COMMENT ON COLUMN crawl_results.hot_score IS '热度分数（keyword*0.4 + relevance*0.6）';
COMMENT ON COLUMN crawl_results.created_at IS '爬取时间';

-- ============================================================
-- 八、索引
-- ============================================================

-- 项目表索引
CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);

-- 文档表索引
CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id);

-- 章节表索引
CREATE INDEX IF NOT EXISTS idx_chapters_project ON chapters(project_id);
CREATE INDEX IF NOT EXISTS idx_chapters_outline ON chapters(outline_id);

-- 检查报告索引
CREATE INDEX IF NOT EXISTS idx_check_reports_project ON check_reports(project_id);
CREATE INDEX IF NOT EXISTS idx_check_reports_type ON check_reports(type);

-- 通知索引
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);

-- RBAC 索引
CREATE INDEX IF NOT EXISTS idx_rbac_user_roles_user ON rbac_user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_rbac_user_roles_role ON rbac_user_roles(role_id);
CREATE INDEX IF NOT EXISTS idx_rbac_role_permissions_role ON rbac_role_permissions(role_id);
CREATE INDEX IF NOT EXISTS idx_rbac_role_permissions_perm ON rbac_role_permissions(permission_id);

-- 监控任务索引
CREATE INDEX IF NOT EXISTS idx_monitoring_tasks_user ON monitoring_tasks(user_id);

-- 爬取结果索引
CREATE INDEX IF NOT EXISTS idx_crawl_results_task ON crawl_results(task_id);
CREATE INDEX IF NOT EXISTS idx_crawl_results_category ON crawl_results(category);
CREATE INDEX IF NOT EXISTS idx_crawl_results_hot ON crawl_results(is_hot) WHERE is_hot = TRUE;

-- ============================================================
-- 九、初始数据 - 角色
-- ============================================================

INSERT INTO rbac_roles (id, name, display_name, description, is_system) VALUES
    ('00000000-0000-0000-0000-role00001', 'admin', '管理员', '系统管理员，拥有所有系统权限', TRUE),
    ('00000000-0000-0000-0000-role00002', 'project_manager', '项目经理', '管理项目和团队成员，可分配任务', FALSE),
    ('00000000-0000-0000-0000-role00003', 'writer', '撰写员', '编写和编辑投标文件内容', FALSE),
    ('00000000-0000-0000-0000-role00004', 'reviewer', '审核员', '审核投标文件内容和检查报告', FALSE)
ON CONFLICT (name) DO NOTHING;

-- ============================================================
-- 十、初始数据 - 权限 (与 rbac.py DEFAULT_PERMISSIONS 对齐)
-- ============================================================

INSERT INTO rbac_permissions (id, code, name, category, description) VALUES
    -- 项目管理权限
    ('00000000-0000-0000-0000-perm00001', 'project.create', '创建项目', 'project', '创建新的投标项目'),
    ('00000000-0000-0000-0000-perm00002', 'project.read', '查看项目', 'project', '查看项目详情信息'),
    ('00000000-0000-0000-0000-perm00003', 'project.update', '更新项目', 'project', '修改项目基本信息'),
    ('00000000-0000-0000-0000-perm00004', 'project.delete', '删除项目', 'project', '删除投标项目'),
    -- 招标解读权限
    ('00000000-0000-0000-0000-perm00005', 'interpret.upload', '上传招标文件', 'interpret', '上传招标文件进行智能解读'),
    ('00000000-0000-0000-0000-perm00006', 'interpret.parse', '解析招标文件', 'interpret', '执行智能解读分析'),
    ('00000000-0000-0000-0000-perm00007', 'interpret.view', '查看解读结果', 'interpret', '查看解读结果和评分矩阵'),
    -- 投标生成权限
    ('00000000-0000-0000-0000-perm00008', 'generate.outline', '生成大纲', 'generate', '根据解读结果生成投标大纲'),
    ('00000000-0000-0000-0000-perm00009', 'generate.content', '生成正文', 'generate', '根据大纲生成章节内容'),
    ('00000000-0000-0000-0000-perm00010', 'generate.review', '审核内容', 'generate', '审核生成的内容'),
    -- 投标检查权限
    ('00000000-0000-0000-0000-perm00011', 'check.run', '执行检查', 'check', '执行各项投标检查'),
    ('00000000-0000-0000-0000-perm00012', 'check.export', '导出检查结果', 'check', '导出检查报告'),
    ('00000000-0000-0000-0000-perm00013', 'check.report', '生成检查报告', 'check', '生成综合检查报告'),
    -- 文档格式化权限
    ('00000000-0000-0000-0000-perm00014', 'format.run', '执行格式化', 'format', '应用文档格式化'),
    ('00000000-0000-0000-0000-perm00015', 'format.template', '管理模板', 'format', '管理格式化模板'),
    ('00000000-0000-0000-0000-perm00016', 'format.config', '配置格式化', 'format', '配置格式化参数'),
    -- 资讯中心权限
    ('00000000-0000-0000-0000-perm00017', 'news.monitor', '监控资讯', 'news', '创建资讯监控任务'),
    ('00000000-0000-0000-0000-perm00018', 'news.view', '查看资讯', 'news', '查看招投标资讯'),
    ('00000000-0000-0000-0000-perm00019', 'news.manage', '管理资讯', 'news', '管理资讯监控任务'),
    -- 知识库权限
    ('00000000-0000-0000-0000-perm00020', 'knowledge.create', '创建知识库', 'knowledge', '创建企业知识库'),
    ('00000000-0000-0000-0000-perm00021', 'knowledge.upload', '上传知识文档', 'knowledge', '上传知识文档'),
    ('00000000-0000-0000-0000-perm00022', 'knowledge.search', '搜索知识库', 'knowledge', '搜索知识库内容'),
    ('00000000-0000-0000-0000-perm00023', 'knowledge.delete', '删除知识库', 'knowledge', '删除知识库'),
    -- 系统设置权限
    ('00000000-0000-0000-0000-perm00024', 'settings.view', '查看设置', 'settings', '查看系统设置'),
    ('00000000-0000-0000-0000-perm00025', 'settings.llm', '配置LLM', 'settings', '配置大语言模型参数'),
    ('00000000-0000-0000-0000-perm00026', 'settings.agent', '配置Agent', 'settings', '配置Agent工作流'),
    ('00000000-0000-0000-0000-perm00027', 'settings.rbac', '管理权限', 'settings', '管理角色和权限')
ON CONFLICT (code) DO NOTHING;

-- ============================================================
-- 十一、初始数据 - 角色权限分配 (与 rbac.py DEFAULT_ROLES 对齐)
-- ============================================================

-- 管理员: 拥有所有权限
INSERT INTO rbac_role_permissions (id, role_id, permission_id)
SELECT '00000000-0000-0000-rp-admin-' || p.code, r.id, p.id
FROM rbac_roles r, rbac_permissions p WHERE r.name = 'admin'
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- 项目经理: 除 settings.rbac 和 settings.agent 外所有权限
INSERT INTO rbac_role_permissions (id, role_id, permission_id)
SELECT '00000000-0000-0000-rp-mgr-' || p.code, r.id, p.id
FROM rbac_roles r, rbac_permissions p
WHERE r.name = 'project_manager' AND p.code NOT IN ('settings.rbac', 'settings.agent')
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- 撰写员: 项目读写 + 解读 + 生成 + 检查执行/导出 + 格式化执行 + 知识搜索
INSERT INTO rbac_role_permissions (id, role_id, permission_id)
SELECT '00000000-0000-0000-rp-writer-' || p.code, r.id, p.id
FROM rbac_roles r, rbac_permissions p
WHERE r.name = 'writer' AND p.code IN (
    'project.create', 'project.read', 'project.update',
    'interpret.upload', 'interpret.parse', 'interpret.view',
    'generate.outline', 'generate.content', 'generate.review',
    'check.run', 'check.export',
    'format.run',
    'knowledge.search'
)
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- 审核员: 项目查看 + 解读查看 + 内容审核 + 检查 + 格式化
INSERT INTO rbac_role_permissions (id, role_id, permission_id)
SELECT '00000000-0000-0000-rp-reviewer-' || p.code, r.id, p.id
FROM rbac_roles r, rbac_permissions p
WHERE r.name = 'reviewer' AND p.code IN (
    'project.read',
    'interpret.view',
    'generate.review',
    'check.run', 'check.export', 'check.report',
    'format.run'
)
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ============================================================
-- 十二、初始数据 - 默认管理员
-- ============================================================

INSERT INTO users (id, email, name, role, password_hash)
VALUES ('00000000-0000-0000-0000-user00001', 'admin@bidmaster.pro', '系统管理员', 'admin', '240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9')
ON CONFLICT (email) DO NOTHING;

-- 绑定管理员角色
INSERT INTO rbac_user_roles (id, user_id, role_id)
SELECT '00000000-0000-0000-ur-admin-role', u.id, r.id
FROM users u, rbac_roles r
WHERE u.email = 'admin@bidmaster.pro' AND r.name = 'admin'
ON CONFLICT (user_id, role_id) DO NOTHING;

-- ============================================================
-- 十三、初始数据 - 默认 Agent 配置 (与 llm_config.py DEFAULT_AGENTS 对齐)
-- ============================================================

INSERT INTO agent_configs (id, name, workflow_dsl, skills, config, enabled) VALUES
    ('00000000-0000-0000-agent-0001', 'interpret', '{}', '[]',
     '{"display_name": "招标解读Agent", "description": "解读招标文件，提取关键信息、评分标准、资质要求", "temperature": 0.3, "max_tokens": 8192}', TRUE),
    ('00000000-0000-0000-agent-0002', 'outline', '{}', '[]',
     '{"display_name": "大纲生成Agent", "description": "根据解读结果生成投标大纲，对齐评分项", "temperature": 0.5, "max_tokens": 4096}', TRUE),
    ('00000000-0000-0000-agent-0003', 'content', '{}', '[]',
     '{"display_name": "内容生成Agent", "description": "根据大纲逐章节生成标书内容", "temperature": 0.7, "max_tokens": 8192}', TRUE),
    ('00000000-0000-0000-agent-0004', 'check', '{}', '[]',
     '{"display_name": "质量检查Agent", "description": "对生成内容进行合规性、一致性、完整性检查", "temperature": 0.2, "max_tokens": 4096}', TRUE),
    ('00000000-0000-0000-agent-0005', 'format', '{}', '[]',
     '{"display_name": "格式排版Agent", "description": "对文档进行格式排版和美化", "temperature": 0.1, "max_tokens": 2048}', TRUE),
    ('00000000-0000-0000-agent-0006', 'final_check', '{}', '[]',
     '{"display_name": "终审Agent", "description": "最终全面检查，确保无遗漏", "temperature": 0.1, "max_tokens": 4096}', TRUE),
    ('00000000-0000-0000-agent-0007', 'export', '{}', '[]',
     '{"display_name": "导出Agent", "description": "导出最终投标文件", "temperature": 0.0, "max_tokens": 2048}', TRUE)
ON CONFLICT (name) DO NOTHING;

-- 完成
SELECT 'BidMaster Pro database initialized successfully!' AS message;
