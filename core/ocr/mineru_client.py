from __future__ import annotations

import asyncio
import logging
import os
import zipfile
from abc import ABC, abstractmethod
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import httpx

from core.settings import get_settings

logger = logging.getLogger(__name__)


class MinerUError(Exception):
    pass


class MinerUClient(ABC):
    """MinerU OCR 抽象基类，定义统一的 submit/query 协议。"""

    mode: str = ""

    @abstractmethod
    async def submit(self, file_path: str, **options: Any) -> str:
        """提交文件抽取任务，返回任务标识。"""

    @abstractmethod
    async def query(self, task_id: str) -> dict[str, Any]:
        """查询任务状态。返回 dict(state/data/error)。"""

    @abstractmethod
    async def fetch_result(self, task_id: str) -> dict[str, Any]:
        """拉取并解析任务结果为结构化字典。"""

    async def extract(
        self,
        file_path: str,
        on_progress: Callable[[str, dict], None] | None = None,
    ) -> dict[str, Any]:
        """提交并轮询至完成，返回抽取结果。"""
        if not Path(file_path).exists():
            raise MinerUError(f"文件不存在: {file_path}")

        settings = get_settings()
        task_id = await self.submit(file_path)
        on_progress and on_progress("submitted", {"task_id": task_id})

        for i in range(settings.mineru_max_polls):
            await asyncio.sleep(settings.mineru_poll_interval)
            try:
                status = await self.query(task_id)
            except MinerUError as e:
                on_progress and on_progress("error", {"task_id": task_id, "error": str(e)})
                raise
            state = status.get("state")
            on_progress and on_progress("polling", {
                "task_id": task_id,
                "state": state,
                "poll": i + 1,
            })
            if state == "done":
                return await self.fetch_result(task_id)
            if state == "failed":
                raise MinerUError(status.get("error") or "MinerU 抽取失败")
        raise MinerUError(f"MinerU 任务超时: {task_id}")


