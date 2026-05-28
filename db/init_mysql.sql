-- ============================================================
-- BidMaster Pro 数据库初始化脚本
-- 适配 MySQL 8.0+
-- ============================================================
--
-- 使用说明:
--   1. 创建数据库:
--      CREATE DATABASE IF NOT EXISTS bidmaster
--        CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
--   2. 执行初始化:
--      USE bidmaster;
--      SOURCE init_mysql.sql;
--
-- 注意：以下表结构由 SQLAlchemy 自动创建（Base.metadata.create_all）
-- 此脚本仅用于手动初始化或参考
-- ============================================================

-- ============================================================
-- 一、用户与权限体系
-- ============================================================

-- 1.1 用户表 - 系统用户，关联 RBAC 角色
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(36) PRIMARY KEY COMMENT '用户唯一标识，UUID 字符串格式',
    email VARCHAR(255) UNIQUE NOT NULL COMMENT '登录邮箱，唯一标识用户',
    name VARCHAR(100) NOT NULL COMMENT '用户姓名，显示名称',
    role VARCHAR(20) DEFAULT 'writer' COMMENT '内置角色标识：admin(管理员)/project_manager(项目经理)/writer(撰写员)/reviewer(审核员)',
    avatar VARCHAR(500) COMMENT '用户头像 URL 地址',
    password_hash VARCHAR(255) COMMENT '密码哈希值，使用 bcrypt 算法加密',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '用户创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '用户信息最后更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统用户表 - 存储平台注册用户信息';

