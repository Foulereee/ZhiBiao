# BidMaster Pro - 全流程智能招投标平台

<div align="center">

![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.12+-green.svg)
![License](https://img.shields.io/badge/license-MIT-orange.svg)

**基于 AI Agent 架构的智能招投标解决方案**

[功能特性](#功能特性) • [技术架构](#技术架构) • [快速开始](#快速开始) • [项目结构](#项目结构) • [API文档](#api文档)

</div>

---

## 📋 项目简介

BidMaster Pro 是一个基于现代 AI 技术构建的全流程智能招投标平台，采用微服务架构和 Agent 驱动的设计理念。系统通过 LLM（大语言模型）、RAG（检索增强生成）和 Skill Engine（技能引擎）三大核心引擎，实现从招标文件解读、投标书自动生成、合规性检查到文档输出的完整工作流自动化。

### 核心价值

- **智能化**: 利用大语言模型自动理解招标文件，生成高质量投标内容
- **自动化**: 一键完成大纲生成、内容填充、格式排版等繁琐工作
- **合规性**: 内置 21 项专业检查规则，确保投标文件符合招标要求
- **可扩展**: 基于 Skill 架构，支持自定义业务逻辑和功能扩展
- **多模态**: 支持 PDF、Word、TXT 等多种文档格式的解析和输出

---

## ✨ 功能特性

### 🎯 核心工作流

#### 1. 招标解读 (Interpret)
- **智能文档解析**: 支持 PDF/DOCX/TXT 等多格式招标文件解析
- **关键信息提取**: 自动识别评分标准、资质要求、技术参数等核心要素
- **风险预警**: 多维度风险评估，标记潜在废标风险点
- **评分矩阵**: 自动生成评分细则对照表

#### 2. 投标生成 (Generate)
- **大纲生成**: 基于招标文件智能生成投标文件大纲
- **内容创作**: AI 辅助撰写各章节内容，支持扩写和优化
- **知识检索**: RAG 引擎提供企业知识库和历史案例参考
- **AI 配图**: 智能生成配套图表和示意图

#### 3. 投标检查 (Check)
- **合规性检查**: 检查是否符合招标文件强制性要求
- **资格审查**: 验证企业资质、业绩、人员等资格条件
- **一致性校验**: 确保前后文数据、金额、日期等信息一致
- **重复率检测**: 避免内容过度重复或抄袭
- **价格合理性**: 分析报价逻辑和竞争性
- **21 项专业检查**: 涵盖保证金、签字盖章、有效期等全方位审核

#### 4. 文档输出 (Format)
- **智能排版**: 自动调整格式、字体、段落样式
- **模板配置**: 支持自定义投标文件模板
- **PDF 导出**: 一键生成标准 PDF 投标文件
- **修订模式**: 支持多人协作审阅和批注

### 🚀 辅助功能

#### 资讯中心
- **商机监控**: 定时抓取招投标网站最新公告
- **关键词过滤**: 精准匹配关注的行业和地区
- **热度分析**: AI 评估项目价值和竞争程度

#### 知识库管理
- **向量检索**: 基于 ChromaDB 的语义搜索
- **文档管理**: 企业资料、历史标书、产品手册集中管理
- **智能问答**: 基于知识库的 Q&A 助手

#### 权限管理 (RBAC)
- **角色定义**: 管理员、项目经理、编写员、审核员
- **细粒度权限**: 菜单级和操作级权限控制
- **团队协作**: 多用户协同编辑和审核

---

## 🏗️ 技术架构

### 系统架构图

```
┌─────────────────────────────────────────────────────┐
│                  Desktop Client                      │
│         React + Electron + TypeScript                │
└──────────────────┬──────────────────────────────────┘
                   │ REST API
┌──────────────────▼──────────────────────────────────┐
│                 FastAPI Server                       │
│              (Python 3.12+)                          │
├─────────────────────────────────────────────────────┤
│  Router Layer                                        │
│  ├── Projects  ├── Interpret  ├── Generate          │
│  ├── Check     ├── Format     ├── Skills            │
│  ├── News      ├── Knowledge  ├── RBAC              │
│  └── AI-Image                                       │
├─────────────────────────────────────────────────────┤
│  Core Engines                                        │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐│
│  │ Agent Engine │ │ Skill Engine │ │  RAG Engine  ││
│  │  LangGraph   │ │  Plugin Sys  │ │  ChromaDB    ││
│  └──────────────┘ └──────────────┘ └──────────────┘│
│  ┌──────────────┐ ┌──────────────┐                  │
│  │  LLM Gateway │ │ Doc Engine   │                  │
│  │  LiteLLM     │ │ Multi-Parser │                  │
│  └──────────────┘ └──────────────┘                  │
├─────────────────────────────────────────────────────┤
│  Infrastructure                                      │
│  ├── PostgreSQL (AsyncPG)                           │
│  ├── Redis (Celery Broker)                          │
│  ├── MinIO (Object Storage)                         │
│  └── Celery Worker (Async Tasks)                    │
└─────────────────────────────────────────────────────┘
```

### 核心技术栈

#### 后端 (Backend)
| 技术 | 用途 | 版本 |
|------|------|------|
| **FastAPI** | Web 框架 | >=0.115 |
| **Python** | 编程语言 | >=3.12 |
| **SQLAlchemy** | ORM 框架 | >=2.0 |
| **PostgreSQL** | 关系数据库 | 16 |
| **AsyncPG** | 异步数据库驱动 | >=0.30 |
| **Redis** | 缓存/消息队列 | 7 |
| **Celery** | 异步任务队列 | >=5.3 |
| **MinIO** | 对象存储 | Latest |

#### AI & LLM
| 技术 | 用途 | 版本 |
|------|------|------|
| **LiteLLM** | LLM 统一接口 | >=1.0 |
| **LangGraph** | Agent 工作流编排 | >=0.2 |
| **LangChain-Core** | LLM 基础组件 | >=0.3 |
| **ChromaDB** | 向量数据库 | >=0.5 |
| **Sentence-Transformers** | 文本嵌入 | >=3.0 |
| **ONNX Runtime** | 文档分类模型 | >=1.17 |

#### 前端 (Frontend)
| 技术 | 用途 | 版本 |
|------|------|------|
| **React** | UI 框架 | ^19.0.0 |
| **Electron** | 桌面应用容器 | ^41.0.0 |
| **TypeScript** | 类型系统 | ^5.5.0 |
| **Vite** | 构建工具 | ^7.0.0 |
| **Zustand** | 状态管理 | ^5.0.0 |
| **React Router** | 路由管理 | ^7.0.0 |
| **TanStack Query** | 数据请求 | ^5.0.0 |
| **Radix UI** | 无头组件库 | ^1.1.0 |
| **TailwindCSS** | 样式框架 | ^4.0.0 |

#### 文档处理
| 技术 | 用途 | 版本 |
|------|------|------|
| **python-docx** | Word 文档处理 | >=1.1 |
| **pdfplumber** | PDF 文本提取 | >=0.11 |
| **PyMuPDF** | PDF 高级处理 | >=1.24 |
| **Mammoth** | DOCX 转 HTML | >=1.8 |
| **WeasyPrint** | HTML 转 PDF | >=61 |
| **BeautifulSoup4** | HTML 解析 | >=4.12 |

---

## 📁 项目结构

```
BidMaster-Pro/
├── core/                          # 核心引擎层
│   ├── agent_engine/              # Agent 编排引擎
│   │   ├── orchestrator.py        # 工作流编排器 (LangGraph)
│   │   ├── gate_keeper.py         # 闸门控制器 (阶段准入检查)
│   │   └── state.py               # 状态管理
│   ├── skill_engine/              # 技能引擎
│   │   ├── base.py                # Skill 基类定义
│   │   ├── registry.py            # 技能注册中心
│   │   └── loader.py              # 技能加载器
│   ├── rag_engine/                # RAG 检索增强引擎
│   │   ├── vector_store.py        # 向量存储 (ChromaDB)
│   │   ├── embedder.py            # 文本嵌入器
│   │   └── retriever.py           # 检索器
│   ├── llm_gateway/               # LLM 网关
│   │   ├── gateway.py             # 统一 LLM 接口 (LiteLLM)
│   │   └── json_repair.py         # JSON 修复引擎
│   ├── doc_engine/                # 文档引擎
│   │   ├── parsers/               # 文档解析器
│   │   │   ├── pdf_parser.py      # PDF 解析
│   │   │   ├── docx_parser.py     # Word 解析
│   │   │   └── txt_parser.py      # 文本解析
│   │   ├── section_detector.py    # 章节检测器
│   │   └── onnx_classifier.py     # ONNX 文档分类
│   ├── settings.py                # 全局配置
│   └── exceptions.py              # 自定义异常
│
├── services/                      # 服务层
│   ├── routers/                   # API 路由
│   │   ├── projects.py            # 项目管理
│   │   ├── interpret.py           # 招标解读
│   │   ├── generate.py            # 投标生成
│   │   ├── check.py               # 投标检查
│   │   ├── format_doc.py          # 文档输出
│   │   ├── skills.py              # Skill 管理
│   │   ├── news.py                # 资讯中心
│   │   ├── knowledge.py           # 知识库
│   │   ├── rbac.py                # 权限管理
│   │   └── ai_image.py            # AI 配图
│   ├── interpret/skills/          # 解读技能
│   │   ├── tender_interpret_skill.py
│   │   ├── scoring_matrix_skill.py
│   │   └── risk_alert_skill.py
│   ├── generate/skills/           # 生成技能
│   │   ├── outline_gen_skill.py
│   │   ├── content_gen_skill.py
│   │   └── structure_template_skill.py
│   ├── check/skills/              # 检查技能 (21项)
│   │   ├── compliance_check_skill.py
│   │   ├── disqualification_check_skill.py
│   │   ├── duplicate_check_skill.py
│   │   ├── pricing_check_skill.py
│   │   └── ... (共21个检查技能)
│   ├── format/skills/             # 格式化技能
│   │   ├── docx_format_skill.py
│   │   └── pdf_export_skill.py
│   ├── main.py                    # FastAPI 应用入口
│   ├── models.py                  # 数据库模型 (SQLAlchemy)
│   ├── database.py                # 数据库连接
│   ├── celery_app.py              # Celery 配置
│   └── skill_bootstrap.py         # 技能初始化
│
├── packages/desktop/              # 桌面客户端
│   ├── main/                      # Electron 主进程
│   ├── preload/                   # 预加载脚本
│   └── renderer/                  # React 渲染进程
│       ├── src/
│       │   ├── pages/             # 页面组件
│       │   │   ├── DashboardPage.tsx
│       │   │   ├── InterpretPage.tsx
│       │   │   ├── GeneratePage.tsx
│       │   │   ├── CheckPage.tsx
│       │   │   ├── FormatPage.tsx
│       │   │   ├── NewsPage.tsx
│       │   │   └── SettingsPage.tsx
│       │   ├── components/        # 通用组件
│       │   ├── services/          # API 服务
│       │   ├── stores/            # Zustand 状态
│       │   └── App.tsx            # 应用根组件
│       └── index.html
│
├── skills/                        # Skill 定义文件 (Markdown)
│   ├── check/compliance_check/SKILL.md
│   ├── generate/content_gen/SKILL.md
│   └── interpret/tender_interpret/SKILL.md
│
├── templates/                     # 文档模板
│   └── default.yaml
│
├── db/                            # 数据库迁移和种子数据
│   ├── migrations/
│   └── seeds/
│
├── docker/                        # Docker 配置
│   ├── Dockerfile.api
│   └── docker-compose.yml
│
├── tests/                         # 测试文件
├── .env.example                   # 环境变量示例
├── pyproject.toml                 # Python 依赖配置
└── alembic.ini                    # 数据库迁移配置
```

---

## 🚀 快速开始

### 环境要求

- **Python**: 3.12+
- **Node.js**: 18+
- **PostgreSQL**: 16+
- **Redis**: 7+
- **Docker & Docker Compose** (推荐)

### 方式一：Docker 部署（推荐）

#### 1. 克隆项目

```bash
git clone <repository-url>
cd BidMaster-Pro
```

#### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填写 LLM API Key 等配置
```

#### 3. 启动服务

```bash
docker-compose up -d
```

这将启动以下服务：
- PostgreSQL (端口 5432)
- Redis (端口 6379)
- MinIO (端口 9000, 控制台 9001)
- FastAPI Server (端口 8000)
- Celery Worker

#### 4. 访问应用

- API 文档: http://localhost:8000/docs
- MinIO 控制台: http://localhost:9001

### 方式二：本地开发

#### 1. 安装依赖

**后端依赖:**
```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate     # Windows

# 安装依赖
pip install -e .
```

**前端依赖:**
```bash
cd packages/desktop
npm install
```

#### 2. 启动基础设施

```bash
# 使用 Docker 仅启动数据库和中间件
docker-compose up -d postgres redis minio
```

#### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，至少配置以下内容：
# BMP_LLM_API_KEY=your_api_key
# BMP_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/bidmaster
# BMP_REDIS_URL=redis://localhost:6379/0
```

#### 4. 初始化数据库

```bash
alembic upgrade head
```

#### 5. 启动后端服务

```bash
# 终端 1: 启动 FastAPI
uvicorn services.main:app --reload --host 0.0.0.0 --port 8000

# 终端 2: 启动 Celery Worker
celery -A services.celery_app worker --loglevel=info
```

#### 6. 启动前端桌面应用

```bash
cd packages/desktop
npm run electron:dev
```

---

## ⚙️ 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `BMP_DEBUG` | 调试模式 | `true` |
| `BMP_HOST` | 服务地址 | `0.0.0.0` |
| `BMP_PORT` | 服务端口 | `8000` |
| `BMP_DATABASE_URL` | PostgreSQL 连接串 | `postgresql+asyncpg://...` |
| `BMP_REDIS_URL` | Redis 连接串 | `redis://localhost:6379/0` |
| `BMP_CHROMA_DIR` | ChromaDB 存储路径 | `./chroma_db` |
| `BMP_PROJECTS_ROOT` | 项目文件根目录 | `./projects` |
| `BMP_LLM_DEFAULT_MODEL` | 默认 LLM 模型 | `deepseek/deepseek-chat` |
| `BMP_LLM_API_KEY` | LLM API Key | - |
| `BMP_LLM_API_BASE` | LLM API 地址 | `https://api.deepseek.com` |
| `BMP_LLM_FALLBACK_MODES` | 降级模型列表 | `ollama/qwen2.5` |
| `BMP_EMBEDDING_MODE` | 嵌入模式 (api/local) | `api` |
| `BMP_EMBEDDING_MODEL` | 嵌入模型 | `text-embedding-v3` |
| `BMP_EMBEDDING_API_KEY` | 嵌入 API Key | - |

### LLM 提供商支持

通过 LiteLLM，系统支持多种 LLM 提供商：

- **DeepSeek**: `deepseek/deepseek-chat`
- **OpenAI**: `gpt-4`, `gpt-3.5-turbo`
- **Anthropic**: `claude-3-opus`, `claude-3-sonnet`
- **阿里云通义千问**: `qwen-max`, `qwen-plus`
- **Ollama (本地)**: `ollama/qwen2.5`, `ollama/llama3`

修改 `.env` 中的 `BMP_LLM_API_KEY` 和 `BMP_LLM_API_BASE` 即可切换。

---

## 📖 API 文档

启动服务后访问 http://localhost:8000/docs 查看完整的 OpenAPI 文档。

### 主要 API 端点

#### 项目管理
- `POST /api/projects` - 创建项目
- `GET /api/projects` - 获取项目列表
- `GET /api/projects/{id}` - 获取项目详情
- `DELETE /api/projects/{id}` - 删除项目

#### 招标解读
- `POST /api/interpret/upload` - 上传招标文件
- `POST /api/interpret/analyze` - 执行智能分析
- `GET /api/interpret/{project_id}/result` - 获取解读结果

#### 投标生成
- `POST /api/generate/outline` - 生成大纲
- `POST /api/generate/chapter` - 生成章节内容
- `POST /api/generate/expand` - 内容扩写

#### 投标检查
- `POST /api/check/run` - 执行检查
- `GET /api/check/{project_id}/reports` - 获取检查报告
- `POST /api/check/compliance` - 合规性检查
- `POST /api/check/pricing` - 价格检查

#### 文档输出
- `POST /api/format/docx` - 生成 Word 文档
- `POST /api/format/pdf` - 导出 PDF
- `POST /api/format/apply-template` - 应用模板

#### 资讯中心
- `GET /api/news/list` - 获取新闻列表
- `POST /api/news/crawl` - 手动触发爬取
- `GET /api/news/tasks` - 获取监控任务

#### 知识库
- `POST /api/knowledge/upload` - 上传知识文档
- `POST /api/knowledge/search` - 语义搜索
- `GET /api/knowledge/collections` - 获取知识库列表

---

## 🔧 核心概念

### Skill (技能)

Skill 是 BidMaster Pro 的核心扩展机制，每个 Skill 代表一个独立的业务能力单元。

#### Skill 结构

```python
from core.skill_engine.base import Skill, SkillContext, SkillResult

class MyCustomSkill(Skill):
    name = "my_custom_skill"
    description = "我的自定义技能"
    category = "generate"
    version = "1.0.0"
    
    async def execute(self, ctx: SkillContext) -> SkillResult:
        # 1. 获取参数
        param1 = ctx.parameters.get("param1")
        
        # 2. 调用 LLM
        response = await ctx.llm.chat(messages=[...])
        
        # 3. 返回结果
        return SkillResult(
            success=True,
            data={"result": response},
            tokens_consumed=100
        )
```

#### Skill 注册

在 `services/skill_bootstrap.py` 中注册：

```python
def register_builtin_skills():
    from core.skill_engine.registry import SkillRegistry
    registry = SkillRegistry.instance()
    
    # 注册内置技能
    registry.register(ComplianceCheckSkill)
    registry.register(ContentGenSkill)
    # ...
```

### Agent Pipeline (Agent 流水线)

使用 LangGraph 编排多个 Skill 的执行流程：

```python
pipeline_dsl = {
    "entry": "parse_tender",
    "nodes": [
        {"id": "parse_tender", "skill": "tender_parser", "require_gate": True},
        {"id": "extract_requirements", "skill": "requirement_extractor"},
        {"id": "generate_outline", "skill": "outline_generator"},
    ],
    "edges": [
        {"from": "parse_tender", "to": "extract_requirements"},
        {"from": "extract_requirements", "to": "generate_outline"},
    ]
}
```

### Gate Keeper (闸门控制器)

确保工作流按顺序执行，前一阶段未完成则不能进入下一阶段：

```python
gate_keeper.mark_passed(project_id, "interpret")
if not gate_keeper.is_passed(project_id, "interpret"):
    raise GateNotPassedException("请先完成招标解读")
```

---

## 🧪 测试

```bash
# 运行所有测试
pytest tests/

# 运行特定模块测试
pytest tests/test_interpret.py

# 带覆盖率报告
pytest --cov=core --cov=services tests/
```

---

## 📊 数据库模型

### 核心实体关系

```
User (用户)
  └── Project (项目)
        ├── Document (文档)
        ├── Analysis (分析结果)
        ├── Outline (大纲)
        ├── Chapter[] (章节)
        └── CheckReport[] (检查报告)

KnowledgeBase (知识库)
MonitoringTask (监控任务)
  └── CrawlResult[] (爬取结果)

RBACRole (角色) ↔ RBACPermission (权限)
```

详细模型定义见 [services/models.py](file:///E:/workspace-llm/biaoshu/BidMaster-Pro/services/models.py)

---

## 🛠️ 开发指南

### 添加新的 Skill

1. **创建 Skill 类**

```python
# services/generate/skills/my_new_skill.py
from core.skill_engine.base import Skill, SkillContext, SkillResult

class MyNewSkill(Skill):
    name = "my_new_skill"
    description = "新功能描述"
    category = "generate"
    
    async def execute(self, ctx: SkillContext) -> SkillResult:
        # 实现逻辑
        pass
```

2. **创建 SKILL.md 文档**

```markdown
# skills/generate/my_new_skill/SKILL.md

## 功能说明
...

## 输入参数
- param1: 描述

## 输出格式
{
  "result": "..."
}
```

3. **注册 Skill**

在 `services/skill_bootstrap.py` 中添加：

```python
from services.generate.skills.my_new_skill import MyNewSkill
registry.register(MyNewSkill)
```

4. **添加到 API 路由**

在对应的 router 中调用该 Skill。

### 代码规范

- **Python**: 遵循 PEP 8，使用 `ruff` 进行 linting
- **TypeScript**: 遵循项目 ESLint 配置
- **提交信息**: 使用 Conventional Commits 规范

```bash
# 代码检查
ruff check .
ruff format .

# 类型检查
mypy core services
```

---

## 🐳 Docker 部署

### 生产环境部署

```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f api

# 停止服务
docker-compose down
```

### 环境变量配置

创建 `docker-compose.override.yml`:

```yaml
version: "3.8"
services:
  api:
    environment:
      BMP_LLM_API_KEY: ${LLM_API_KEY}
      BMP_LLM_API_BASE: https://api.your-provider.com
      BMP_DEBUG: "false"
```

---

## 📈 性能优化

### 数据库优化

- 使用连接池 (SQLAlchemy AsyncEngine)
- 为常用查询字段添加索引
- 定期清理过期数据

### 缓存策略

- Redis 缓存 LLM 响应
- 向量检索结果缓存
- 静态资源 CDN 加速

### 异步处理

- 耗时操作通过 Celery 异步执行
- 使用 WebSocket 推送进度
- 批量操作使用并发控制

---

## 🔒 安全考虑

- **认证**: JWT Token 认证
- **授权**: RBAC 细粒度权限控制
- **数据加密**: 敏感字段加密存储
- **API 限流**: 防止滥用
- **输入验证**: Pydantic 模型验证
- **CORS**: 跨域资源共享控制

---

## 🤝 贡献指南

欢迎贡献代码、报告问题或提出建议！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

---

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

---

## 📞 联系方式

- **项目主页**: [GitHub Repository]
- **问题反馈**: [Issues]
- **邮箱**: support@bidmaster.pro

---

## 🙏 致谢

感谢以下开源项目的支持：

- [FastAPI](https://fastapi.tiangolo.com/)
- [LangGraph](https://langchain-ai.github.io/langgraph/)
- [LiteLLM](https://docs.litellm.ai/)
- [ChromaDB](https://www.trychroma.com/)
- [React](https://react.dev/)
- [Electron](https://www.electronjs.org/)

---

<div align="center">

**Made with ❤️ by BidMaster Team**

⭐ 如果这个项目对你有帮助，请给我们一个 Star！

</div>