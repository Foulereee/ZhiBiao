from __future__ import annotations

import logging
import os
import time

from pydantic_settings import BaseSettings
from pathlib import Path
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

# 每隔多久检查一次 .env 有没有被改动（秒）
_ENV_POLL_INTERVAL = 1.0


class Settings(BaseSettings):
    # ── 品牌信息：全站唯一来源，改 .env 里的 BMP_APP_NAME / BMP_APP_TAGLINE /
    #    BMP_APP_VERSION 即可整体改名（前端运行时拉取，无需重新构建前端）──
    app_name: str = "智标"
    app_tagline: str = "全流程智能招投标平台"
    app_version: str = "2.0"

    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000

    db_type: str = "postgresql"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/bidmaster"
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "root"
    mysql_database: str = "bidmaster"

    redis_url: str = "redis://localhost:6379/0"
    chroma_dir: str = "./chroma_db"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "bidmaster"
    projects_root: str = "./projects"

    llm_default_model: str = "deepseek/deepseek-chat"
    llm_api_key: str = ""
    llm_api_base: str = "https://api.deepseek.com"
    llm_fallback_modes: str = "ollama/qwen2.5"
    llm_max_retries: int = 3

    embedding_mode: str = "api"
    embedding_model: str = "text-embedding-v3"
    embedding_api_key: str = ""
    embedding_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    mineru_mode: str = "cloud"
    mineru_api_key: str = ""
    mineru_endpoint: str = "https://mineru.net/api/v4"
    mineru_timeout: int = 180
    mineru_model_version: str = "vlm"
    mineru_poll_interval: int = 5
    mineru_max_polls: int = 60

    tender_text_max_chars: int = 32000

    model_config = {"env_file": ".env", "env_prefix": "BMP_", "extra": "ignore"}

    def get_database_url(self) -> str:
        if self.db_type == "mysql":
            return (
                f"mysql+aiomysql://{quote_plus(self.mysql_user)}:{quote_plus(self.mysql_password)}"
                f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
                f"?charset=utf8mb4"
            )
        return self.database_url


_settings: Settings | None = None
_settings_stamp: tuple | None = None
_env_checked_at: float = 0.0


def env_file_path() -> str:
    """与 pydantic Settings 的 env_file=".env" 同一个位置（相对当前工作目录）。"""
    return os.path.abspath(".env")


def env_file_stamp() -> tuple | None:
    """(.env 的 mtime_ns, size, inode)；文件不存在返回 None。

    sig 里带上 inode：单文件 bind mount 的情况下，宿主机上任何「原子替换」式
    的写入（sed -i / ansible template / 编辑器的 rename 保存）都会新建一个
    inode，容器里挂载点仍然指着**旧 inode**。此时容器看到的内容会永远停在
    旧版本 —— GET /api/app-config/config 会把这里的 inode 报出来，
    和宿主机 `stat -c %i .env` 对一下就知道有没有踩到。
    """
    try:
        st = os.stat(env_file_path())
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _load_settings() -> Settings:
    global _settings, _settings_stamp, _env_checked_at
    _settings = Settings()
    _settings_stamp = env_file_stamp()
    _env_checked_at = time.monotonic()
    return _settings


def get_settings() -> Settings:
    """取配置；会自动感知 .env 的改动。

    为什么不再「启动读一次就完事」：
      Settings 缓存在模块级变量里，以前只有显式调用 reload_settings()
      （也就是走 PUT /api/app-config/config 那条路）才会重读 .env。
      结果就是 —— ssh 上去直接改 /opt/bidmaster/.env 对**已经跑着的进程毫无作用**，
      改了不生效，必须重建容器。这正是「.env 修改后并没有同步」的原因。

      现在每次取配置时顺手看一眼 .env 的 mtime/size/inode，变了就自动重新加载，
      最多每秒 stat 一次，开销可忽略。celery worker 也一并受益。
    """
    global _env_checked_at
    if _settings is None:
        return _load_settings()

    now = time.monotonic()
    if (now - _env_checked_at) >= _ENV_POLL_INTERVAL:
        _env_checked_at = now
        if env_file_stamp() != _settings_stamp:
            logger.info("[配置] 检测到 .env 已变更，自动重新加载")
            return _load_settings()
    return _settings


def reload_settings() -> Settings:
    """强制重新读取 .env。

    平台设置的「保存默认模型」会重写 .env,而 get_settings() 把 Settings 缓存在
    模块级变量里 —— 不重载就永远是进程启动时那份,改了等于没改。
    """
    return _load_settings()
