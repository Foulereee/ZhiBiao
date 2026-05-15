from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime


class GateKeeper:
    def __init__(self, projects_root: Path | str | None = None):
        self.projects_root = Path(projects_root or "./projects")

    def is_passed(self, project_id: str, stage: str) -> bool:
        gate_file = self.projects_root / project_id / ".stages" / stage / ".reviewed"
        return gate_file.exists()

    def mark_passed(self, project_id: str, stage: str, reviewer: str, notes: str = ""):
        gate_file = self.projects_root / project_id / ".stages" / stage / ".reviewed"
        try:
            gate_file.parent.mkdir(parents=True, exist_ok=True)
            gate_data = {
                "stage": stage,
                "reviewer": reviewer,
                "timestamp": datetime.now().isoformat(),
                "notes": notes,
            }
            gate_file.write_text(json.dumps(gate_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            raise RuntimeError(f"写入闸门文件失败: {e}") from e

    def reset(self, project_id: str, stage: str):
        gate_file = self.projects_root / project_id / ".stages" / stage / ".reviewed"
        if gate_file.exists():
            gate_file.unlink()

    def get_gate_info(self, project_id: str, stage: str) -> dict | None:
        gate_file = self.projects_root / project_id / ".stages" / stage / ".reviewed"
        if not gate_file.exists():
            return None
        try:
            return json.loads(gate_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            return None

    def list_passed_stages(self, project_id: str) -> list[str]:
        stages_dir = self.projects_root / project_id / ".stages"
        if not stages_dir.exists():
            return []
        return sorted([d.name for d in stages_dir.iterdir() if d.is_dir() and (d / ".reviewed").exists()])
