"""
Derive a personality + signals block from a Live session's turn log
and merge it into a student profile JSON (`reports/students/{id}.json`).

Closes the manual loop from HW10's calibration MVP: every Live session a
real student plays now contributes to a `derived` block describing how
they actually behave (response length, frustration markers, weak
topics). EWMA is used so a single weird session can't swing the profile.

Design choices:
- Pure-Python, no LLM calls. Deterministic and cheap.
- Additive: writes only into `profile["derived"]`. Existing fields
  (`proficiency`, `sessions_completed`, `name`, `grade`, …) are left
  alone — the existing `/api/student/{id}/update-proficiency` keeps
  owning those.
- Skips writing if the session has no usable turns (e.g. crashed
  pre-test).
"""
from __future__ import annotations

import datetime
import json
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

# EWMA weight on the latest observation. 0.4 → ~3 sessions until a value
# is mostly determined by recent behavior. Tunable.
EWMA_ALPHA = 0.4

# Phrases that signal "I'm done, leave me alone" or "I told you, I don't get it".
# Kept as fixed lists (not LLM-judged) for transparency.
FRUSTRATION_PATTERNS_JA = [
    r"だから",
    r"って！",
    r"もういい",
    r"知らない",
]
FRUSTRATION_PATTERNS_EN = [
    r"\bI told you\b",
    r"\bwhatever\b",
    r"\bgive up\b",
]

DISENGAGEMENT_PATTERNS_JA = [
    r"わからない",
    r"分からない",
    r"知らない",
    r"忘れた",
]
DISENGAGEMENT_PATTERNS_EN = [
    r"\bI don'?t know\b",
    r"\bnot sure\b",
    r"\bforgot\b",
]

# Keep the top-N misconceptions verbatim (privacy-bounded; not displayed
# back to other users in this MVP).
MAX_MISCONCEPTIONS = 5

# A topic counts as "weak" if its running mean delta is below this threshold,
# "strong" if above the symmetrical positive value.
WEAK_TOPIC_DELTA_THRESHOLD = 1.0
STRONG_TOPIC_DELTA_THRESHOLD = 5.0


def derive_signals_from_session(turns: list[dict], lang: str) -> dict[str, Any]:
    """Compute one session's worth of signals from its Referee-evaluated turn log.

    Returns a dict with the per-session observation. Caller is responsible
    for merging it into the running `derived` block via EWMA.
    """
    student_texts = [t.get("student") or "" for t in turns]
    student_texts = [s for s in student_texts if s.strip()]
    n_turns = len(student_texts)
    if n_turns == 0:
        return {"n_turns": 0}

    char_lengths = [len(s) for s in student_texts]
    frust_pats = FRUSTRATION_PATTERNS_JA if lang == "ja" else FRUSTRATION_PATTERNS_EN
    diseng_pats = DISENGAGEMENT_PATTERNS_JA if lang == "ja" else DISENGAGEMENT_PATTERNS_EN
    # Always check the other language too — bilingual sessions exist.
    frust_pats = frust_pats + (FRUSTRATION_PATTERNS_EN if lang == "ja" else FRUSTRATION_PATTERNS_JA)
    diseng_pats = diseng_pats + (DISENGAGEMENT_PATTERNS_EN if lang == "ja" else DISENGAGEMENT_PATTERNS_JA)

    frust_count = sum(1 for s in student_texts if _matches_any(s, frust_pats))
    diseng_count = sum(1 for s in student_texts if _matches_any(s, diseng_pats))
    aha_count = sum(1 for t in turns if (t.get("delta") or 0) >= 5)

    return {
        "n_turns": n_turns,
        "mean_chars": round(statistics.mean(char_lengths), 1),
        "median_chars": int(statistics.median(char_lengths)),
        "max_chars": max(char_lengths),
        "frustration_rate": round(frust_count / n_turns, 3),
        "disengagement_rate": round(diseng_count / n_turns, 3),
        "aha_rate": round(aha_count / n_turns, 3),
    }


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


