# 变更记录

本文件记录本仓库（https://github.com/Foulereee/ZhiBiao）相对上游 https://github.com/guangshu100/BidMaster-Pro 的修改，便于下游使用者判断差异。

格式参考 Keep a Changelog；日期为本地时间。

## [1.0.0] - 2026-10-05

首个对外发布的衍生版本，基于上游 `main@cc89d90`。

### Added（新增）

- `core/env_store.py`：无损修改 `.env`（保留注释、分组与顺序），修复此前“改配置把 `.env` 注释全冲掉”的问题。
- `services/routers/app_config.py`：品牌配置接口 `/api/app-config`（GET/PUT，改名热生效，带 `no-store`）。
- `services/format/font_utils.py`：docx 字体规范化工具，统一导出文档字体。
- `deploy/`：迁移运维工具链 —— `export_all.sh`、`import_all.sh`、`rebuild_and_verify.sh`、`seed_admin.py`
  以及《全新主机部署手册》《部署迁移方案》。
- `.gitattributes`：统一入库行尾为 LF，保证 Linux 容器内脚本可执行。
- `NOTICE.md` / `SECURITY.md` / `CONTRIBUTING.md` / `THIRD_PARTY_NOTICES.md`：开源合规与协作文件。

### Fixed（修复）

- **导出文档封面/页脚异常**：修复导出后封面信息与页脚页码错乱的问题。
- **字体与排版**：docx 字体规范化，避免缺字体导致的排版走样。
- **鉴权补齐**：为若干原本缺少鉴权的路由补齐认证依赖，未登录不可访问。
- **LLM 调用稳定性**：`core/llm_gateway/gateway.py` 直连 OpenAI 兼容端点（不再经 litellm 转发），
  确保 `response_format`、`temperature`、`max_tokens` 等参数正确传递；补充超时与重试策略。
- **检查链路**：`services/check/` 下检查类 Skill 的超时/并发行为修正，避免“执行检查中”长时间无响应。
- **Agent 框架**：`core/agent_framework/` 工具注册、上下文绑定与 DB 查询工具修复。
- **docker**：`Dockerfile.api`、`docker-compose.yml`、`entrypoint.sh`、`nginx.conf` 修正，保证站点与 API 稳定启动。
- **前端**：工作台、检查、排版、设置等页面交互与状态修复。

### Changed（调整）

- `.env.example`：移除示例中的真实 API Key，改为空值 + 注释说明（**请填入你自己的 Key**）。
- `README.md`：更正许可证描述为 AGPL-3.0（原文误写 MIT），更新维护者信息与联系方式；
  修正技术栈中与实现不符的描述（实际运行时编排为自研多 Agent 框架，LangGraph 引擎为预留未接入）。
- `pyproject.toml` / `packages/desktop/package.json`：补充 `license` 与 `authors`/`author` 字段。

### Removed（移除）

- `packages/desktop/images/wechat-qrcode.png`：上游作者的个人公众号二维码，与本仓库维护者无关。
- `assets/screenshots/01_登录页.png`：画面内包含默认管理员账号提示，不适合放在公开仓库。
- `assets/screenshots/智标2.0_导出Markdown修复_前后对比.png`、`…_投标检查_修复方案.png`、`…_等待反馈_正文生成中.png`：
  这三张来自另一套部署（另一端口的产品界面），与本仓库 B/S 界面不符，属放错位置。
- `packages/desktop/logo.png`：与 `packages/desktop/renderer/src/assets/logo.png` **字节完全相同**的 2.5 MB
  重复文件，且未被 electron-builder / 主进程 / 前端引用。

### Security（安全）

- 仓库内不含任何生产密钥：`.env` 被 `.gitignore` 忽略且从未进入本仓库历史；
  本机私有的运维记录、迁移包、构建产物均已加入忽略清单。
- ⚠️ 若你曾把真实 Key 写进 `*.example` 文件并提交，**请立即到服务商控制台轮换该 Key**。

## [1.0.1] - 2026-10-09

