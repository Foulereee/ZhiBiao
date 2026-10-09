# 贡献指南

感谢你愿意参与改进。本项目以 **AGPL-3.0-only** 发布，提交贡献即表示你同意以同一许可授权你的贡献。

## 提交前

1. 不要提交任何密钥、口令、真实 `.env`、生产数据或客户文档。
   - `.env` 已被忽略；请把新增配置写成 `.env.example` 中的**占位值**。
2. 保持改动聚焦：一个 PR 解决一件事，说明“改了什么、为什么、怎么验证”。
3. 代码风格：Python 遵循 `ruff`（行宽 120，`pyproject.toml` 已配置）；前端遵循既有 TypeScript/React 风格。

## 流程

```bash
# 1) Fork 本仓库并克隆你的 fork
git clone https://github.com/<你的用户名>/ZhiBiao.git
cd ZhiBiao

# 2) 建分支
git checkout -b fix/你的改动

# 3) 本地自检（可选但推荐）
ruff check .
python -m pytest -q

# 4) 提交并推送
git add -A
git commit -m "fix: 简述改动"
git push origin fix/你的改动
```

然后在 GitHub 上发起 Pull Request，并在描述中附上验证方式（命令与输出）。

## 许可与署名

- 上游项目：https://github.com/guangshu100/BidMaster-Pro（GNU Affero General Public License v3.0（AGPL-3.0）），版权归原作者所有。
- 本仓库的修改部分：Copyright (C) 2026 Foulereee。
- 提交贡献时请勿移除任何现有版权与许可声明，也不要新增与本项目冲突的许可条款。
