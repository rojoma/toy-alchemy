"""Teacher registry: enumerates and loads internal + external Teacher Agents.

Internal teachers are factory-created in code (e.g. Dr. Owen).
External teachers live in `field/external_teachers/*.json` — each file is the
external party's self-declared persona, validated against the field contract on load.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from training_field.teacher_agent import TeacherAgent

EXTERNAL_DIR = Path(__file__).parent / "field" / "external_teachers"

# Internal teachers — created via factory methods on TeacherAgent.
_INTERNAL_FACTORIES = {
    "t001": TeacherAgent.create_dr_owen,
}


def _summarize(agent: TeacherAgent) -> dict:
    c = agent.config
    return {
        "teacher_id": c.teacher_id,
        "name": c.name,
        "origin": c.origin,
        "teaching_philosophy": c.teaching_philosophy,
        "warmth": c.warmth,
        "formality": c.formality,
        "patience_threshold": c.patience_threshold,
        "selected_skills": list(c.selected_skills),
    }


def list_teachers() -> list[dict]:
    """Return a list of summaries (no LLM clients) for all available teachers."""
    out: list[dict] = []
    # Internal
    for tid, factory in _INTERNAL_FACTORIES.items():
        try:
            agent = factory()
            out.append(_summarize(agent))
        except Exception as e:
            out.append({"teacher_id": tid, "name": "(error)", "origin": "internal", "error": str(e)})
    # External
    if EXTERNAL_DIR.exists():
        for path in sorted(EXTERNAL_DIR.glob("*.json")):
            try:
                agent = TeacherAgent.from_json(path)
                out.append(_summarize(agent))
            except Exception as e:
                out.append({
                    "teacher_id": path.stem, "name": f"(invalid: {path.name})",
                    "origin": "external", "error": str(e),
                })
    return out


def load_teacher(teacher_id: Optional[str]) -> TeacherAgent:
    """Resolve a teacher_id to a fresh TeacherAgent instance.
    Falls back to Dr. Owen if teacher_id is None or unknown."""
    if not teacher_id or teacher_id == "t001":
        return TeacherAgent.create_dr_owen()
    if teacher_id in _INTERNAL_FACTORIES:
        return _INTERNAL_FACTORIES[teacher_id]()
    if EXTERNAL_DIR.exists():
        for path in EXTERNAL_DIR.glob("*.json"):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("teacher_id") == teacher_id:
                    return TeacherAgent.from_json(path)
            except Exception:
                continue
    # Unknown teacher_id → fail loudly so the caller knows
    raise ValueError(f"Unknown teacher_id: {teacher_id}")
