import json
import os
from datetime import datetime
from pathlib import Path

from core.agent_framework.types import AgentResult


class CheckpointManager:
    """检查点管理——部分结果持久化，支持断点续跑。

    存储方式：JSON 文件（原子写入，支持多进程安全）。
    """

    def __init__(self, storage_dir: str = "./checkpoints"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, project_id: str, step_id: str, pipeline_type: str,
                   completed_steps: list, step_results: dict, errors: list,
                   retry_counts: dict):
        """保存检查点——使用原子写入避免并发写损坏"""
        step_keys = {
            step: list(data.keys())[:3] if isinstance(data, dict) else "ok"
            for step, data in step_results.items()
        }
        checkpoint = {
            "project_id": project_id,
            "pipeline_type": pipeline_type,
            "completed_steps": completed_steps,
            "current_step": step_id,
            "step_results_keys": step_keys,
            "errors": errors[-10:],
            "retry_counts": retry_counts,
            "status": "in_progress",
            "updated_at": datetime.now().isoformat(),
        }
        path = self.storage_dir / f"{project_id}.json"
        tmp_path = self.storage_dir / f"{project_id}.tmp"
        tmp_path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)  # 原子重命名

    async def load_latest(self, project_id: str) -> dict | None:
        path = self.storage_dir / f"{project_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    async def resume_from_checkpoint(self, project_id: str,
                                     resume_fn: callable) -> AgentResult:
        checkpoint = await self.load_latest(project_id)
        if not checkpoint:
            return AgentResult(success=False, error="无检查点可恢复")
        return await resume_fn(project_id, checkpoint)