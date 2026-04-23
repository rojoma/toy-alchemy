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
from training_field.teacher_memory import load_memory_prompt

EXTERNAL_DIR = Path(__file__).parent / "field" / "external_teachers"

# Internal teachers — created via factory methods on TeacherAgent.
_INTERNAL_FACTORIES = {
    "t001": TeacherAgent.create_dr_owen,
}


def _warmth_tier(v: float) -> str:
    if v >= 0.85: return "very_warm"
    if v >= 0.65: return "warm"
    if v >= 0.4: return "balanced"
    return "cool"


def _formality_tier(v: float) -> str:
    if v >= 0.7: return "formal"
    if v >= 0.45: return "neutral"
    return "casual"


def _pace_tier(v: float) -> str:
    if v >= 0.55: return "brisk"
    if v >= 0.4: return "steady"
    return "slow"


def _persona_preview(c) -> dict:
    """User-facing summary: what makes this teacher different from the others?

    Converts internal TeacherConfig parameters into tags and a plain-English
    tagline that a student or parent can actually use to pick one.
    """
    warmth = _warmth_tier(c.warmth)
    formality = _formality_tier(c.formality)
    pace = _pace_tier(c.pacing_speed)
    patience = "patient" if c.patience_threshold >= 4 else "brisk"
    motivation = c.motivation_style  # "challenge" | "encouragement" | "mastery"

    # Traits: short chips the UI shows on the teacher card.
    traits: list[dict] = []
    if warmth == "very_warm":
        traits.append({"key": "warm", "icon": "💗", "label_en": "Very warm", "label_ja": "とてもやさしい"})
    elif warmth == "warm":
        traits.append({"key": "warm", "icon": "😊", "label_en": "Warm", "label_ja": "やさしい"})
    elif warmth == "cool":
        traits.append({"key": "cool", "icon": "🧊", "label_en": "Cool & direct", "label_ja": "クールで率直"})

    if formality == "formal":
        traits.append({"key": "formal", "icon": "🎓", "label_en": "Formal", "label_ja": "丁寧"})
    elif formality == "casual":
        traits.append({"key": "casual", "icon": "🗣️", "label_en": "Casual", "label_ja": "くだけた"})

    if patience == "patient":
        traits.append({"key": "patient", "icon": "🕰️", "label_en": "Patient with mistakes", "label_ja": "間違いに寛容"})

    if motivation == "challenge":
        traits.append({"key": "challenges", "icon": "🔥", "label_en": "Challenges you", "label_ja": "チャレンジを促す"})
    elif motivation == "encouragement":
        traits.append({"key": "cheers", "icon": "📣", "label_en": "Cheers you on", "label_ja": "はげましてくれる"})
    elif motivation == "mastery":
        traits.append({"key": "mastery", "icon": "🎯", "label_en": "Mastery-focused", "label_ja": "じっくり完成させる"})

    if pace == "slow":
        traits.append({"key": "slow", "icon": "🐢", "label_en": "Slow and steady", "label_ja": "ゆっくりじっくり"})
    elif pace == "brisk":
        traits.append({"key": "brisk", "icon": "⚡", "label_en": "Brisk pace", "label_ja": "テンポよく"})

    if "socratic_questioning" in c.selected_skills:
        traits.append({"key": "socratic", "icon": "❓", "label_en": "Asks questions", "label_ja": "問いかけてくれる"})
    if "stepwise_decomposition" in c.selected_skills:
        traits.append({"key": "stepwise", "icon": "🪜", "label_en": "Step-by-step", "label_ja": "一歩ずつ"})
    if "concrete_examples" in c.selected_skills:
        traits.append({"key": "examples", "icon": "🍎", "label_en": "Real examples", "label_ja": "身近な例で"})

    # Derive a single tagline from the dominant traits. Short, student-facing.
    if motivation == "encouragement" and warmth in ("warm", "very_warm"):
        tagline_en = "Your encouraging cheerleader."
        tagline_ja = "やさしく応援してくれる先生。"
    elif motivation == "mastery" and pace == "slow":
        tagline_en = "Patient, step-by-step coach."
        tagline_ja = "一歩ずつ、しっかり確認する先生。"
    elif motivation == "challenge" and warmth == "cool":
        tagline_en = "Sharp challenger. No fluff."
        tagline_ja = "きびしめで、実力勝負の先生。"
    elif motivation == "challenge":
        tagline_en = "Curious questioner who pushes you to think."
        tagline_ja = "問いかけて考えさせてくれる先生。"
    elif warmth == "very_warm":
        tagline_en = "Warm and welcoming — great if you're nervous."
        tagline_ja = "あったかい雰囲気。緊張しがちな子に。"
    else:
        tagline_en = "Balanced and approachable."
        tagline_ja = "バランス型の先生。"

    return {
        "tagline_en": tagline_en,
        "tagline_ja": tagline_ja,
        "traits": traits,
    }


def _summarize(agent: TeacherAgent) -> dict:
    c = agent.config
    persona = _persona_preview(c)
    return {
        "teacher_id": c.teacher_id,
        "name": c.name,
        "origin": c.origin,
        "teaching_philosophy": c.teaching_philosophy,
        "warmth": c.warmth,
        "formality": c.formality,
        "patience_threshold": c.patience_threshold,
        "selected_skills": list(c.selected_skills),
        # User-facing derived fields (#10 groundwork):
        "tagline_en": persona["tagline_en"],
        "tagline_ja": persona["tagline_ja"],
        "traits": persona["traits"],
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
    tid = teacher_id or "t001"
    if tid == "t001" or not teacher_id:
        agent = TeacherAgent.create_dr_owen()
    elif tid in _INTERNAL_FACTORIES:
        agent = _INTERNAL_FACTORIES[tid]()
    elif EXTERNAL_DIR.exists():
        agent = None
        for path in EXTERNAL_DIR.glob("*.json"):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("teacher_id") == tid:
                    agent = TeacherAgent.from_json(path)
                    break
            except Exception:
                continue
        if agent is None:
            raise ValueError(f"Unknown teacher_id: {tid}")
    else:
        raise ValueError(f"Unknown teacher_id: {tid}")

    agent.session_memory = load_memory_prompt(agent.config.teacher_id)
    return agent
