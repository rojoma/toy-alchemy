"""agent_core のAPI不要なヘルパー関数テスト。"""

import json
from pathlib import Path

import pytest

from src.agent_core import (
    detect_subject,
    parse_referee_verdict,
    resolve_tutor_skill,
    format_profile_for_prompt,
    load_child_profile,
    save_child_profile,
)
from src.conversation_store import PHASE_QUESTIONING, DEFAULT_PERSONA


# ---------- detect_subject ----------

def test_detect_subject_math_keyword():
    assert detect_subject("算数の宿題") == "算数"
    assert detect_subject("分数がわからない") == "算数"


def test_detect_subject_math_expression():
    assert detect_subject("3+5は？") == "算数"
    assert detect_subject("12 × 4 教えて") == "算数"


def test_detect_subject_japanese():
    assert detect_subject("漢字の書き取り") == "国語"


def test_detect_subject_unknown():
    assert detect_subject("こんにちは") is None


# ---------- parse_referee_verdict ----------

def test_parse_full_verdict():
    text = """
    DIRECTOR_VERDICT {
      phase: explaining
      selected_persona: gamemaster
      emotion: GENTLE_ENCOURAGEMENT
      prev_persona_signal: POSITIVE
    }
    """
    v = parse_referee_verdict(text)
    assert v["phase"] == "explaining"
    assert v["selected_persona"] == "gamemaster"
    assert v["emotion"] == "GENTLE_ENCOURAGEMENT"
    assert v["prev_persona_signal"] == "POSITIVE"


def test_parse_verdict_signal_negative():
    v = parse_referee_verdict("prev_persona_signal: NEGATIVE")
    assert v["prev_persona_signal"] == "NEGATIVE"


def test_parse_verdict_signal_default_neutral():
    v = parse_referee_verdict("phase: questioning")
    assert v["prev_persona_signal"] == "NEUTRAL"


def test_parse_verdict_defaults_when_missing():
    v = parse_referee_verdict("garbage output")
    assert v["phase"] == PHASE_QUESTIONING
    assert v["selected_persona"] == DEFAULT_PERSONA
    assert v["emotion"] == "NONE"


def test_parse_verdict_case_insensitive():
    v = parse_referee_verdict("PHASE: RESOLVED\nSELECTED_PERSONA: ARTIST")
    assert v["phase"] == "resolved"
    assert v["selected_persona"] == "artist"


# ---------- resolve_tutor_skill ----------

def test_resolve_tutor_skill_grade6_math():
    skill = resolve_tutor_skill("小学6年生", "算数")
    assert isinstance(skill, str) and len(skill) > 0


def test_resolve_tutor_skill_fallback_to_general():
    skill = resolve_tutor_skill("小学2年生", "社会")
    assert isinstance(skill, str) and len(skill) > 0


def test_resolve_tutor_skill_no_grade_no_subject():
    skill = resolve_tutor_skill(None, None)
    assert isinstance(skill, str) and len(skill) > 0


# ---------- format_profile_for_prompt ----------

def test_format_empty_profile():
    text = format_profile_for_prompt({})
    assert "プロファイル情報はまだありません" in text


def test_format_full_profile():
    profile = {
        "display_name": "ゆうき",
        "grade": "小学6年生",
        "learning_preferences": ["ゲームの例えが好き"],
        "strengths": ["かけ算九九"],
        "error_patterns": [
            {"subject": "算数", "description": "円の直径と半径を間違える"}
        ],
        "persona_effectiveness": {"gamemaster": 3, "logic": 1},
    }
    text = format_profile_for_prompt(profile)
    assert "ゆうき" in text
    assert "小学6年生" in text
    assert "ゲームの例え" in text
    assert "円の直径" in text
    assert "ゲームマスター" in text or "gamemaster" in text.lower() or "🎮" in text


# ---------- profile load/save round-trip ----------

def test_profile_roundtrip(tmp_path, monkeypatch):
    from src import agent_core
    monkeypatch.setattr(agent_core, "MEMORY_DIR", tmp_path)

    profile = {
        "child_id": "test_user_xyz",
        "display_name": "テスト太郎",
        "grade": "小学5年生",
    }
    save_child_profile(profile)
    loaded = load_child_profile("test_user_xyz")
    assert loaded["display_name"] == "テスト太郎"
    assert loaded["grade"] == "小学5年生"


def test_load_missing_profile_returns_skeleton(tmp_path, monkeypatch):
    from src import agent_core
    monkeypatch.setattr(agent_core, "MEMORY_DIR", tmp_path)

    loaded = load_child_profile("nonexistent")
    assert loaded["child_id"] == "nonexistent"
    assert loaded.get("session_history") == []
