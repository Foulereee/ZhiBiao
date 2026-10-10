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