第二轮修订：清理放错的素材、补齐"修复效果"的可复现证据，并修掉两处会误导新部署者的配置/文档陷阱。

### Added（新增）

- `tools/font_normalize_evidence.py`：字体归一化的可复现实测脚本（生成"缺 `w:eastAsia`"的样例 docx
  → 调 `normalize_docx_fonts()` → 打印前后字体取值对比），README「修复效果实测」数据由它产出。
- `assets/diagrams/zhibiao-font-normalize.png`：字体问题根因/修复/实测/边界四段式证据图（由
  `迁移部署/工具/生成文档/README字体证据图.py` 生成，该生成器不进公开仓库）。
- `README.md` 新增「本仓库的实机验证记录」：方式二逐环节结果 + 方式一未实机的原因与静态校验结论 + 已知边界。

### Fixed（修复）

- **`docker/.env.docker.example`**：`UVICORN_WORKERS` 由 `2` 改为 `1` 并写明原因 —— 登录会话保存在
  `services/routers/auth.py` 的进程内 `_sessions` 字典，多 worker 时登录与后续请求可能落到不同进程，
  表现为随机退出登录 / 401（线上实际以 `--workers 1` 运行）。
- **`.gitattributes`**：新增 `*.bat text eol=crlf`。`start-postgres.bat` / `stop-postgres.bat` 原本以 LF
  入库，在 Windows 上 cmd 会逐行报"不是内部或外部命令"，导致便携 PostgreSQL 启停脚本不可用。
- **`README.md` 快速开始（方式二）**：删掉 `alembic upgrade head`（仓库内并无 `db/migrations`，
  该命令必然失败），改为 `psql -f db/init_pg.sql` + 说明启动时 `create_all` 会补齐其余表；
  修正前端 dev 端口（`vite.config.ts` 写死 **15168**，不是 5173）与 `VITE_API_TARGET` 用法；
  补充 `.env` 相对 CWD、Redis 仅 Celery 需要等前置条件。
- **`README.md` 快速开始（方式一）**：补上 `--profile infra --profile web`（否则只起 api + celery）、
  `docker/.env.docker` 的正确路径与站点端口（`WEB_PORT` 默认 8080）。

### Changed（调整）

- `README.md`：「重点修复」表补充 6 条（字体根因、两条导出链路不一致、多 worker 会话、批处理行尾、
  alembic 指向、`feedparser` 漏声明）；「新增能力」表按业务域展开到 16 条（投标检查的修复方案/原文定位/
  一键应用/报告导出与删除/上传直查、投标生成的按大纲排序与提示词组装、文档输出的目录级别与三格式等）。
- `README.md`：「界面预览」改为 13 张真实 B/S 截图（移除登录页条目）。
- `README.md`：「实机截图（修复证据）」改为「修复效果实测（可复现）」——用实测数字与代码位置替代营销式截图。

### Removed（移除）

- 见 [1.0.0] 段落，第二轮共删除 5 个放错/重复的图片文件（合计约 3.97 MB）；
  仓库跟踪体积由约 10.7 MB 降至 **7.06 MB（227 个文件）**，其中最大单项仍是前端 logo（2.45 MB，见「已知边界」）。

## [1.0.2] - 2026-10-09

按"下载 ZIP 后照抄文档"的真实路径重跑一遍，修掉三处会直接卡住新部署者的问题，并补一份完整部署手册。

### Added（新增）

- **`DEPLOY.md`：完整部署手册**（README 快速开始已精简并指向它）。包含：
  ZIP 解压常见的"多套一层目录"判据（`pyproject.toml` 与 `docker/docker-compose.yml` 必须同层）、
  目录与文件地图（谁读哪个文件）、方式一/方式二逐步命令、两套环境变量表（`docker/.env.docker` 用无前缀名、
  根 `.env` 用 `BMP_*`）、首次登录与 `seed_admin.py` 用法、停止/升级/数据安全（`down` vs `down -v`）、
  12 条常见报错对照表、本机实测记录与已知边界。

### Fixed（修复）

