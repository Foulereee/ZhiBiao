# 第三方组件许可

本仓库自身以 **AGPL-3.0-only** 发布；下列第三方组件随本项目一起安装/分发，各自遵循其原始许可。
下表由本机已安装版本的实际元数据整理，供合规参考（版本号取生成时实测值）。

## 后端主要依赖

| 组件 | 版本 | 许可 |
|---|---|---|
| FastAPI | 0.141.1 | MIT |
| Uvicorn | 0.53.0 | BSD-3-Clause |
| SQLAlchemy | 2.0.54 | MIT |
| Alembic | 1.20.0 | MIT |
| asyncpg | 0.31.0 | Apache-2.0 |
| Pydantic | 2.13.5 | MIT |
| OpenAI Python SDK | 2.54.0 | Apache-2.0 |
| LiteLLM（已声明，运行路径未使用） | 1.101.0 | MIT |
| LangGraph（预留引擎） | 1.2.11 | MIT |
| LangChain-Core（未直接使用） | 1.6.3 | MIT |
| ChromaDB | 1.5.9 | Apache-2.0 |
| ONNX Runtime | 1.30.0 | MIT |
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

## 前端主要依赖

React 19 / React DOM 19 / React Router 7 / Zustand 5 / Vite 7 / TypeScript 5 / Tailwind CSS 4 /
Electron 41 / axios / lucide-react / react-markdown 等，均为 **MIT** 或 **Apache-2.0** 许可。

## 特别提示

1. **PyMuPDF** 采用 AGPL-3.0 与商业许可双授权。本项目整体已按 AGPL-3.0 发布，因此相容；
   若你打算以闭源商业方式分发，需自行购买 PyMuPDF 商业许可，或替换该组件。
2. **MinerU** 通过其云端 HTTP API 调用（`MINERU_MODE=cloud`），不作为库随本项目分发。
3. 完整条款以各组件包内 `LICENSE` 文件为准。