class CloudMinerUClient(MinerUClient):
    """MinerU 官方云端 SaaS 实现（https://mineru.net/api/v4）。

    流程:
      1. POST /file-urls/batch  → 上传地址 + batch_id
      2. PUT 上传文件
      3. POST /extract/task     → 提交抽取任务（返回 task_id 或 batch_id）
      4. GET  /extract/task/{task_id} 轮询结果
      5. 下载 zip 解析 markdown
    """

    mode = "cloud"

    def __init__(self, api_key: str, endpoint: str = "https://mineru.net/api/v4", timeout: int = 180):
        if not api_key:
            raise MinerUError("MinerU 云端模式需要配置 API Key")
        self.api_key = api_key
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def submit(self, file_path: str, **options: Any) -> str:
        file_path_p = Path(file_path)
        file_size = file_path_p.stat().st_size
        if file_size > 200 * 1024 * 1024:
            raise MinerUError(f"文件超过 200MB 上限: {file_size} bytes")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            apply_formula = options.get("enable_formula", True)
            apply_table = options.get("enable_table", True)
            language = options.get("language", "ch")
            resp = await client.post(
                f"{self.endpoint}/file-urls/batch",
                headers=self._headers(),
                data={
                    "enable_formula": str(apply_formula).lower(),
                    "enable_table": str(apply_table).lower(),
                    "language": language,
                },
                files={"files": (file_path_p.name, open(file_path, "rb"), "application/octet-stream")},
            )
            if resp.status_code not in (200, 201):
                raise MinerUError(f"申请上传地址失败: HTTP {resp.status_code} {resp.text[:300]}")
            data = resp.json()
            if data.get("code") not in (0, 200):
                raise MinerUError(f"申请上传地址业务错误: {data.get('msg') or data}")

            result = data.get("data") or {}
            batch_id = result.get("batch_id")
            urls = result.get("file_urls") or []
            if not batch_id or not urls:
                raise MinerUError(f"申请上传地址返回缺少 batch_id/file_urls: {data}")
            upload_url = urls[0]
            with open(file_path, "rb") as f:
                put_resp = await client.put(
                    upload_url,
                    content=f.read(),
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=self.timeout,
                )
            if put_resp.status_code not in (200, 201, 204):
                raise MinerUError(f"文件上传失败: HTTP {put_resp.status_code} {put_resp.text[:300]}")

            task_resp = await client.post(
                f"{self.endpoint}/extract/task",
                headers=self._headers(),
                json={
                    "batch_id": batch_id,
                    "enable_formula": apply_formula,
                    "enable_table": apply_table,
                    "language": language,
                },
            )
            if task_resp.status_code not in (200, 201):
                raise MinerUError(f"提交抽取任务失败: HTTP {task_resp.status_code} {task_resp.text[:300]}")
            task_data = task_resp.json()
            if task_data.get("code") not in (0, 200):
                raise MinerUError(f"提交抽取任务业务错误: {task_data.get('msg') or task_data}")
            task_id = (task_data.get("data") or {}).get("task_id") or batch_id
            return str(task_id)

    async def query(self, task_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.endpoint}/extract/task/{task_id}",
                headers=self._headers(),
            )
            if resp.status_code != 200:
                raise MinerUError(f"查询任务失败: HTTP {resp.status_code} {resp.text[:300]}")
            data = resp.json()
            if data.get("code") not in (0, 200):
                raise MinerUError(f"查询任务业务错误: {data.get('msg') or data}")
            state = ((data.get("data") or {}).get("state") or "").lower()
            mapped = {
                "pending": "pending",
                "running": "running",
                "processing": "running",
                "done": "done",
                "success": "done",
                "completed": "done",
                "failed": "failed",
                "error": "failed",
            }.get(state, "running")
            result = {
                "state": mapped,
                "raw_state": state,
                "data": data.get("data") or {},
                "error": data.get("msg") if mapped == "failed" else None,
            }
            return result

    async def fetch_result(self, task_id: str) -> dict[str, Any]:
        status = await self.query(task_id)
        payload = status.get("data") or {}
        zip_url = (
            payload.get("full_md_link")
            or payload.get("md_link")
            or payload.get("zip_url")
            or payload.get("result_url")
        )
        if not zip_url:
            raise MinerUError("任务完成但未返回结果下载链接")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(zip_url, follow_redirects=True)
            if resp.status_code != 200:
                raise MinerUError(f"下载结果失败: HTTP {resp.status_code}")
            content = resp.content
        return _parse_zip_result(content)


class SelfHostedMinerUClient(MinerUClient):
    """自部署（OpenAPI 兼容）MinerU 实现。默认 POST /predict。

    期望的协议:
      - POST {endpoint}/predict  multipart file=... → {"task_id": "..."}
      - GET  {endpoint}/tasks/{task_id}  → {"state": "running|done|failed", "data": {...}}
      - 直接在 GET 响应中返回 markdown（data.markdown）或 result_url
    """

    mode = "self_hosted"

    def __init__(self, endpoint: str, api_key: str = "", timeout: int = 180):
        if not endpoint:
            raise MinerUError("自部署模式需要配置 endpoint")
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def submit(self, file_path: str, **options: Any) -> str:
        file_path_p = Path(file_path)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.endpoint}/predict",
                headers=self._headers(),
                files={"file": (file_path_p.name, open(file_path, "rb"), "application/octet-stream")},
                data={
                    k: str(v).lower() if isinstance(v, bool) else str(v)
                    for k, v in options.items()
                } or None,
            )
            if resp.status_code not in (200, 201, 202):
                raise MinerUError(f"提交任务失败: HTTP {resp.status_code} {resp.text[:300]}")
            data = resp.json()
            task_id = data.get("task_id") or data.get("id")
            if not task_id:
                raise MinerUError(f"自部署 MinerU 响应缺少 task_id: {data}")
            return str(task_id)

    async def query(self, task_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.endpoint}/tasks/{task_id}",
                headers=self._headers(),
            )
            if resp.status_code != 200:
                raise MinerUError(f"查询任务失败: HTTP {resp.status_code} {resp.text[:300]}")
            data = resp.json()
            state = (data.get("state") or data.get("status") or "running").lower()
            mapped = {
                "pending": "pending",
                "queued": "pending",
                "running": "running",
                "processing": "running",
                "done": "done",
                "success": "done",
                "completed": "done",
                "finished": "done",
                "failed": "failed",
                "error": "failed",
            }.get(state, "running")
            return {
                "state": mapped,
                "raw_state": state,
                "data": data,
                "error": data.get("error") if mapped == "failed" else None,
            }

    async def fetch_result(self, task_id: str) -> dict[str, Any]:
        status = await self.query(task_id)
        payload = status.get("data") or {}
        if "markdown" in payload:
            return {"markdown": payload["markdown"], "meta": payload.get("meta", {}), "source": task_id}
        result_url = payload.get("result_url") or payload.get("zip_url")
        if result_url:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(result_url, follow_redirects=True)
                if resp.status_code != 200:
                    raise MinerUError(f"下载自部署结果失败: HTTP {resp.status_code}")
                if result_url.endswith(".zip"):
                    return _parse_zip_result(resp.content)
                return {"markdown": resp.text, "meta": {}, "source": task_id}
        raise MinerUError("自部署 MinerU 任务完成但未返回 markdown/result_url")