- **`docker/docker-compose.yml`**：`UVICORN_WORKERS` 默认值 `2` → **`1`**。登录会话保存在
  `services/routers/auth.py` 的进程内字典 `_sessions`，多 worker 会让"登录"与后续请求落到不同进程，
  表现为随机退出登录 / 401（1.0.1 只改了示例文件，编排与镜像里的默认值仍是 2，等于没堵住）。
- **`docker/Dockerfile.api`**：`CMD` 里的 `--workers ${UVICORN_WORKERS:-2}` → **`:-1`**，与编排保持一致。
- **`.gitignore`**：补 `docker/.env.docker`、`docker/.env`。此前只有根 `.env` 被忽略，
  而方式一要求把 `LLM_API_KEY` 填进 `docker/.env.docker` —— 一旦 `git add -A` 就会把真实密钥提交上去。
- **README 方式一**：改为正确命令
  `docker compose -f docker/docker-compose.yml --env-file docker/.env.docker --profile infra --profile web up -d --build`。
  原文档在仓库根目录直接 `docker compose ... up`，必然报 `no configuration file provided: not found`
  —— 编排文件在 `docker/` 下，且其内部 `../db`、`../skills`、`../templates`、`../.env` 都是相对
  compose 文件所在目录解析的（所以也不能加 `--project-directory .`）。
- **README 方式一**：补两个前置步骤 —— 根 `.env` 必须存在（`../.env:/app/.env` 的挂载源缺失时，
  Docker 会把 `.env` 建成**目录**），以及 Key 必须写进 `docker/.env.docker`
  （`LLM_API_KEY` 等五个键默认值是空串，会把容器内同名 `BMP_*` 覆盖成空）。
- **README 方式二**：`start-postgres.bat` 说明纠正 —— 它依赖的 `.pgsql/` 免安装运行时**不在仓库里**
  （已被 `.gitignore` 排除），全新下载直接运行会提示找不到 `pg_ctl`；补 PowerShell 激活写法与执行策略提示；
  补 `python deploy/seed_admin.py` 步骤（系统不会自动创建管理员，不跑它就没有账号可登录）。

### Changed（调整）

- README「环境要求」改为方式一/方式二对照表，明确哪些组件只是其中一条路需要。

## [1.0.3] - 2026-10-10

新增 Windows 一键安装脚本，并把"照抄文档仍会踩到的坑"一并堵上。

### Added（新增）

- **`install.ps1`：一键安装/部署（Windows PowerShell，无需管理员权限）**
  - 自动判断：`docker info` 可用则走方式一（Docker 全量），否则走方式二（本地开发）；每步都有
    `[OK]/[..]/[!]/[X]` 状态，全过程日志落 `logs\install-<时间戳>.log`。
  - 方式二：校验 Python≥3.12 → `venv` + `pip install -e .` → `npm install` → 检查/启动 PostgreSQL
    （依次找 `<仓库>\.pgsql`、`-PgRoot`、PATH 里的 `pg_ctl`）→ 建库 + 导入 `db/init_pg.sql` →
    生成 `.env` → `deploy/seed_admin.py` 建管理员 → 后台启动 uvicorn 与 vite → 轮询 `/api/health` 与首页。
  - 方式一：生成根 `.env` 与 `docker\.env.docker` → 一条
    `docker compose -f docker/docker-compose.yml --env-file docker/.env.docker --profile infra --profile web up -d --build`
    → 等健康检查（最多 8 分钟）→ 容器内执行 `seed_admin.py`。
  - **幂等**：可重复执行；已存在的 `.env` / `docker\.env.docker` 默认保留，`-Force` 才重建（会先备份）。
  - 生成的 `.env` 以 **UTF-8 无 BOM** 写入：PowerShell 5.1 的 `Set-Content -Encoding UTF8` 会写 BOM，
    而 pydantic 会把 BOM 算进第一个键名，导致整份配置失效。
  - 端口、库名、管理员、Key 均可用参数覆盖，详见 `DEPLOY.md` §9。
