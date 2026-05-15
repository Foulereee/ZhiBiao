from __future__ import annotations

from core.skill_engine.base import Skill
from core.exceptions import SkillNotFoundError


class SkillRegistry:
    _instance: SkillRegistry | None = None
    _skills: dict[str, type[Skill]]

    def __init__(self):
        self._skills = {}

    @classmethod
    def instance(cls) -> SkillRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls):
        if cls._instance is not None:
            cls._instance._skills.clear()
        cls._instance = None

    def register(self, skill_class: type[Skill]):
        if not skill_class.name:
            raise ValueError(f"Skill类 {skill_class.__name__} 必须定义name属性")
        self._skills[skill_class.name] = skill_class

    def get(self, name: str) -> type[Skill]:
        if name not in self._skills:
            raise SkillNotFoundError(f"Skill '{name}' 未注册")
        return self._skills[name]

    def list_all(self) -> list[dict]:
        return [
            {
                "name": cls.name,
                "description": cls.description,
                "category": cls.category,
                "version": cls.version,
                "triggers": cls.triggers,
            }
            for cls in self._skills.values()
        ]

    def list_by_category(self, category: str) -> list[type[Skill]]:
        return [s for s in self._skills.values() if s.category == category]

    def match_trigger(self, text: str) -> list[type[Skill]]:
        matched = []
        text_lower = text.lower()
        for skill_cls in self._skills.values():
            if any(t.lower() in text_lower for t in skill_cls.triggers):
                matched.append(skill_cls)
        return matched

    def has(self, name: str) -> bool:
        return name in self._skills
