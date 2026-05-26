from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_MAX_AUX_FILES = 10


@dataclass
class SkillInfo:
    name: str
    description: str
    content: str
    location: Path
    auxiliary_files: list[Path] = field(default_factory=list)


def parse_skill_md(path: Path) -> SkillInfo | None:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None

    frontmatter = match.group(1)
    body = text[match.end() :]

    name = ""
    description = ""
    for line in frontmatter.splitlines():
        line = line.strip()
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip().strip("\"'")
        elif line.startswith("description:"):
            description = line.split(":", 1)[1].strip().strip("\"'")

    if not name or not _SKILL_NAME_RE.match(name):
        return None
    if not description:
        return None
    if len(name) > 64:
        return None
    if len(description) > 1024:
        description = description[:1024]

    skill_dir = path.parent
    aux_files = []
    try:
        for child in sorted(skill_dir.rglob("*")):
            if child.is_file() and child.name != "SKILL.md":
                aux_files.append(child)
                if len(aux_files) >= _MAX_AUX_FILES:
                    break
    except Exception:
        pass

    return SkillInfo(
        name=name,
        description=description,
        content=body.strip(),
        location=skill_dir,
        auxiliary_files=aux_files,
    )


def discover_skills(directories: list[Path]) -> dict[str, SkillInfo]:
    skills: dict[str, SkillInfo] = {}
    for directory in directories:
        if not directory.exists() or not directory.is_dir():
            continue
        try:
            for skill_md in directory.rglob("SKILL.md"):
                info = parse_skill_md(skill_md)
                if info:
                    skills[info.name] = info
        except Exception:
            continue
    return skills


def format_skill_content(skill: SkillInfo) -> str:
    parts = [
        f'<skill_content name="{skill.name}">\n',
        f"# Skill: {skill.name}\n\n",
        skill.content,
    ]
    if skill.auxiliary_files:
        parts.append("\n\nAuxiliary files (use read tool to load):")
        for f in skill.auxiliary_files:
            try:
                rel = f.relative_to(skill.location)
                parts.append(f"  - {rel}")
            except ValueError:
                parts.append(f"  - {f}")
    parts.append(f"\n\nSkill directory: {skill.location}")
    parts.append("\n</skill_content>")
    return "\n".join(parts)


def register_skill_tool(registry, skills: dict[str, SkillInfo]):
    if not skills:
        return

    available_lines = "\n".join(
        f"  - **{s.name}**: {s.description}" for s in sorted(skills.values(), key=lambda s: s.name)
    )
    description = (
        "Load a specialized skill that provides domain-specific instructions and workflows. "
        "Use this tool when you recognize that the current task matches one of the available skills. "
        "Returns the full skill instructions and auxiliary file references.\n\n"
        "Available skills:\n" + available_lines
    )

    _skills_ref = skills

    @registry.register(
        name="skill",
        description=description,
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The name of the skill to load from available skills",
                },
            },
            "required": ["name"],
        },
    )
    def load_skill(name: str) -> str:
        skill = _skills_ref.get(name)
        if not skill:
            names = ", ".join(sorted(_skills_ref.keys()))
            return f"Error: skill '{name}' not found. Available skills: {names}"
        return format_skill_content(skill)