- **`stop.ps1`**：按端口停本地 API 与前端；`-WithPg` 连便携 PostgreSQL 一起停；
  `-Docker` 走 compose stop，`-Docker -Remove` 删容器与网络（数据卷默认保留，加 `-Volumes` 才删）。
- `DEPLOY.md` 新增 §9「一键脚本（Windows）」；README 新增「⚡ 一键安装」小节。

### Fixed（修复）

- **`.gitignore`**：补 `logs/`。
- **`.gitattributes`**：补 `*.ps1 text eol=crlf`（Windows PowerShell 对 LF 行尾的 `.ps1` 兼容性差）。
- 脚本会明确说出 Docker 引擎不可用的原因（Docker Desktop 未启动 / 未启用 WSL2-Hyper-V）。
  本机实测：`wsl --status` 报未安装、`HypervisorPresent=False` →
  `Error response from daemon: Docker Desktop is unable to start`；此时 `-Mode auto` 会自动回落本地模式。
- **`db/init_pg.sql`：修掉 `projects` ↔ `documents` 的循环外键**
  - 原文件在 `projects` 里内联 `tender_doc_id ... REFERENCES documents(id)`，而 `documents` 又内联
    `project_id ... REFERENCES projects(id)`——两表互相引用，空库上**两张表都建不出来**，紧随其后的
    74 条 `COMMENT` / `CREATE INDEX` 级联报 `relation "projects"/"documents" does not exist`。
  - 改为"先建表、两表就绪后用幂等 `DO` 块补 `fk_projects_tender_doc`"。
  - 实测：空库导入 `init_pg.sql` **0 报错**，再执行 `init_db()`（`Base.metadata.create_all`）共 **22 张表**，
    与生产库一致。`install.ps1` 同步改为"容错导入 → `init_db()` 补全 → 表数自检"。- **`db/init_pg.sql`：修掉 RBAC 角色-权限绑定的 `value too long`**
  - 4 条 `INSERT INTO rbac_role_permissions ... SELECT '前缀' || p.code, ...` 拼出的 `id` 最长 40+ 字符，
    超过 `id VARCHAR(36)` → PostgreSQL 报 `value too long for type character varying(36)`，
    **整条 `INSERT ... SELECT` 整体回滚**，角色-权限绑定一行都写不进去（实测 0 行）。
  - 改用 `uuid_generate_v4()::text`（固定 36 字符），幂等性仍由 `ON CONFLICT (role_id, permission_id) DO NOTHING` 保证。
  - 实测（全新空库）：导入 `init_pg.sql` **0 报错**、17 张表、72 行绑定
    （admin 27 / project_manager 25 / writer 13 / reviewer 7）、管理员已绑定 admin 角色；
    **重复导入仍 0 报错且行数不变**；再执行 `init_db()` 共 22 张表。- **`start-postgres.bat` / `stop-postgres.bat` 在中文 Windows 上"静默失效"（根因已修）**
  - 两个 bat 以 UTF-8 保存、却在第 2 行 `chcp 65001`：cmd.exe 会按**切换前的代码页**重新换算文件偏移，
    切换之后剩余的每一行都被丢弃 —— 脚本一行输出都没有、`pg.log` 也没生成、数据库自然起不来
    （实测复现；换成 ASCII-only + 无 chcp 的等价脚本后一次成功）。
  - 已重写为 **ASCII-only、不带 chcp**，并在注释里写明"不要再加 chcp"。
    实测三个分支：已在运行 / 启动成功 / 停止，全部正常。
  - 另修一处安全隐患：`stop-postgres.bat` 的兜底从 `taskkill /IM postgres.exe /F`
    （按进程名杀，会连带杀掉同机**其它** PostgreSQL 实例，包括生产库）改为只结束本数据目录
    `postmaster.pid` 中记录的 PID。
  - `install.ps1` 同步改为**优先直接用** `pg_ctl -D <data> -l <log> -w start` 起库，不再依赖 bat。- **README「快速开始」重写为完整部署流程**：新增「前置环境对照表」（三种方式 × 组件 / 权限 / 端口 / 磁盘 / 外网）、
  一键脚本参数表与 8 步动作表、方式一的 Docker 前置（WSL2/Hyper-V）与**两个 env 文件的分工表**、方式二前置说明，
  以及两个通用新章节：「🔑 首次登录与校验」（seed_admin 幂等语义、`admin123` 初值提示、校验清单与期望值）、
  「🛑 停止、重启与升级」（含 `docker compose down -v` 等于删库的警告）。