def _parse_zip_result(content: bytes) -> dict[str, Any]:
    """解析 MinerU 返回的 zip，提取 markdown 与图片占位。"""
    markdown = ""
    images: dict[str, str] = {}
    try:
        with zipfile.ZipFile(BytesIO(content)) as zf:
            md_candidate = None
            for name in zf.namelist():
                if name.endswith(".md") and not name.startswith("images/"):
                    md_candidate = name
                    break
            if not md_candidate:
                for name in zf.namelist():
                    if name.endswith(".md"):
                        md_candidate = name
                        break
            if md_candidate:
                markdown = zf.read(md_candidate).decode("utf-8", errors="ignore")
            for name in zf.namelist():
                if name.startswith("images/") and not name.endswith("/"):
                    images[name] = f"zip://{name}"
    except zipfile.BadZipFile as e:
        if content[:4] == b"%PDF":
            return {"markdown": "", "meta": {"warning": "返回的是 PDF，无法解析为 markdown"}, "source": "zip"}
        raise MinerUError(f"解析 MinerU 结果 zip 失败: {e}")
    return {"markdown": markdown, "images": images, "meta": {}, "source": "zip"}


_client_cache: dict[str, MinerUClient] = {}


def get_mineru_client(
    mode: str | None = None,
    api_key: str | None = None,
    endpoint: str | None = None,
    timeout: int | None = None,
) -> MinerUClient:
    """根据当前配置或覆盖参数构造 MinerU 客户端（单例缓存）。"""
    settings = get_settings()
    actual_mode = (mode or settings.mineru_mode or "cloud").lower()
    actual_key = api_key if api_key is not None else settings.mineru_api_key
    actual_endpoint = endpoint or settings.mineru_endpoint
    actual_timeout = timeout or settings.mineru_timeout
    cache_key = f"{actual_mode}|{actual_key}|{actual_endpoint}|{actual_timeout}"
    if cache_key in _client_cache:
        return _client_cache[cache_key]
    if actual_mode == "self_hosted" or actual_mode == "self-hosted" or actual_mode == "selfhosted":
        client = SelfHostedMinerUClient(endpoint=actual_endpoint, api_key=actual_key, timeout=actual_timeout)
    else:
        client = CloudMinerUClient(api_key=actual_key, endpoint=actual_endpoint, timeout=actual_timeout)
    _client_cache[cache_key] = client
    return client


def reset_mineru_client_cache() -> None:
    """重置客户端缓存（用于配置变更后立即生效）。"""
    _client_cache.clear()
