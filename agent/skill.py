from __future__ import annotations

from pathlib import Path
from typing import Any


class Skill:
    def __init__(self, name: str, description: str, always: bool = False, details: str = ""):
        self.name = name
        self.description = description
        self.always = always
        self.details = details

    @classmethod
    def from_md(cls, path: Path) -> "Skill":
        text = path.read_text(encoding="utf-8")
        meta: dict[str, Any] = {}
        body = text

        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                raw_meta = parts[1]
                body = parts[2].strip()
                for line in raw_meta.splitlines():
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    meta[key.strip()] = value.strip().strip('"').strip("'")

        return cls(
            name=meta.get("name", path.parent.name),
            description=meta.get("description", ""),
            always=str(meta.get("always", "false")).lower() in {"true", "1", "yes"},
            details=body,
        )

    def to_prompt(self) -> str:
        prompt = f"- {self.name}: {self.description}"
        if self.details:
            newline = '\n'
            indent = '\n  '
            prompt += f"\n  {self.details.strip().replace(newline, indent)}"
        return prompt


class SkillManager:
    def __init__(self, skill_root: Path):
        self.skill_root = skill_root
        self.skills: dict[str, Skill] = self._load_skills()

    def _load_skills(self) -> dict[str, Skill]:
        skills: dict[str, Skill] = {}
        if not self.skill_root.exists():
            return skills

        for child in sorted(self.skill_root.iterdir()):
            if not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.exists():
                continue
            skill = Skill.from_md(skill_file)
            skills[skill.name] = skill

        return skills

    def get(self, name: str) -> Skill | None:
        return self.skills.get(name)

    def get_all(self) -> list[Skill]:
        return list(self.skills.values())

    def get_definitions(self) -> list[dict[str, str]]:
        return [
            {"name": skill.name, "description": skill.description}
            for skill in self.skills.values()
        ]

    def to_prompt(self) -> str:
        if not self.skills:
            return ""
        return "\n\n".join(skill.to_prompt() for skill in self.get_all())