- `install.ps1`：`-DevPort` 现在**真正生效**（显式给 vite 传 `--port <n> --strictPort`；此前只改了探测地址，
  vite 仍用配置里写死的 15168），因此可在不影响已有实例的前提下于独立端口再部署一套。

## [1.0.4] - 2026-10-10

本轮是**仓库整理**（体积 / 冗余 / 对外信息面），不改业务功能。所有删除项都仍可从 git 历史取回，
例如：`git checkout 5cf4acf -- alembic.ini start.bat`。

### Added（新增）

- `tools/optimize_images.py`：可重复执行的图片瘦身工具，带 PSNR 安全阀（低于 35 dB 就跳过、不替换原图）。
  实测把 17 张 PNG 从 **4.73 MB 压到 1.33 MB（−72%）**：
  - `logo.png`：2048×2048 / 2.39 MB → 256×256 / **64 KB**（仅缩放、无损；它在 `Sidebar.tsx` 只显示 32×32）；
  - 13 张 README 截图：降到 1400px 宽 + 256 色量化，PSNR 39–47 dB，1.64 MB → 0.95 MB；
  - 3 张架构/流程图：**保持原尺寸**只做 256 色量化（原本是 24 位 RGB 存线稿，属低效保存），PSNR 54–56 dB，0.70 MB → 0.26 MB。
  仓库受控文件总量 **7.19 MB → 3.79 MB**；前端构建产物里的 logo 资源 2.4 MB → **66 KB**。
- `DEPLOY.md` §10「迁移到另一台主机（通用做法）」：导出库 / 数据卷 / 环境文件 → 新机恢复 → 逐条核对 → 日常上线，
  用通用命令替代原先依赖私有脚本的流程（并如实标注 Docker 路径未在本机实机跑通）。

### Removed（删除）

- `alembic.ini` 与 `alembic` 依赖：配置指向并不存在的 `db/migrations`，`alembic upgrade head` 必然失败，
  且全仓库没有任何代码引用 alembic。建表统一走 `db/init_pg.sql` + 启动时 `create_all`。
- `core/doc_engine/onnx_classifier.py`（152 行）与 `onnxruntime` 依赖：公开仓库内**零调用方**，
  `core/doc_engine/__init__.py` 也没有转导出它；`onnxruntime` 只被这个文件使用，故一并移除。
- `core/skill_engine/check_normalizer.py`（194 行）：同样零引用（`core/skill_engine/__init__.py` 未导出）。
- `start.bat`：与 `install.ps1` 职责重叠，且第 2 行 `chcp 65001` 正是刚修掉的那类"cmd 丢行"隐患。
  Windows 统一用 `install.ps1`，Linux/macOS 用 `start.py`。
- `THIRD_PARTY_NOTICES.md`：内容并入 `NOTICE.md` 第 5 节（并补记本轮移除的 Alembic / ONNX Runtime）。
- `deploy/export_all.sh`、`deploy/import_all.sh`、`deploy/rebuild_and_verify.sh` 以及《全新主机部署手册》《部署迁移方案》：
  这些是本项目生产环境的运维资产（含真实主机路径、容器名、定时任务、备份与看门狗策略），**移出公开仓库**，
  保留在维护者本地的 `迁移部署/`（该目录在 `.gitignore` 内）。`deploy/` 现只保留 `seed_admin.py`。

### Fixed（修复）

- **README / DEPLOY 里"logo 进 bundle 导致主 chunk 1.7 MB"的说法有误**：实测 vite 用默认 4 KB 内联阈值，
  logo 一直是独立产物（压缩后 66 KB）；替换前后主 chunk 都是 1.70 MB / gzip 525 KB。已按实测更正，
  并说明 chunk 偏大的真实原因是依赖体积与尚未按路由拆包。
