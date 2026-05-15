from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

from core.skill_engine.base import Skill
from core.exceptions import SkillNotFoundError


class SkillLoader:
    def __init__(self, skills_dir: Path | str):
        self.skills_dir = Path(skills_dir)
        self._loaded_skills: dict[str, dict] = {}

    def load_all(self) -> dict[str, dict]:
        if not self.skills_dir.exists():
            return {}
        for category_dir in self.skills_dir.iterdir():
            if not category_dir.is_dir():
                continue
            for skill_dir in category_dir.iterdir():
                if not skill_dir.is_dir():
                    continue
                skill_md = skill_dir / "SKILL.md"
                skill_py = skill_dir / "skill.py"
                if skill_md.exists() or skill_py.exists():
                    meta = self._parse_skill_md(skill_md) if skill_md.exists() else {"name": skill_dir.name}
                    self._loaded_skills[meta.get("name", skill_dir.name)] = {
                        "meta": meta,
                        "dir": skill_dir,
                        "module": skill_py,
                    }
        return self._loaded_skills

    def get_skill_class(self, name: str) -> type[Skill]:
        info = self._loaded_skills.get(name)
        if not info:
            raise SkillNotFoundError(f"Skill '{name}' 未找到")
        module_path = info.get("module")
        if not module_path or not Path(module_path).exists():
            raise SkillNotFoundError(f"Skill '{name}' 模块文件不存在")
        spec = importlib.util.spec_from_file_location(f"skills.{name}", str(module_path))
        if not spec or not spec.loader:
            raise SkillNotFoundError(f"Skill '{name}' 模块加载失败")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, Skill) and attr is not Skill:
                return attr
        raise SkillNotFoundError(f"Skill '{name}' 中未找到Skill子类")

    def _parse_skill_md(self, path: Path) -> dict:
        content = path.read_text(encoding="utf-8")
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    return yaml.safe_load(parts[1]) or {}
                except yaml.YAMLError:
                    pass
        return {"name": path.parent.name}
