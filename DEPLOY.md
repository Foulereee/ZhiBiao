# 智标 部署手册（从下载到能用）

面向「刚下载 ZIP / 刚克隆」的人。两条路，任选一条：

- **方式一 · Docker 全量部署（推荐）**：一条命令起 PostgreSQL/Redis/MinIO/后端/Celery/nginx 站点，浏览器直接用，用户侧零安装。
- **方式二 · 本地开发**：不用 Docker（或只把基础设施放 Docker），自己起 uvicorn + vite。

> 遇到报错先翻 [§6 常见报错对照表](#6-常见报错对照表)，两个最常见的问题（`no configuration file provided` / `does not appear to be a Python project`）都在里面。
>
> **Windows 用户可以先试一键脚本**：`.\install.ps1`（自动判断 Docker / 本地，说明见 [§9](#9-一键脚本windows)；停服务用 `.\stop.ps1`）。

---

## 0. 先确认"仓库根目录"

GitHub「Download ZIP」解压后，Windows 上常见会**多套一层同名目录**：

```
D:\ZhiBiao-main\                 ← 如果这里除了一个同名文件夹什么都没有，就是多套了一层
    └── ZhiBiao-main\            ← 真正的仓库根目录
            pyproject.toml
            README.md
            docker\docker-compose.yml
```

**判据：下面这些必须在同一层**

```powershell
Get-ChildItem -Force | Where-Object { $_.Name -in 'pyproject.toml','README.md','docker','.env.example' }
# 正常输出：docker  .env.example  pyproject.toml  README.md
```

- 看不到 `pyproject.toml` → 你在上一层或下一层，`pip install -e .` 会报 "does not appear to be a Python project"。
- 连 `docker` 目录都没有 → 解压不完整，重新解压。

```powershell
cd D:\ZhiBiao-main\ZhiBiao-main      # 进到含 pyproject.toml 的那一层
```

> 本手册所有命令都假设 **当前目录 = 仓库根目录**。方式二的 `.env` 更是按"启动命令所在目录"查找，跑错目录会出现"改了配置不生效"。

---

## 1. 目录与文件地图

| 路径 | 作用 | 谁读它 |
| --- | --- | --- |
| `pyproject.toml` | Python 依赖与包定义（`pip install -e .` 的前提） | pip |
| `services/` | 后端：各业务域 router + check/format/generate 等 Skill | uvicorn |
| `core/` | 引擎层：LLM 网关、OCR、检索、Agent 框架、`settings.py`（读 `.env`） | 后端 |
| `packages/desktop/` | 前端（React + Vite，另含 Electron 外壳） | npm / nginx |
| `db/init_pg.sql` | PostgreSQL 基础表 + 默认角色/权限/Agent 数据，**postgres 容器首次启动自动执行**（幂等，可重复导入） | postgres 容器 |
| `db/init_mysql.sql` | MySQL 版本，仅 `--profile mysql` 时用 | mysql 容器 |
| `docker/docker-compose.yml` | 全部编排（**在 docker/ 目录下**，不在仓库根） | docker compose |
| `docker/Dockerfile.api` / `Dockerfile.web` | 后端镜像 / 前端构建+nginx 镜像 | docker compose |
| `docker/.env.docker.example` | **方式一的插值变量**模板（`LLM_API_KEY` 等，无 `BMP_` 前缀） | docker compose |
| `.env.example` → `.env` | **方式二的运行配置**（`BMP_*`）；方式一里它被挂载进容器 | pydantic / api 容器 |
| `templates/`、`skills/` | 文档模板与 Skill 定义，容器内只读挂载 | 后端 |
| `deploy/` | 迁移工具链 + 手册 + `seed_admin.py`（**建管理员账号**） | 手动执行 |
| `tools/font_normalize_evidence.py` | 字体归一化实测脚本（与部署无关） | 手动执行 |
| 卷 `pgdata` `redisdata` `miniodata` `projects` `chroma` `uploads` `celerybeat` | 数据持久化 | docker |

---

## 2. 方式一：Docker 全量部署（推荐）

### 2.1 前置条件

- Docker Engine 20.10+ 或 Docker Desktop，且带 compose v2：`docker compose version` 能输出版本号。
- 以下端口空闲（都可用变量改）：`8080` 站点、`8000` API、`5432` PG、`16379` Redis、`19000/19001` MinIO。
- 能出网：拉基础镜像 + 构建前端时 `npm install`。

### 2.2 为什么命令必须带 `-f docker/docker-compose.yml`

compose 文件在 `docker/` 里，而它内部所有相对路径都是**相对 compose 文件所在目录**解析的：

- 构建上下文：`context: ..` → 仓库根（Dockerfile 里再 `docker/Dockerfile.api`）
- 挂载：`../db/init_pg.sql`、`../skills`、`../templates`、`../.env`

所以在仓库根目录直接敲 `docker compose up -d` 一定失败，报：

```
no configuration file provided: not found
```

正确做法是显式指定文件（等价于把工程目录切到 `docker/`）。**不要**再加 `--project-directory .`，那会把 `../` 解析到仓库外。

### 2.2.1 Windows PowerShell 两个必看注意

1. **命令写在一行**。bash 的 `\` 续行在 PowerShell 里不是续行符，会被当成参数传给 docker，报
   `unknown docker command: "compose \"`。真要换行请用反引号：

   ```powershell
   docker compose -f docker/docker-compose.yml --env-file docker/.env.docker `
     --profile infra --profile web up -d --build
   ```

2. **先启动 Docker Desktop**。CLI 装了但 daemon 没起来时会报
   `failed to connect to the docker API at npipe:////./pipe/docker_engine ... is the daemon running?`。
   打开 Docker Desktop，等右下角托盘图标变为运行中再执行。

### 2.3 步骤

```powershell
# 1) 准备两个环境文件：一个给 compose 插值，一个挂进容器
Copy-Item .env.example .env                               # 必须存在！否则 Docker 会创建同名"目录"，容器报错
Copy-Item docker\.env.docker.example docker\.env.docker

# 2) 填 Key
notepad docker\.env.docker     # 必填 LLM_API_KEY；可选 EMBEDDING_API_KEY / MINERU_API_KEY / WEB_PORT
notepad .env                   # 可选：品牌名、调试开关；数据库/Redis 地址**不用改**（compose 内已指向容器服务）

# 3) 构建并启动（infra = PG/Redis/MinIO，web = nginx 站点）
docker compose -f docker/docker-compose.yml --env-file docker/.env.docker --profile infra --profile web up -d --build

# 4) 看状态、看日志（首次构建要几分钟；api 健康检查有 90s start_period，别急）
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml logs -f api

# 5) 全新空库要建管理员（会打印随机密码，只显示一次）
docker compose -f docker/docker-compose.yml exec api python deploy/seed_admin.py
#    也可指定：
#    docker compose -f docker/docker-compose.yml exec -e ADMIN_EMAIL=me@example.com -e ADMIN_PASSWORD='强密码' api python deploy/seed_admin.py

# 6) 打开站点
start http://localhost:8080         # 前端站点（nginx）
start http://localhost:8000/docs    # API 文档
```

**访问地址与端口**

| 服务 | 地址 | 变量 |
| --- | --- | --- |
| B/S 站点（前端） | http://localhost:8080 | `WEB_PORT` |
| API / Swagger | http://localhost:8000/docs | `API_PORT` |
| MinIO 控制台 | http://localhost:19001（minioadmin / minioadmin） | `MINIO_CONSOLE_PORT` |
| PostgreSQL | localhost:5432 | `POSTGRES_PORT` |
| Redis | localhost:16379 | `REDIS_EXTERNAL_PORT` |

**只起后端（直连外部 PG/Redis/MinIO）**：不加 `--profile` 就只启动 api + celery-worker + celery-beat：

```powershell
docker compose -f docker/docker-compose.yml --env-file docker/.env.docker up -d
```

**想用 MySQL 而不是 PostgreSQL**：加 `--profile mysql`，并把 `docker/.env.docker` 里 `BMP_DB_TYPE=mysql`。
注意 `db/init_pg.sql` 不会被 MySQL 执行，需自行导入 `db/init_mysql.sql`。

### 2.4 停止、升级与数据安全

```powershell
docker compose -f docker/docker-compose.yml stop       # 只停，容器和数据都在
docker compose -f docker/docker-compose.yml down       # 删容器/网络，卷保留 ✅
docker compose -f docker/docker-compose.yml down -v    # ⚠️ 连数据卷一起删 = 删库，慎用
```

升级到新版本：

```powershell
git pull      # 或重新解压 ZIP 覆盖源码（.env / docker\.env.docker 自己留好）
docker compose -f docker/docker-compose.yml --env-file docker/.env.docker --profile infra --profile web up -d --build
```

---

## 3. 方式二：本地开发（不想装 Docker 也能跑）

### 3.1 前置条件

| 组件 | 要求 | 说明 |
| --- | --- | --- |
| Python | 3.12+（本仓库在 **3.14.2** 实测通过） | 用于 `pip install -e .` |
| Node.js | 18+（实测 24.12.0 / npm 11.6.2） | 前端构建与 dev 服务 |
| PostgreSQL | 16+ | **必须**，ZIP 里**不含**数据库 |
| Redis | 7+ | **可选**，只有 Celery 异步任务需要 |
| Docker | 可选 | 只拿它起 PG/Redis/MinIO 最省事 |

> ⚠️ 仓库里的 `start-postgres.bat` / `stop-postgres.bat` 依赖 `.pgsql\` 免安装运行时，而 `.pgsql\` **不在仓库里**（已被 `.gitignore` 排除）。全新下载直接运行会提示找不到 `pg_ctl`。要用它，请自己放一份便携 PostgreSQL 到 `.pgsql\extracted\pgsql\`；否则用本机安装的 PostgreSQL 或 Docker。

### 3.2 步骤

```powershell
# 1) Python 依赖（必须在含 pyproject.toml 的仓库根目录）
python -m venv venv
.\venv\Scripts\Activate.ps1        # 提示"禁止运行脚本"时先执行：Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
python -m pip install -e .         # 实测：218 个包安装成功

# 2) 前端依赖
cd packages\desktop
npm install
cd ..\..

# 3) 基础设施（三选一）
#   a) 只用 Docker 起依赖（推荐）
docker compose -f docker/docker-compose.yml --profile infra up -d postgres redis minio
#   b) 本机已装 PostgreSQL/Redis：确认服务在跑（PG 监听 5432）
#   c) 有便携 PostgreSQL：放到 .pgsql\extracted\pgsql\ 后运行 .\start-postgres.bat

# 4) 建库 + 建表
createdb -U postgres bidmaster                    # 或： psql -U postgres -c "CREATE DATABASE bidmaster;"
psql -U postgres -d bidmaster -f db/init_pg.sql   # 基础表 + 默认角色/权限/Agent（幂等）
# 其余表由 init_db() → Base.metadata.create_all 补齐（实测共 22 张）
# ⚠️ 不要用 alembic upgrade head：alembic.ini 指向 db/migrations，而仓库里没有这个目录

# 5) 配置：.env 放在"启动命令所在目录"（pydantic 的 env_file=".env" 是相对 CWD 的）
Copy-Item .env.example .env
notepad .env
#   至少改：BMP_DATABASE_URL 里的主机/密码
#   必填：BMP_LLM_API_KEY（注意 BMP_LLM_API_BASE 必须与你 Key 的服务商一致）
#   生产环境：BMP_DEBUG=false

# 6) 启动后端（在仓库根目录执行）
python -m uvicorn services.main:app --reload --host 0.0.0.0 --port 8000
#    健康检查：http://localhost:8000/api/health  →  db_ready:true 才算就绪

# 7) 全新空库建管理员（另开终端，同样先激活 venv；系统不会自动建账号）
python deploy\seed_admin.py
#    指定账号密码：
#    $env:ADMIN_EMAIL='me@example.com'; $env:ADMIN_PASSWORD='强密码'; python deploy\seed_admin.py

# 8) 启动前端（另开终端）
cd packages\desktop
npm run dev
#    ⚠️ 端口是 vite.config.ts 写死的 15168（不是 5173）
#    打开 http://localhost:15168/ ；/api 默认反代到 http://localhost:8000
#    后端不在 8000 时：$env:VITE_API_TARGET='http://127.0.0.1:8010'; npm run dev

# 9) 可选：Celery（需要 Redis；Windows 用 solo 池）
python -m celery -A services.celery_app worker --loglevel=info --pool=solo

# 10) 可选：打包前端产物交给 nginx
npm run build       # 产物：packages/desktop/dist
```

---

## 4. 环境变量（两张表，别搞混）

系统里有**两套**变量名，这是最容易踩的坑：

- **方式一**：`docker/.env.docker` 用**无前缀**名（`LLM_API_KEY`），它只负责 compose 的 `${...}` 插值，再由 compose 注入成容器内的 `BMP_*`。
- **方式二**：根 `.env` 用 **`BMP_*`** 名，由 pydantic 直接读取。

### 4.1 方式一：`docker/.env.docker`

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_API_KEY` | （空） | **必填**，模型类功能总开关 |
| `LLM_MODEL` | `deepseek/deepseek-chat` | 默认模型 |
| `LLM_API_BASE` | `https://api.deepseek.com` | OpenAI 兼容端点，**须与 Key 同源** |
| `LLM_TIMEOUT` / `LLM_MAX_TOKENS` | `300` / `8192` | 单次调用超时与上限 |
| `LLM_CHECK_TIMEOUT` / `LLM_CHECK_MODEL` | `150` / （空） | 检查类 Skill 专用超时/模型（留空跟随默认） |
| `EMBEDDING_MODE` / `EMBEDDING_MODEL` / `EMBEDDING_API_KEY` / `EMBEDDING_API_BASE` | `api` / `text-embedding-v3` / （空） / dashscope | 知识库检索向量 |
| `MINERU_MODE` / `MINERU_API_KEY` / `MINERU_ENDPOINT` | `cloud` / （空） / `mineru.net/api/v4` | OCR |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_PORT` | `bidmaster` / `postgres` / `postgres` / `5432` | 容器内数据库 |
| `REDIS_HOST` / `REDIS_INTERNAL_PORT` / `REDIS_EXTERNAL_PORT` | `redis` / `6379` / `16379` | `REDIS_HOST` 改成外部 IP 即直连外部 Redis |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` / `MINIO_API_PORT` / `MINIO_CONSOLE_PORT` / `MINIO_BUCKET` | `minioadmin` / `minioadmin` / `19000` / `19001` / `bidmaster` | 对象存储 |
| `WEB_PORT` / `API_PORT` | `8080` / `8000` | 对外端口 |
| `UVICORN_WORKERS` | `1` | **保持 1**，见下 |
| `CELERY_CONCURRENCY` | `2` | Celery worker 并发 |
| `BMP_DB_TYPE` | `postgresql` | 用 MySQL 时改 `mysql` 并加 `--profile mysql` |
| `ALLOWED_ORIGINS` | （空） | 前后端分离部署时填前端来源（逗号分隔） |
| `BMP_DEBUG` | `false` | 调试开关 |

> ⚠️ **空默认值陷阱**：`LLM_API_KEY`、`EMBEDDING_API_KEY`、`MINERU_API_KEY`、`LLM_CHECK_MODEL`、`ALLOWED_ORIGINS`
> 的默认值是**空字符串**，compose 会把容器内的 `BMP_` 同名变量**覆盖成空串**。
> 所以方式一必须把 Key 填在 `docker/.env.docker`，只填根 `.env` 会被覆盖掉。

> ⚠️ **`UVICORN_WORKERS` 必须为 1**：登录会话保存在 `services/routers/auth.py` 的进程内字典 `_sessions` 中。
> 多 worker 时"登录"和后续请求可能落到不同进程，表现为随机退出登录 / 401。
> 要横向扩容，请先把会话迁到 Redis（或用带粘性会话的网关）。

### 4.2 方式二：根 `.env`（`BMP_*`）

| 变量 | 示例值 | 说明 |
| --- | --- | --- |
| `BMP_APP_NAME` / `BMP_APP_TAGLINE` / `BMP_APP_VERSION` | `智标` / 全流程智能招投标平台 / `2.0` | 全站品牌名的唯一来源（前端 + 后端 + 导出落款） |
| `BMP_DEBUG` | `true` | 生产改 `false` |
| `BMP_HOST` / `BMP_PORT` | `0.0.0.0` / `8000` | 监听地址与端口 |
| `BMP_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/bidmaster` | **方式二最常改的一项** |
| `BMP_REDIS_URL` | `redis://localhost:6379/0` | 连不上时会降级继续跑，只有异步任务受影响 |
| `BMP_CHROMA_DIR` / `BMP_PROJECTS_ROOT` | `./chroma_db` / `./projects` | **相对启动目录**，建议在仓库根目录启动 |
| `BMP_LLM_DEFAULT_MODEL` | `deepseek/deepseek-chat` | 默认模型 |
| `BMP_LLM_API_KEY` | （空） | **必填** |
| `BMP_LLM_API_BASE` | `https://token.sensenova.cn/v1` | **必须与你 Key 的服务商一致**，用错会 401/404 |
| `BMP_LLM_FALLBACK_MODES` | `deepseek-v4-flash` | 备用模式 |
| `BMP_EMBEDDING_*` | 见文件 | 向量检索 |
| `BMP_MINERU_*` | 见文件 | OCR |
| `BMP_TENDER_TEXT_MAX_CHARS` | `32000` | 招标文本截断长度 |

---

## 5. 首次登录与账号

- 系统**不会**自动创建管理员，`deploy/seed_admin.py` 是唯一入口（**幂等**，可重复执行）。
- 默认邮箱 `admin@bidmaster.pro`；不给 `ADMIN_PASSWORD` 时会随机生成 16 位并**只打印一次**。
- 它同时补齐 RBAC：实测 **27 个权限 / 4 个角色 / 1 个管理员**。
- 登录接口用**邮箱 + 密码**（`POST /api/auth/login`），站点登录页直接填即可。

---

## 6. 常见报错对照表

| 报错 | 原因 | 解决 |
| --- | --- | --- |
| `no configuration file provided: not found` | 在仓库根目录跑 compose，而编排文件在 `docker/` | 加 `-f docker/docker-compose.yml` |
| `unknown docker command: "compose \"` | 复制了 bash 的 `\` 续行；PowerShell 不认 `\`，它被当成参数传给 docker | 命令写在一行，或用反引号 `` ` `` 续行 |
| `failed to connect to the docker API at npipe:////./pipe/docker_engine ... is the daemon running?` | Docker Desktop 没启动（CLI 装了也一样） | 启动 Docker Desktop，等托盘图标就绪再执行 |
| `Error response from daemon: Docker Desktop is unable to start` | 本机未启用 WSL2 / Hyper-V（`wsl --status` 报未安装、`HypervisorPresent=False`） | 管理员 PowerShell 执行 `wsl --install`（或在「启用或关闭 Windows 功能」里勾选 **虚拟机平台 + 适用于 Linux 的 Windows 子系统**，专业版也可用 Hyper-V），**重启**后再启动 Docker Desktop |
| `ERROR: file:///D:/ZhiBiao-main does not appear to be a Python project: neither 'setup.py' nor 'pyproject.toml' found` | 当前目录不是仓库根目录（ZIP 解压多套一层） | `cd` 到含 `pyproject.toml` 的那层，见 [§0](#0-先确认仓库根目录) |
| 根目录出现一个名为 `.env` 的**文件夹** | 挂载 `../.env` 时源文件不存在，Docker 自动建了目录 | 停容器 → 删该目录 → `Copy-Item .env.example .env` → 重启 |
| `port is already allocated` / 8080 起不来 | 端口被占 | 改 `WEB_PORT` / `API_PORT` / `POSTGRES_PORT` |
| 反复被登出、随机 401 | `UVICORN_WORKERS` > 1（会话在进程内） | 保持为 `1` |
| `alembic upgrade head` 报 `Path doesn't exist: db\migrations` | 仓库没有迁移目录 | 用 `psql -f db/init_pg.sql`，其余表由启动时 `create_all` 建 |
| `psql -f db/init_pg.sql` 刷出一堆 `relation "projects"/"documents" does not exist` | **老版本 `init_pg.sql` 的缺陷**：`projects.tender_doc_id → documents(id)` 与 `documents.project_id → projects(id)` 互相引用，两张表都建不出来，后续 74 条语句级联报错 | 用本仓库当前的 `db/init_pg.sql`（已改为末尾补外键，空库导入 0 报错）；若用的是旧副本，这些报错**可以忽略**——启动 API 时 `init_db()` 会建全 22 张表 |
| `psql -f db/init_pg.sql` 报 `value too long for type character varying(36)` | **老版本 `init_pg.sql` 的缺陷**：角色-权限绑定用 `'前缀' \|\| p.code` 拼 `id`，最长的超过 36 字符 → 整条 `INSERT ... SELECT` 回滚，RBAC 绑定一行都写不进去 | 用本仓库当前的 `db/init_pg.sql`（改用 `uuid_generate_v4()::text`，实测 72 行绑定且可重复导入）；旧副本可忽略该报错——应用启动时 `rbac.py` 会自行补齐 |
| 双击 `start-postgres.bat` 一闪而过、数据库没起来（连 `.pgsql\pg.log` 都没生成） | **老版本 bat 的缺陷**：UTF-8 批处理里中途 `chcp 65001`，cmd 会按切换前的代码页重算偏移、丢掉其后所有行 | 用本仓库当前的 bat（已改为 ASCII-only、不带 chcp）；或绕过它直接 `.\.pgsql\extracted\pgsql\bin\pg_ctl.exe -D .pgsql\data -l .pgsql\pg.log -w start` |
| `stop-postgres.bat` 把同机其它 PostgreSQL 实例也停了 | 老版本兜底按进程名执行 `taskkill /IM postgres.exe /F` | 用当前版本：只结束本数据目录 `postmaster.pid` 中记录的 PID |
| api 容器长时间 `unhealthy` | 首次启动要等 DB + 首次构建慢 | `logs -f api` 看进度；健康检查有 90s 宽限 |
| PowerShell 无法激活 venv（禁止运行脚本） | 执行策略限制 | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| 前端 5173 打不开 | dev 端口是 **15168**（`vite.config.ts` 写死） | 访问 `http://localhost:15168/` |
| `start-postgres.bat` 报找不到 `pg_ctl` | `.pgsql\` 不在仓库里 | 用 Docker 或本机 PostgreSQL，见 [§3.1](#31-前置条件) |
| 模型类功能全报未配置 Key | 只填了根 `.env`，被 compose 的空默认值覆盖 | 把 `LLM_API_KEY` 填进 `docker/.env.docker` |
| 改了根 `.env` 但容器内不生效 | 容器优先用 compose 注入的环境变量 | 改 `docker/.env.docker`，或重建：`up -d --force-recreate` |

---

## 7. 本机实测记录（方式二）

Windows 11 + Python 3.14.2 + Node 24.12.0 + PostgreSQL 16，全新空目录 + 独立数据库：

| 环节 | 结果 |
| --- | --- |
| `pip install -e .` | ✅ 218 个包成功 |
| 数据库 | ✅ 空库导入 `db/init_pg.sql` **0 报错**（循环外键 + RBAC ID 超长两处缺陷已修）：17 张表、72 行角色-权限绑定、管理员已绑 admin 角色；再执行 `init_db()` 补到 **22 张表**，重复导入仍 0 报错且行数不变 |
| API | ✅ `/api/health` 200（`db_ready:true`）、`/api/stats` 200（46 个 Skill）、`/openapi.json` 200 |
| 鉴权 | ✅ 登录返回 64 位 token；带 token 200，不带 token 全 401 |
| 业务写入 | ✅ 建项目 → 回读 → 删除 |
| `seed_admin.py` | ✅ 27 权限 / 4 角色 / 管理员 |
| 前端 | ✅ `npm run build` 16.4s 通过；`npm run dev` 起在 15168 |
| Celery | ✅ worker `celery@R ready.`，注册 3 个任务 |
| `install.ps1` 一键脚本 | ✅ 干净副本 + Windows PowerShell 5.1：依赖 → 起便携 PG → 建库 → `init_pg.sql` **0 报错** → `init_db()` **22 张表** → 建管理员 → API 与前端就绪；`stop.ps1` 释放 8000/15168 |

方式一未能在本机跑通：验证机装了 Docker Desktop（CLI 29.8.2 / compose v5.5.1），
`docker compose -f docker/docker-compose.yml --env-file docker/.env.docker.example config --quiet` **校验通过（exit 0）**，
但本机 **WSL2 未安装**（`wsl --status` 报未安装）且 `HypervisorPresent=False`，Docker 引擎起不来：

```
Error response from daemon: Docker Desktop is unable to start
```

启用 WSL2/Hyper-V 并重启后即可实机验证；线上生产正是这套 compose 在跑（HTTP 200），可作为长期运行证据。

---

## 8. 已知边界

1. 登录会话在**进程内**，`UVICORN_WORKERS` 必须为 1（扩容需先迁 Redis）。
2. `alembic.ini` 指向的 `db/migrations` 不存在，`alembic upgrade head` 必然失败。
3. 前端 `renderer/src/assets/logo.png` 有 2.45 MB 且进 bundle，主 chunk 1.7 MB（建议压缩 + 按路由拆包）。
4. `/api/projects` 这类以 `/` 结尾的路由会 307 跳转，客户端需带尾斜杠。
5. `core/agent_engine/`（LangGraph）为预留能力，未接入运行路径。
6. 导出 PDF 若在缺少中文字体的环境运行，字体会被替换（交付 docx 或用装了字体的镜像）。

---

## 9. 一键脚本（Windows）

仓库根目录自带两个 PowerShell 脚本（**无需管理员权限**）：

| 脚本 | 作用 |
| --- | --- |
| `install.ps1` | 一键安装/部署：目录校验 → 后端/前端依赖 → 数据库 → 建库建表 → 生成 `.env` → 建管理员 → 起服务 → 健康检查 |
| `stop.ps1` | 停本地服务（按端口定位进程）；`-Docker` 停容器；`-WithPg` 连便携 PostgreSQL 一起停 |

### 9.1 最简用法

```powershell
cd <仓库根目录>          # 含 pyproject.toml 的那一层
.\install.ps1            # 自动判断：Docker 引擎可用就走方式一，否则走方式二
.\stop.ps1               # 停掉本地方式二启动的 API 与前端
```

### 9.2 常用参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `-Mode auto\|docker\|local` | `auto` | 强制走哪条路；`auto` 下 Docker 不可用会自动回落本地 |
| `-LlmApiKey` / `-LlmApiBase` | 空 | 写入 `.env`（本地）或 `docker/.env.docker`（Docker）；不传则交互式询问 |
| `-AdminEmail` / `-AdminPassword` | `admin@bidmaster.pro` / 随机 | 交给 `deploy/seed_admin.py`；不给密码则打印一次随机密码 |
| `-DbName` / `-PgUser` / `-PgPassword` / `-PgPort` | `bidmaster` / `postgres` / `postgres` / `5432` | 本地模式建库用 |
| `-ApiPort` / `-SitePort` / `-DevPort` | `8000` / `8080` / `15168` | API / Docker 站点 / vite dev 端口 |
| `-PgRoot` | 空 | 便携 PostgreSQL 根目录（含 `extracted\pgsql\bin` 与 `data`）；不传则用 `<仓库>\.pgsql` |
| `-SkipFrontend` | 关 | 不装前端依赖 |
| `-NoStart` | 关 | 只准备环境，不启动服务 |
| `-Force` | 关 | 重建已存在的 `.env` / `docker\.env.docker`（会先备份） |
| `-Yes` | 关 | 非交互（不询问 API Key） |

### 9.3 它做了什么（对应上面的手工步骤）

**方式二（本地）**：检查 Python 版本 → `venv` + `pip install -e .` → `npm install` →
检查/启动 PostgreSQL（依次找 `<仓库>\.pgsql`、`-PgRoot`、PATH 里的 `pg_ctl`；都没有就给出三种获取方式）→
建库 + 导入 `db/init_pg.sql`（幂等，容忍其中循环外键相关的报错）→ 执行 `init_db()` 补全 **22 张表** →
生成 `.env`（UTF-8 **无 BOM**，避免 pydantic 把 BOM 当进第一个键名）→
`deploy/seed_admin.py` 建管理员 → 后台启动 uvicorn 与 `npm run dev` → 轮询 `/api/health` 与首页。

**方式一（Docker）**：`docker info` 探活（失败会说明 Docker Desktop / WSL2-Hyper-V 的原因）→
生成根 `.env` 与 `docker\.env.docker` → 一条
`docker compose -f docker/docker-compose.yml --env-file docker/.env.docker --profile infra --profile web up -d --build`
→ 等待 `/api/health`（最多 8 分钟）→ 容器内执行 `seed_admin.py` → 打印站点与 API 地址。

### 9.4 日志与停止

```
logs\install-<时间戳>.log        脚本全过程
logs\api.out.log / api.err.log   本地后端
logs\web.out.log / web.err.log   本地前端
logs\postgres.log                便携 PostgreSQL（由 pg_ctl 启动时）
```

```powershell
.\stop.ps1                  # 停 API + 前端
.\stop.ps1 -WithPg          # 再停便携 PostgreSQL
.\stop.ps1 -Docker          # Docker：compose stop（容器与数据卷都保留）
.\stop.ps1 -Docker -Remove  # Docker：删容器与网络（数据卷仍保留；再加 -Volumes 才会删数据）
```

> Docker Desktop 未启用 WSL2/Hyper-V 时，`install.ps1 -Mode auto` 会自动改为本地模式，不会卡在半路。