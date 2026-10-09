# 变更记录

本文件记录本仓库（https://github.com/Foulereee/zhinbiao-pro）相对上游 https://github.com/guangshu100/BidMaster-Pro 的修改，便于下游使用者判断差异。

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

### Security（安全）

- 仓库内不含任何生产密钥：`.env` 被 `.gitignore` 忽略且从未进入本仓库历史；
  本机私有的运维记录、迁移包、构建产物均已加入忽略清单。
- ⚠️ 若你曾把真实 Key 写进 `*.example` 文件并提交，**请立即到服务商控制台轮换该 Key**。
