# 来源与修改说明（NOTICE）

本文件依据 **AGPL-3.0 第 5 条**（保留版权声明、标注修改）编写，供使用者与下游分发者查阅。

## 1. 上游项目与版权

| 项目 | 内容 |
|---|---|
| 上游仓库 | https://github.com/guangshu100/BidMaster-Pro |
| 上游作者 | guangshu100 |
| 上游许可 | **GNU Affero General Public License v3.0（AGPL-3.0）**，完整条款见本仓库 [LICENSE](LICENSE) |
| 上游版权 | `Copyright (C) 智标团队 / guangshu100` |

## 2. 本仓库

| 项目 | 内容 |
|---|---|
| 仓库 | https://github.com/Foulereee/ZhiBiao |
| 维护者 | Foulereee <1817558146@qq.com> |
| 许可 | **GNU Affero General Public License v3.0（AGPL-3.0）**（整体，包含对上游代码的修改部分） |

## 3. 修改说明（AGPL-3.0 §5(a)：标注修改内容与日期）

本仓库基于上游 `main` 分支提交 `cc89d90` 继续开发，自 **2026-10-05** 起由 Foulereee 修改并投入生产使用
（80 端口纯 B/S 部署：nginx 站点 + API + PostgreSQL/Redis）。改动规模：**83 个文件、+6975 / −1153 行**，
主要集中在：

| 模块 | 文件数 | 修改内容概述 |
|---|---|---|
| `services/` | 46 | 业务路由与 Skill 修复；检查/生成/排版链路稳定性；认证与鉴权补齐 |
| `packages/desktop/` | 16 | 前端页面与状态管理修复（工作台、检查、排版、设置等） |
| `core/` | 7 | LLM Gateway、Agent 框架、文档解析器修复 |
| `docker/` | 5 | 镜像构建、compose、entrypoint、nginx 配置修复 |
| `skills/` | 4 | Skill 定义（SKILL.md）修订 |
| 其他 | 5 | `start.py`、`pyproject.toml`、`.gitignore`、`README.md`、`.env.example` |

新增文件（上游没有）：

| 文件 | 用途 |
|---|---|
| `core/env_store.py` | 无损修改宿主 `.env`（保留注释与分组），供品牌/模型配置接口落盘 |
| `services/routers/app_config.py` | 品牌配置接口（`/api/app-config`，改名热生效） |
| `services/format/font_utils.py` | docx 字体规范化（解决导出后字体/封面异常） |
| `deploy/` | `seed_admin.py`（空库建管理员，幂等）。运维脚本与迁移实录手册属私有运维资产，**不随公开仓库发布** |

完整变更请见 [CHANGELOG.md](CHANGELOG.md)，逐文件差异请见 git 历史。

## 4. AGPL-3.0 第 13 条（网络服务）义务

本程序以 **B/S（浏览器访问）** 形态通过网络对外提供服务。依据 AGPL-3.0 第 13 条，
**任何通过网络与本程序交互的用户，都有权获取其对应的完整源代码**。
本仓库即为该源代码，任何部署者都应当：

1. 在服务的“关于/帮助”页面（或等价位置）提供指向本仓库的源码链接；或
2. 提供书面要约，承诺向任何第三方提供对应源代码。

若你在此基础上做了修改并对外提供服务，你同样需要公开你的修改（AGPL-3.0 §5、§13）。

## 5. 第三方组件

> 本节原为独立文件 `THIRD_PARTY_NOTICES.md`，本轮已合并到这里（减少重复文档）。
> 版本号取整理时的实测值；本仓库自身以 **AGPL-3.0-only** 发布，下列组件各自遵循其原始许可。

**后端主要依赖**

| 组件 | 版本 | 许可 |
|---|---|---|
| FastAPI | 0.141.1 | MIT |
| Uvicorn | 0.53.0 | BSD-3-Clause |
| SQLAlchemy | 2.0.54 | MIT |
| asyncpg | 0.31.0 | Apache-2.0 |
| Pydantic | 2.13.5 | MIT |
| OpenAI Python SDK | 2.54.0 | Apache-2.0 |
| LiteLLM（已声明，运行路径未使用） | 1.101.0 | MIT |
| LangGraph（编排层预留、`gate_keeper` 已接入） | 1.2.11 | MIT |
| LangChain-Core（未直接使用） | 1.6.3 | MIT |
| ChromaDB | 1.5.9 | Apache-2.0 |
| PyMuPDF | 1.28.2 | **AGPL-3.0 或商业许可（双许可）** |
| pdfplumber | 0.11.10 | MIT |
| python-docx | 1.2.0 | MIT |
| mammoth | 1.12.2 | BSD-2-Clause |
| beautifulsoup4 | 4.15.0 | MIT |
| feedparser | 6.0.14 | BSD-2-Clause |
| requests | 2.34.2 | Apache-2.0 |
| Celery | 5.6.3 | BSD-3-Clause |
| redis-py | 6.4.0 | MIT |
| MinIO Python SDK | 7.2.20 | Apache-2.0 |
| httpx | 0.28.1 | BSD-3-Clause |
| tenacity | 9.1.4 | Apache-2.0 |
| loguru | 0.7.3 | MIT |
| jieba | 0.42.1 | MIT |
| openpyxl | 3.1.5 | MIT |
| Jinja2 | 3.1.6 | BSD-3-Clause |
| WeasyPrint | 70.0 | BSD-3-Clause |
| FastMCP | 4.0.4 | Apache-2.0 |
| Apprise | 1.13.1 | BSD-2-Clause |
| PyYAML | 6.0.3 | MIT |

**前端主要依赖**：React 19 / React DOM 19 / React Router 7 / Zustand 5 / Vite 7 / TypeScript 5 /
Tailwind CSS 4 / Electron 41 / axios / lucide-react / react-markdown 等，均为 **MIT** 或 **Apache-2.0** 许可。

**特别提示**

1. **PyMuPDF** 采用 AGPL-3.0 与商业许可双授权。本项目整体已按 AGPL-3.0 发布，因此相容；
   若你打算以闭源商业方式分发，需自行购买 PyMuPDF 商业许可，或替换该组件。
2. **MinerU** 通过其云端 HTTP API 调用（`MINERU_MODE=cloud`），不作为库随本项目分发。
3. 完整条款以各组件包内 `LICENSE` 文件为准。
4. 历史版本曾依赖 **Alembic** 与 **ONNX Runtime**（均 MIT）；因仓库不含数据库迁移、且唯一使用
   ONNX 的模块证明无任何调用方，本轮已连同该模块一并移除，故不再列出。