- **文档称 `core/agent_engine/` 为预留、未接入运行路径，与代码不符**：`services/routers/generate.py`、
  `projects.py` 与多 Agent 技能共 5 处 `from core.agent_engine.gate_keeper import GateKeeper`。
  已更正为"`gate_keeper.py` 已接入；`orchestrator.py`（LangGraph 建图）仍为预留、仅包内自引用"。
- **`start.py` 在中文 Windows 控制台会崩**：19 处 emoji 符号（✅/❌/⚠️/📦/🗄️/🚀）换成 `[OK]`/`[X]`/`[!]`/`[*]`
  （GBK 控制台无法编码 emoji）；同时把 Python 版本门槛从 3.11 对齐到 `pyproject.toml` 的 `requires-python = ">=3.12"`。

### Security（对外信息面收敛）

- `README.md` 去掉生产站点 IP，只保留"同一套 compose 已在公网 80 端口长期运行（HTTP 200）"这一可验证结论。
- `services/routers/app_config.py`（3 处）与 `core/settings.py`（1 处）里把宿主机真实部署路径
  `/opt/bidmaster/.env` 改写成"宿主机仓库根目录/.env"；`docker/docker-compose.yml` 的网络名 `bidmaster-net`
  属内部命名、无敏感性，保留（改名会与既有部署不一致）。
- 复核结论：仓库内**没有**硬编码密钥；唯一出现的口令是文档中说明的 `db/init_pg.sql` 默认管理员密码
  `admin123`（部署后必须立即修改）；`服务器运维说明.md`、`迁移部署/`、`验证环境/` 均未上传。

## [1.0.5] - 2026-10-11

### Added（新增）

- **`install.sh` / `stop.sh`**：Linux 一键部署脚本（bash），支持 Ubuntu/Debian(apt) 与 CentOS/RHEL/Rocky/AlmaLinux(dnf/yum)。
  默认自动判断 Docker / 本地；`--install-deps` 自动装缺失依赖（Docker / Python3 / Node.js / PostgreSQL）。
  步骤对齐 Windows 的 `install.ps1`：校验目录 → 依赖 → venv → npm → PostgreSQL → 建库建表 → `.env` → 建管理员 → 起服务 → 健康检查。
  已设可执行位（`100755`），行尾 LF。

### Changed（变更）