def update_derived_profile(
    profile_path: Path,
    *,
    turns: list[dict],
    lang: str,
    topic: str | None,
    proficiency_delta: float,
    teacher_skills: Iterable[str],
) -> dict[str, Any] | None:
    """Merge one session's observations into `profile["derived"]`.

    Returns the updated profile dict on success, None if the profile
    file doesn't exist or the session had no usable signal.
    """
    if not profile_path.exists():
        return None
    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    obs = derive_signals_from_session(turns, lang)
    if obs.get("n_turns", 0) == 0:
        return None  # nothing to learn from

    derived = profile.get("derived") or {
        "version": 1,
        "sessions_observed": 0,
        "personality": {},
        "signals": {},
        "weak_topics": [],
        "strong_topics": [],
        "topic_deltas": {},
        "misconceptions": [],
    }

    # 1. EWMA-update numeric signals.
    prev_signals = derived.get("signals") or {}
    new_signals: dict[str, float] = {}
    for key in ("mean_chars", "median_chars", "max_chars",
                "frustration_rate", "disengagement_rate", "aha_rate"):
        if key not in obs:
            continue
        prev = prev_signals.get(key)
        new_signals[key] = _ewma(prev, obs[key], EWMA_ALPHA)
    derived["signals"] = new_signals

    # 2. Per-topic running mean delta. Stored separately from the existing
    #    `proficiency` map so we can reason about *trend* not just absolute.
    if topic:
        topic_deltas = derived.get("topic_deltas") or {}
        prev_d = topic_deltas.get(topic)
        topic_deltas[topic] = round(_ewma(prev_d, proficiency_delta, EWMA_ALPHA), 2)
        derived["topic_deltas"] = topic_deltas
        derived["weak_topics"] = sorted(
            [t for t, d in topic_deltas.items() if d < WEAK_TOPIC_DELTA_THRESHOLD]
        )
        derived["strong_topics"] = sorted(
            [t for t, d in topic_deltas.items() if d >= STRONG_TOPIC_DELTA_THRESHOLD]
        )

    # 3. Misconceptions: keep verbatim student replies on turns the
    #    Referee flagged as low-mastery. Bounded list (rolling).
    new_miscons = [
        (t.get("student") or "").strip()
        for t in turns
        if (t.get("delta") or 0) < 0 and (t.get("student") or "").strip()
    ]
    if new_miscons:
        misc = list(derived.get("misconceptions") or [])
        misc.extend(new_miscons)
        # Deduplicate while preserving order (most recent at end), keep last N.
        seen = set()
        deduped = []
        for m in reversed(misc):
            if m in seen:
                continue
            seen.add(m)
            deduped.append(m)
        derived["misconceptions"] = list(reversed(deduped[:MAX_MISCONCEPTIONS]))

    # 4. Preferred skills — count which of the teacher's skills appeared
    #    in this session, weighted by proficiency_delta. Just the top-3.
    pref = derived.get("preferred_skills_counter") or {}
    weight = max(proficiency_delta, 0.0)  # only credit gains
    for sk in teacher_skills:
        pref[sk] = round(pref.get(sk, 0) + weight, 2)
    derived["preferred_skills_counter"] = pref
    derived["preferred_skills"] = [
        sk for sk, _ in sorted(pref.items(), key=lambda kv: -kv[1])[:3]
    ]

    # 5. Personality — derived deterministically from the smoothed signals.
    derived["personality"] = _derive_personality(new_signals)
    derived["personality"]["description"] = _describe_personality(
        new_signals, derived["weak_topics"]
    )

    derived["sessions_observed"] = derived.get("sessions_observed", 0) + 1
    derived["updated_at"] = datetime.datetime.now().isoformat()
    profile["derived"] = derived

    profile_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return profile


def _ewma(prev: float | None, observed: float, alpha: float) -> float:
    if prev is None:
        return float(observed)
    return round(alpha * float(observed) + (1 - alpha) * float(prev), 3)


def _derive_personality(signals: dict[str, float]) -> dict[str, float]:
    """Map smoothed signals to TeacherConfig-shaped personality knobs.

    Verbosity = mean_chars normalized (60+ chars → 1.0).
    Patience = inverse of frustration_rate.
    Confidence = inverse of disengagement_rate.
    Curiosity = aha_rate, scaled.
    """
    mean_chars = signals.get("mean_chars", 30.0)
    frust = signals.get("frustration_rate", 0.0)
    diseng = signals.get("disengagement_rate", 0.0)
    aha = signals.get("aha_rate", 0.0)

    return {
        "verbosity": round(min(max(mean_chars / 60.0, 0.0), 1.0), 2),
        "patience": round(min(max(1.0 - frust * 2.5, 0.0), 1.0), 2),
        "confidence": round(min(max(1.0 - diseng * 1.5, 0.0), 1.0), 2),
        "curiosity": round(min(max(aha * 5.0, 0.0), 1.0), 2),
    }


def _describe_personality(signals: dict[str, float], weak_topics: list[str]) -> str:
    """Produce a deterministic, human-readable summary string.

    Templated (not LLM) so the description always agrees with the numbers
    and is reviewable.
    """
    parts: list[str] = []
    median_chars = signals.get("median_chars")
    if median_chars is not None:
        if median_chars <= 12:
            parts.append(f"short replies (median {int(median_chars)} chars)")
        elif median_chars >= 40:
            parts.append(f"verbose replies (median {int(median_chars)} chars)")

    frust = signals.get("frustration_rate")
    if frust is not None and frust >= 0.15:
        parts.append(f"frustrates often ({int(frust*100)}% of turns)")
    diseng = signals.get("disengagement_rate")
    if diseng is not None and diseng >= 0.25:
        parts.append(f"disengages on hard re-questions ({int(diseng*100)}% of turns)")
    aha = signals.get("aha_rate")
    if aha is not None and aha >= 0.2:
        parts.append(f"frequent aha moments ({int(aha*100)}% of turns)")

    if weak_topics:
        # Truncate to first 2 to keep the summary one short sentence.
        parts.append("weakest topics: " + ", ".join(weak_topics[:2]))

    if not parts:
        return "Auto-derived: not enough signal yet to characterize."
    return "Auto-derived: " + "; ".join(parts) + "."