-- 1.2 RBAC 角色表 - 权限角色定义
CREATE TABLE IF NOT EXISTS rbac_roles (
    id VARCHAR(36) PRIMARY KEY COMMENT '角色唯一标识，UUID 字符串格式',
    name VARCHAR(100) UNIQUE NOT NULL COMMENT '角色标识（英文）：admin/project_manager/writer/reviewer',
    display_name VARCHAR(200) NOT NULL COMMENT '角色显示名称（中文）',
    description TEXT COMMENT '角色详细描述说明',
    is_system BOOLEAN DEFAULT FALSE COMMENT '是否为系统内置角色，内置角色不可删除',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '角色创建时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='RBAC角色表 - 定义系统角色及其权限范围';

-- 1.3 RBAC 权限表 - 细粒度权限码
CREATE TABLE IF NOT EXISTS rbac_permissions (
    id VARCHAR(36) PRIMARY KEY COMMENT '权限唯一标识，UUID 字符串格式',
    code VARCHAR(200) UNIQUE NOT NULL COMMENT '权限码（英文）：project.create / interpret.upload 等',
    name VARCHAR(200) NOT NULL COMMENT '权限名称（中文）',
    category VARCHAR(100) NOT NULL COMMENT '权限分类：project/interpret/generate/check/format/knowledge/news/settings',
    description TEXT COMMENT '权限功能描述',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '权限创建时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='RBAC权限表 - 定义系统细粒度权限';

-- 1.4 用户-角色关联表
CREATE TABLE IF NOT EXISTS rbac_user_roles (
    id VARCHAR(36) PRIMARY KEY COMMENT '关联记录唯一标识，UUID 字符串格式',
    user_id VARCHAR(36) NOT NULL COMMENT '关联的用户ID，外键关联 users.id，级联删除',
    role_id VARCHAR(36) NOT NULL COMMENT '关联的角色ID，外键关联 rbac_roles.id，级联删除',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '关联创建时间',
    UNIQUE KEY uk_user_role (user_id, role_id) COMMENT '同一用户不可重复绑定同一角色',
    INDEX idx_rbac_user_roles_user (user_id) COMMENT '用户ID索引，加速用户角色查询',
    INDEX idx_rbac_user_roles_role (role_id) COMMENT '角色ID索引，加速角色用户查询',
    CONSTRAINT fk_rbac_user_roles_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_rbac_user_roles_role FOREIGN KEY (role_id) REFERENCES rbac_roles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户角色关联表 - 记录用户与角色的多对多关系';

-- 1.5 角色-权限关联表
CREATE TABLE IF NOT EXISTS rbac_role_permissions (
    id VARCHAR(36) PRIMARY KEY COMMENT '关联记录唯一标识，UUID 字符串格式',
    role_id VARCHAR(36) NOT NULL COMMENT '关联的角色ID，外键关联 rbac_roles.id，级联删除',
    permission_id VARCHAR(36) NOT NULL COMMENT '关联的权限ID，外键关联 rbac_permissions.id，级联删除',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '关联创建时间',
    UNIQUE KEY uk_role_permission (role_id, permission_id) COMMENT '同一角色不可重复绑定同一权限',
    INDEX idx_rbac_role_permissions_role (role_id) COMMENT '角色ID索引，加速角色权限查询',
    INDEX idx_rbac_role_permissions_perm (permission_id) COMMENT '权限ID索引，加速权限角色查询',
    CONSTRAINT fk_rbac_role_permissions_role FOREIGN KEY (role_id) REFERENCES rbac_roles(id) ON DELETE CASCADE,
    CONSTRAINT fk_rbac_role_permissions_perm FOREIGN KEY (permission_id) REFERENCES rbac_permissions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='角色权限关联表 - 记录角色与权限的多对多关系';

-- ============================================================
-- 二、项目管理核心
-- ============================================================

-- 2.1 项目表 - 投标项目主表
CREATE TABLE IF NOT EXISTS projects (
    id VARCHAR(36) PRIMARY KEY COMMENT '项目唯一标识，UUID 字符串格式',
    user_id VARCHAR(36) NOT NULL COMMENT '项目创建者用户ID，外键关联 users.id，级联删除',
    name VARCHAR(200) NOT NULL COMMENT '项目名称',
    status VARCHAR(50) DEFAULT 'created' COMMENT '项目状态：created(创建)/interpreting(解读中)/analyzing(分析中)/outlining(大纲)/generating(生成中)/checking(检查中)/formatting(格式化)/completed(完成)/archived(归档)',
    tender_doc_id VARCHAR(36) COMMENT '关联的招标文件文档ID，外键关联 documents.id',
    config JSON COMMENT '项目配置信息（模板选择、参数设置等）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '项目创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '项目最后更新时间',
    INDEX idx_projects_user (user_id) COMMENT '用户ID索引，加速用户项目查询',
    INDEX idx_projects_status (status) COMMENT '状态索引，加速状态筛选',
    CONSTRAINT fk_projects_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='项目表 - 投标项目主表，存储项目基本信息';

-- 2.2 文档表 - 招标文件/投标文件/模板/参考资料
CREATE TABLE IF NOT EXISTS documents (
    id VARCHAR(36) PRIMARY KEY COMMENT '文档唯一标识，UUID 字符串格式',
    project_id VARCHAR(36) COMMENT '所属项目ID，外键关联 projects.id，级联删除；可为空（模板文档）',
    type VARCHAR(20) DEFAULT 'tender' COMMENT '文档类型：tender(招标文件)/bid(投标文件)/template(模板)/reference(参考资料)',
    file_path VARCHAR(500) NOT NULL COMMENT '文件存储路径',
    original_name VARCHAR(255) COMMENT '上传时的原始文件名',
    file_size INT COMMENT '文件大小（字节）',
    parsed_content TEXT COMMENT '文档解析后的文本内容',
    doc_metadata JSON COMMENT '文档元数据（页数、表格数、章节结构等）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '文档上传时间',
    INDEX idx_documents_project (project_id) COMMENT '项目ID索引，加速项目文档查询',
    CONSTRAINT fk_documents_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文档表 - 存储各类文档信息';

-- ============================================================
-- 三、招标解读模块
-- ============================================================

-- 3.1 分析表 - 招标文件解读结果
CREATE TABLE IF NOT EXISTS analyses (
    id VARCHAR(36) PRIMARY KEY COMMENT '分析记录唯一标识，UUID 字符串格式',
    project_id VARCHAR(36) UNIQUE NOT NULL COMMENT '关联项目ID，一对一关系，外键关联 projects.id，级联删除',
    dimensions JSON COMMENT '解读维度（资质要求、评分标准、关键条款、废标条款等）',
    scoring_matrix JSON COMMENT '评分矩阵（评分项、分值、权重、是否强制等）',
    risk_flags JSON COMMENT '风险标记（高风险条款、陷阱条款、需重点关注项等）',
    sections JSON COMMENT '章节结构（检测到的文档章节列表）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '分析创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '分析更新时间',
    INDEX idx_analyses_project (project_id) COMMENT '项目ID索引',
    CONSTRAINT fk_analyses_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分析表 - 存储招标文件智能解读结果';

-- ============================================================
-- 四、投标生成模块
-- ============================================================

-- 4.1 大纲表 - 投标文件大纲
CREATE TABLE IF NOT EXISTS outlines (
    id VARCHAR(36) PRIMARY KEY COMMENT '大纲唯一标识，UUID 字符串格式',
    project_id VARCHAR(36) UNIQUE NOT NULL COMMENT '关联项目ID，一对一关系，外键关联 projects.id，级联删除',
    mode VARCHAR(20) DEFAULT 'aligned' COMMENT '大纲模式：aligned(对齐评分标准)/free(自由模式)',
    tree JSON COMMENT '大纲树结构（层级章节数据）',
    score_mapping JSON COMMENT '评分项映射（章节与评分项的对应关系）',
    reviewed BOOLEAN DEFAULT FALSE COMMENT '大纲是否已审核确认',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '大纲创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '大纲更新时间',
    INDEX idx_outlines_project (project_id) COMMENT '项目ID索引',
    CONSTRAINT fk_outlines_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='大纲表 - 存储投标文件大纲结构';

-- 4.2 章节表 - 投标文件各章节内容
CREATE TABLE IF NOT EXISTS chapters (
    id VARCHAR(36) PRIMARY KEY COMMENT '章节唯一标识，UUID 字符串格式',
    project_id VARCHAR(36) NOT NULL COMMENT '所属项目ID，外键关联 projects.id，级联删除',
    outline_id VARCHAR(36) COMMENT '所属大纲ID，外键关联 outlines.id，级联删除',
    title VARCHAR(500) NOT NULL COMMENT '章节标题',
    content TEXT COMMENT '章节正文内容',
    mode VARCHAR(10) DEFAULT 'A' COMMENT '生成模式：A(自动生成)/M(手动编辑)',
    status VARCHAR(20) DEFAULT 'pending' COMMENT '章节状态：pending(待生成)/generating(生成中)/generated(已生成)/reviewed(已审核)',
    word_count INT DEFAULT 0 COMMENT '章节字数统计',
    sort_order INT DEFAULT 0 COMMENT '章节排序序号',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '章节创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '章节更新时间',
    INDEX idx_chapters_project (project_id) COMMENT '项目ID索引',
    INDEX idx_chapters_outline (outline_id) COMMENT '大纲ID索引',
    CONSTRAINT fk_chapters_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_chapters_outline FOREIGN KEY (outline_id) REFERENCES outlines(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='章节表 - 存储投标文件各章节内容';

-- ============================================================
-- 五、投标检查模块
-- ============================================================

-- 5.1 检查报告表 - 各类检查结果
CREATE TABLE IF NOT EXISTS check_reports (
    id VARCHAR(36) PRIMARY KEY COMMENT '检查报告唯一标识，UUID 字符串格式',
    project_id VARCHAR(36) NOT NULL COMMENT '关联项目ID，外键关联 projects.id，级联删除',
    type VARCHAR(30) NOT NULL COMMENT '检查类型：compliance(合规性)/disqualification(废标项)/duplicate(重复检查)/consistency(一致性)/format(格式)/qualification(资质)/deposit(保证金)/signature(签章)/pricing(报价)/mandatory(必填项)/validity(有效期)/selfcheck(自检)/fit_score(匹配度)/ai_text(AI文本)/cross_check(交叉检查)/sample_report(样例报告)/joint_bid(联合体)/ebid_submit(电子投标)/pricing_logic(报价逻辑)/doc_integrity(文档完整性)/risk_score(风险评分)',
    results JSON COMMENT '检查结果详情（各检查项的具体结果）',
    risk_level VARCHAR(20) DEFAULT 'low' COMMENT '风险等级：low(低)/medium(中)/high(高)/critical(严重)',
    summary JSON COMMENT '检查摘要（总数、合规数、不合规数、建议等）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '检查时间',
    INDEX idx_check_reports_project (project_id) COMMENT '项目ID索引',
    INDEX idx_check_reports_type (type) COMMENT '检查类型索引',
    CONSTRAINT fk_check_reports_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='检查报告表 - 存储各类投标检查结果';

-- ============================================================
-- 六、系统配置
-- ============================================================

-- 6.1 Skill 配置表 - 技能引擎配置
CREATE TABLE IF NOT EXISTS skill_configs (
    id VARCHAR(36) PRIMARY KEY COMMENT '技能配置唯一标识，UUID 字符串格式',
    name VARCHAR(100) UNIQUE NOT NULL COMMENT '技能名称（唯一）',
    category VARCHAR(50) NOT NULL COMMENT '技能分类：interpret(解读)/generate(生成)/check(检查)/output(输出)',
    version VARCHAR(20) DEFAULT '1.0.0' COMMENT '技能版本号',
    config JSON COMMENT '技能配置参数',
    enabled BOOLEAN DEFAULT TRUE COMMENT '技能是否启用',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '配置创建时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='技能配置表 - 存储技能引擎的配置信息';

-- 6.2 Agent 配置表 - Agent 工作流配置
CREATE TABLE IF NOT EXISTS agent_configs (
    id VARCHAR(36) PRIMARY KEY COMMENT 'Agent配置唯一标识，UUID 字符串格式',
    name VARCHAR(100) UNIQUE NOT NULL COMMENT 'Agent名称：interpret/outline/content/check/format/final_check/export',
    workflow_dsl JSON COMMENT '工作流DSL定义',
    skills JSON COMMENT '绑定的技能列表',
    config JSON COMMENT 'Agent配置（model、temperature、max_tokens等）',
    enabled BOOLEAN DEFAULT TRUE COMMENT 'Agent是否启用',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '配置创建时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Agent配置表 - 存储AI Agent的工作流配置';

-- 6.3 通知表 - 系统通知
CREATE TABLE IF NOT EXISTS notifications (
    id VARCHAR(36) PRIMARY KEY COMMENT '通知唯一标识，UUID 字符串格式',
    user_id VARCHAR(36) NOT NULL COMMENT '接收通知的用户ID，外键关联 users.id，级联删除',
    channel VARCHAR(50) NOT NULL COMMENT '通知渠道：email(邮件)/webhook(Web钩子)/dingtalk(钉钉)/wechat(微信)',
    content TEXT NOT NULL COMMENT '通知内容',
    status VARCHAR(20) DEFAULT 'pending' COMMENT '通知状态：pending(待发送)/sent(已发送)/failed(发送失败)',
    sent_at TIMESTAMP NULL COMMENT '实际发送时间',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '通知创建时间',
    INDEX idx_notifications_user (user_id) COMMENT '用户ID索引',
    CONSTRAINT fk_notifications_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='通知表 - 存储系统通知消息';

-- ============================================================
-- 七、知识库与资讯
-- ============================================================

-- 7.1 知识库表 - 企业知识库
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id VARCHAR(36) PRIMARY KEY COMMENT '知识库唯一标识，UUID 字符串格式',
    name VARCHAR(200) NOT NULL COMMENT '知识库名称',
    doc_count INT DEFAULT 0 COMMENT '知识库中文档数量',
    embedding_model VARCHAR(100) DEFAULT 'text-embedding-v3' COMMENT '使用的嵌入模型名称',
    collection_name VARCHAR(200) COMMENT 'ChromaDB 集合名称',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '知识库创建时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库表 - 存储企业知识库信息';

-- 7.2 监控任务表 - 招投标资讯监控
CREATE TABLE IF NOT EXISTS monitoring_tasks (
    id VARCHAR(36) PRIMARY KEY COMMENT '监控任务唯一标识，UUID 字符串格式',
    user_id VARCHAR(36) NOT NULL COMMENT '创建任务的用户ID，外键关联 users.id，级联删除',
    name VARCHAR(200) NOT NULL COMMENT '任务名称',
    keywords TEXT NOT NULL COMMENT '监控关键词（逗号分隔）',
    exclude_keywords TEXT COMMENT '排除关键词（逗号分隔）',
    must_contain_keywords TEXT COMMENT '必须包含的关键词（逗号分隔）',
    sites JSON COMMENT '监控站点列表（URL列表）',
    interval_minutes INT DEFAULT 60 COMMENT '监控间隔（分钟）',
    enabled BOOLEAN DEFAULT TRUE COMMENT '任务是否启用',
    last_run_at TIMESTAMP NULL COMMENT '上次执行时间',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '任务创建时间',
    INDEX idx_monitoring_tasks_user (user_id) COMMENT '用户ID索引',
    CONSTRAINT fk_monitoring_tasks_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='监控任务表 - 存储招投标资讯监控任务配置';

-- 7.3 爬取结果表 - 资讯爬取结果
CREATE TABLE IF NOT EXISTS crawl_results (
    id VARCHAR(36) PRIMARY KEY COMMENT '爬取结果唯一标识，UUID 字符串格式',
    task_id VARCHAR(36) NOT NULL COMMENT '关联的监控任务ID，外键关联 monitoring_tasks.id，级联删除',
    title VARCHAR(500) NOT NULL COMMENT '资讯标题',
    url VARCHAR(1000) NOT NULL COMMENT '资讯链接地址',
    source VARCHAR(500) DEFAULT '' COMMENT '来源网站名称',
    pub_date VARCHAR(50) COMMENT '发布日期',
    content TEXT COMMENT '资讯正文内容',
    keyword_score FLOAT DEFAULT 0.0 COMMENT '关键词匹配分数（0-1）',
    relevance_score FLOAT DEFAULT 0.0 COMMENT '语义相关分数（0-1）',
    category VARCHAR(50) DEFAULT 'general' COMMENT '资讯分类：general(普通)/hot(热点)/business(商业)',
    is_hot BOOLEAN DEFAULT FALSE COMMENT '是否为热门资讯',
    hot_score FLOAT DEFAULT 0.0 COMMENT '热度分数（keyword*0.4 + relevance*0.6）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '爬取时间',
    INDEX idx_crawl_results_task (task_id) COMMENT '任务ID索引',
    INDEX idx_crawl_results_category (category) COMMENT '分类索引',
    CONSTRAINT fk_crawl_results_task FOREIGN KEY (task_id) REFERENCES monitoring_tasks(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='爬取结果表 - 存储资讯爬取结果';

-- ============================================================
-- 八、初始数据 - 角色
-- ============================================================

INSERT IGNORE INTO rbac_roles (id, name, display_name, description, is_system) VALUES
    ('00000000-0000-0000-0000-role00001', 'admin', '管理员', '系统管理员，拥有所有系统权限', TRUE),
    ('00000000-0000-0000-0000-role00002', 'project_manager', '项目经理', '管理项目和团队成员，可分配任务', FALSE),
    ('00000000-0000-0000-0000-role00003', 'writer', '撰写员', '编写和编辑投标文件内容', FALSE),
    ('00000000-0000-0000-0000-role00004', 'reviewer', '审核员', '审核投标文件内容和检查报告', FALSE);

-- ============================================================
-- 九、初始数据 - 权限 (与 rbac.py DEFAULT_PERMISSIONS 对齐)
-- ============================================================

INSERT IGNORE INTO rbac_permissions (id, code, name, category, description) VALUES
    ('00000000-0000-0000-0000-perm00001', 'project.create', '创建项目', 'project', '创建新的投标项目'),
    ('00000000-0000-0000-0000-perm00002', 'project.read', '查看项目', 'project', '查看项目详情信息'),
    ('00000000-0000-0000-0000-perm00003', 'project.update', '更新项目', 'project', '修改项目基本信息'),
    ('00000000-0000-0000-0000-perm00004', 'project.delete', '删除项目', 'project', '删除投标项目'),
    ('00000000-0000-0000-0000-perm00005', 'interpret.upload', '上传招标文件', 'interpret', '上传招标文件进行智能解读'),
    ('00000000-0000-0000-0000-perm00006', 'interpret.parse', '解析招标文件', 'interpret', '执行智能解读分析'),
    ('00000000-0000-0000-0000-perm00007', 'interpret.view', '查看解读结果', 'interpret', '查看解读结果和评分矩阵'),
    ('00000000-0000-0000-0000-perm00008', 'generate.outline', '生成大纲', 'generate', '根据解读结果生成投标大纲'),
    ('00000000-0000-0000-0000-perm00009', 'generate.content', '生成正文', 'generate', '根据大纲生成章节内容'),
    ('00000000-0000-0000-0000-perm00010', 'generate.review', '审核内容', 'generate', '审核生成的内容'),
    ('00000000-0000-0000-0000-perm00011', 'check.run', '执行检查', 'check', '执行各项投标检查'),
    ('00000000-0000-0000-0000-perm00012', 'check.export', '导出检查结果', 'check', '导出检查报告'),
    ('00000000-0000-0000-0000-perm00013', 'check.report', '生成检查报告', 'check', '生成综合检查报告'),
    ('00000000-0000-0000-0000-perm00014', 'format.run', '执行格式化', 'format', '应用文档格式化'),
    ('00000000-0000-0000-0000-perm00015', 'format.template', '管理模板', 'format', '管理格式化模板'),
    ('00000000-0000-0000-0000-perm00016', 'format.config', '配置格式化', 'format', '配置格式化参数'),
    ('00000000-0000-0000-0000-perm00017', 'news.monitor', '监控资讯', 'news', '创建资讯监控任务'),
    ('00000000-0000-0000-0000-perm00018', 'news.view', '查看资讯', 'news', '查看招投标资讯'),
    ('00000000-0000-0000-0000-perm00019', 'news.manage', '管理资讯', 'news', '管理资讯监控任务'),
    ('00000000-0000-0000-0000-perm00020', 'knowledge.create', '创建知识库', 'knowledge', '创建企业知识库'),
    ('00000000-0000-0000-0000-perm00021', 'knowledge.upload', '上传知识文档', 'knowledge', '上传知识文档'),
    ('00000000-0000-0000-0000-perm00022', 'knowledge.search', '搜索知识库', 'knowledge', '搜索知识库内容'),
    ('00000000-0000-0000-0000-perm00023', 'knowledge.delete', '删除知识库', 'knowledge', '删除知识库'),
    ('00000000-0000-0000-0000-perm00024', 'settings.view', '查看设置', 'settings', '查看系统设置'),
    ('00000000-0000-0000-0000-perm00025', 'settings.llm', '配置LLM', 'settings', '配置大语言模型参数'),
    ('00000000-0000-0000-0000-perm00026', 'settings.agent', '配置Agent', 'settings', '配置Agent工作流'),
    ('00000000-0000-0000-0000-perm00027', 'settings.rbac', '管理权限', 'settings', '管理角色和权限');

-- ============================================================
-- 十、初始数据 - 角色权限分配 (与 rbac.py DEFAULT_ROLES 对齐)
-- ============================================================

INSERT IGNORE INTO rbac_role_permissions (id, role_id, permission_id)
SELECT CONCAT('00000000-0000-0000-rp-admin-', p.code), r.id, p.id
FROM rbac_roles r, rbac_permissions p WHERE r.name = 'admin';

INSERT IGNORE INTO rbac_role_permissions (id, role_id, permission_id)
SELECT CONCAT('00000000-0000-0000-rp-mgr-', p.code), r.id, p.id
FROM rbac_roles r, rbac_permissions p
WHERE r.name = 'project_manager' AND p.code NOT IN ('settings.rbac', 'settings.agent');

INSERT IGNORE INTO rbac_role_permissions (id, role_id, permission_id)
SELECT CONCAT('00000000-0000-0000-rp-writer-', p.code), r.id, p.id
FROM rbac_roles r, rbac_permissions p
WHERE r.name = 'writer' AND p.code IN (
    'project.create', 'project.read', 'project.update',
    'interpret.upload', 'interpret.parse', 'interpret.view',
    'generate.outline', 'generate.content', 'generate.review',
    'check.run', 'check.export',
    'format.run',
    'knowledge.search'
);

INSERT IGNORE INTO rbac_role_permissions (id, role_id, permission_id)
SELECT CONCAT('00000000-0000-0000-rp-reviewer-', p.code), r.id, p.id
FROM rbac_roles r, rbac_permissions p
WHERE r.name = 'reviewer' AND p.code IN (
    'project.read',
    'interpret.view',
    'generate.review',
    'check.run', 'check.export', 'check.report',
    'format.run'
);

-- ============================================================
-- 十一、初始数据 - 默认管理员
-- ============================================================

INSERT IGNORE INTO users (id, email, name, role, password_hash)
VALUES ('00000000-0000-0000-0000-user00001', 'admin@bidmaster.pro', '系统管理员', 'admin', '240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9');

INSERT IGNORE INTO rbac_user_roles (id, user_id, role_id)
SELECT '00000000-0000-0000-ur-admin-role', u.id, r.id
FROM users u, rbac_roles r
WHERE u.email = 'admin@bidmaster.pro' AND r.name = 'admin';

-- ============================================================
-- 十二、初始数据 - 默认 Agent 配置 (与 llm_config.py DEFAULT_AGENTS 对齐)
-- ============================================================

INSERT IGNORE INTO agent_configs (id, name, workflow_dsl, skills, config, enabled) VALUES
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
     '{"display_name": "导出Agent", "description": "导出最终投标文件", "temperature": 0.0, "max_tokens": 2048}', TRUE);

SELECT 'BidMaster Pro database initialized successfully!' AS message;