- **`install.ps1` 增强**：Python / Node.js / PostgreSQL / Docker 四种依赖缺失时，打印**下载地址与安装后放置位置**
  （新增 `Help-Download` 函数）。例如：Python 给 `python.org/downloads/windows` + 勾选 Add to PATH；
  PostgreSQL 给便携版（`enterprisedb.com/download-postgresql-binaries`，解压到 `.pgsql\extracted\pgsql\`）与
  官方安装包（`postgresql.org/download/windows`，加 `-PgRoot`）两种方案；Docker 给 `docker.com` + WSL2 步骤。
- **`README.md` 大幅精简**：688 行 → **229 行**（-67%，46.4 KB → 14.8 KB）。把重点修复表（16 行）、新增能力表（16 行）、
  修复实测表、实机验证记录（超长单元格）、已知边界、4 个技术栈表、核心概念代码块等冗长段落压缩为精简列表与一句话概述；
  细节统一指向 CHANGELOG / DEPLOY。保留全部事实信息（命令、URL、端口、版本、13 张截图、2 张架构图）。
- **`DEPLOY.md` §9** 扩展为「一键脚本（Windows / Linux）」，新增 `install.sh` / `stop.sh` 的用法与参数说明。

## [1.0.6] - 2026-10-17

### Added（新增）

- **正文生成编排阶段**（对标易标 OpenBidKit 逆向改造）：生成正文前先对全书大纲做一次"上游统一决策"
  （`services/generate/skills/content_plan_skill.py` → `plan_writing_focus`），把每节的写作要点
  （`writing_focus`）挂到大纲节点上，再让各章在该约束下写作。这是修"各章自说自话、上下文不通顺"的主要机制：
  易标用"上游一次决策 + 下游致盲"替代"让每章互相可见"。已编排过则复用落库结果，**失败绝不阻断正文生成**。
- **编排阶段进度可视化**：`plan_writing_focus` 新增 `on_progress(done, total)` 回调，
  `stream_generate_all_chapters` 据此下发 SSE `plan_progress` 事件，前端显示"正在编排写作计划 n/m"。
  编排在 `concurrency=1` 时是**串行**的（几十个一级子树，实测 ~30 秒/个，可达 30 分钟），
  期间没有任何正文产出，此前进度条长期停在 `0/N`，会被误判为"卡死"。
- **导出前分级门禁**：导出接口在出文档前按生成模式扫描全书，对**生成失败章节 / 编造内容 / 缺必要章节**
  分级拦截（409 + 阻断原因），`force=1` 可放行；生成模式取自项目配置 `selected_structure_type`，
  避免"技术标独立成册"被误判为"缺投标函"而永久 409。
- **模式化章节范围**（`services/generate/skills/chapter_attrs.py`、`norm_rules.py`）：
  `standalone-technical` 不再要求商务/资信类章节（投标函、法定代表人身份证明、开标一览表等），
  `norm_rules.scan_bid_document` 相应跳过该模式下的排除项。

### Fixed（修复）

- **正文上下文不通顺、各章自说自话**：生成提示词统一注入**全局口径台账**与项目事实
  （`build_chapter_system_prompt`），并对跨章承诺/金额/工期做一致性校验（`bid_consistency.py`）；
  口径不同且**主语不同**的（如"质保期结束后 2 年内供备件"本身是独立事实）**只提示、不自动改**，避免误改原文。
- **导出正文残留 Markdown 与模板样板句**：`content_cleaner.py` 新增确定性清洗 ——
  四级标题下拉（`1.2.3.4` 式）、索引样板句删除（"由 x.y 节阐述""本节不再展开""其余内容见后续章节"等）、
  重复维度片段去重；导出时对**已落库内容**再跑一次，旧内容重新导出同样会被清洗。
- **同一项目被重复起生成任务**：运行标记（`<项目>/.stages/generate/.running.json`）此前只在章节边界写入，
  而判定过期为 **240 秒**；上游限流（429）时单章"3 次重试 × 20 秒 + 流式等待"**实测可超过 240 秒**，
  运行标记会被误判为"进程已死"，此时再点一次就会真的新建并行任务。现改为**独立心跳协程**
  （`_gen_lock_heartbeat`，每 30 秒续写，与章节边界、订阅者数量均无关；任务结束即退出且不重建标记）。
- **前端"停止批量生成"服务端收不到停止信号**：原先只 abort 本地 fetch，只能靠"无订阅者超宽限期"兜底停，
  期间继续消耗 LLM 配额。现显式调用 `POST /api/generate/{id}/content/stop`。
  该补丁原以**产物形式**直接打在 `dist` 的 bundle 上（只存在于服务器，重建前端即丢失），
  本次已**回填源码** `GeneratePage.tsx` 并补了项目 ID 判空保护。
- **"标书五大结构"页内的章节数/页数文字**：删除模板卡片、卡片展开预览、应用结果面板共 4 处
  "N 章节 / 约 N 页 / ~N页"标注。`page_target` 仍保留在数据与接口中
  （`outline_gen_skill.py` 生成大纲时确实读它推算篇幅），**只去掉界面显示**，不影响字数预算。

### Changed（调整）

- **`docker/docker-compose.yml`**：补充生成相关环境变量映射 ——
  `BMP_GEN_CONCURRENCY`、`BMP_GEN_INTERVAL`、`BMP_GEN_DETACH_GRACE`、`BMP_SUBTREE_MAX`。

### Notes（说明）

- 本次同时补齐 [1.0.5] 与本次之间已提交但**未记录**的正文连贯性改造（提交 `eefc28d`，第 1–13 轮）。