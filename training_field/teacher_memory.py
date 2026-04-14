"""Teacher Session Memory — persists lessons learned across sessions.

Config = who the teacher IS (immutable).
Memory = what the teacher has LEARNED from past sessions (grows over time).
"""
from __future__ import annotations
import json
import datetime
from collections import Counter
from pathlib import Path

MEMORY_DIR = Path(__file__).parent / "field" / "teacher_memory"
MAX_SESSIONS = 5


def extract_session_insights(
    teacher_id: str,
    session_id: str,
    turn_evaluations: list,
    evaluation,
    update_check: dict,
) -> dict:
    directives = []
    for ev in turn_evaluations:
        d = ev.directive_to_teacher if hasattr(ev, "directive_to_teacher") else ""
        if d and d not in directives:
            directives.append(d)

    metrics = {
        "halluc_rate": round(getattr(evaluation, "hallucination_rate", 0) or 0, 3),
        "direct_rate": round(getattr(evaluation, "direct_answer_rate", 0) or 0, 3),
        "avg_zpd": round(getattr(evaluation, "avg_zpd_alignment", 0) or 0, 3),
        "avg_bloom": round(getattr(evaluation, "avg_bloom_level", 0) or 0, 1),
    }

    recommendation = None
    if update_check and update_check.get("trigger"):
        recommendation = update_check.get("recommendation")

    return {
        "session_id": session_id,
        "timestamp": datetime.datetime.now().isoformat(),
        "metrics": metrics,
        "directives": directives[:6],
        "recommendation": recommendation,
    }


def save_memory(teacher_id: str, insight: dict) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    path = MEMORY_DIR / f"{teacher_id}.json"

    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {"teacher_id": teacher_id, "sessions": []}

    data["sessions"].append(insight)
    data["sessions"] = data["sessions"][-MAX_SESSIONS:]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_memory_prompt(teacher_id: str) -> str:
    path = MEMORY_DIR / f"{teacher_id}.json"
    if not path.exists():
        return ""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""

    sessions = data.get("sessions", [])
    if not sessions:
        return ""

    directive_counts = Counter()
    for s in sessions:
        for d in s.get("directives", []):
            directive_counts[d] += 1

    top_directives = [d for d, _ in directive_counts.most_common(3)]

    latest = sessions[-1].get("metrics", {})
    first = sessions[0].get("metrics", {})
    n = len(sessions)

    def trend(key):
        v0 = first.get(key, 0) or 0
        v1 = latest.get(key, 0) or 0
        if v1 > v0 + 0.05:
            return f"{v0:.2f} → {v1:.2f} ↑"
        elif v1 < v0 - 0.05:
            return f"{v0:.2f} → {v1:.2f} ↓"
        return f"{v1:.2f} (stable)"

    lines = ["=== LESSONS FROM PAST SESSIONS ==="]

    if top_directives:
        for d in top_directives:
            count = directive_counts[d]
            lines.append(f"- {d} ({count}/{n} sessions)")

    lines.append(f"- ZPD alignment: {trend('avg_zpd')}")
    lines.append(f"- Hallucination rate: {trend('halluc_rate')}")

    latest_rec = None
    for s in reversed(sessions):
        if s.get("recommendation"):
            latest_rec = s["recommendation"]
            break
    if latest_rec:
        lines.append(f"- Recommendation: {latest_rec}")

    return "\n".join(lines)
