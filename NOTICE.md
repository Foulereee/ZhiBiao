# 来源与修改说明（NOTICE）

本文件依据 **AGPL-3.0 第 5 条**（保留版权声明、标注修改）编写，供使用者与下游分发者查阅。

## 1. 上游项目与版权

| 项目 | 内容 |
|---|---|
| 上游仓库 | https://github.com/guangshu100/BidMaster-Pro |
| 上游作者 | guangshu100（chenjinyong / cjinyong） |
| 上游许可 | **GNU Affero General Public License v3.0（AGPL-3.0）**，完整条款见本仓库 [LICENSE](LICENSE) |
| 上游版权 | `Copyright (C) 智标团队 / guangshu100` |

> **关于「README 写 MIT、LICENSE 却是 AGPL」的说明**
>
> 上游 README 曾把许可证写成 “MIT”，但其仓库内 `LICENSE` 文件是 **AGPL-3.0 全文（661 行）**，
> GitHub 对该仓库的识别结果同样是 **AGPL-3.0**。二者冲突时，**以实际授权文本 `LICENSE` 为准**，
> 不能依据 README 里的一句话把 AGPL 代码改成 MIT 发布。
> 因此本仓库**整体按 AGPL-3.0 发布**，未采用 MIT。

## 2. 本仓库

| 项目 | 内容 |
|---|---|
| 仓库 | https://github.com/Foulereee/zhinbiao-pro |
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
| `deploy/` | 迁移与运维脚本（导出/导入/重建校验/管理员初始化 + 两份手册） |

完整变更请见 [CHANGELOG.md](CHANGELOG.md)，逐文件差异请见 git 历史。

## 4. AGPL-3.0 第 13 条（网络服务）义务

本程序以 **B/S（浏览器访问）** 形态通过网络对外提供服务。依据 AGPL-3.0 第 13 条，
**任何通过网络与本程序交互的用户，都有权获取其对应的完整源代码**。
本仓库即为该源代码，任何部署者都应当：

1. 在服务的“关于/帮助”页面（或等价位置）提供指向本仓库的源码链接；或
2. 提供书面要约，承诺向任何第三方提供对应源代码。

若你在此基础上做了修改并对外提供服务，你同样需要公开你的修改（AGPL-3.0 §5、§13）。

## 5. 第三方组件

主要第三方依赖及其许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
