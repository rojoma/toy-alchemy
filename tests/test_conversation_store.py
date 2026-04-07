"""ConversationStore のフェーズ/ペルソナ管理・履歴整形のテスト（API不要）。"""

from src.conversation_store import (
    ConversationStore,
    PERSONAS,
    DEFAULT_PERSONA,
    PHASE_QUESTIONING,
    PHASE_EXPLAINING,
    PHASE_RESOLVED,
)


def test_default_phase_and_persona():
    store = ConversationStore()
    assert store.get_phase("u1") == PHASE_QUESTIONING
    assert store.get_persona("u1") == DEFAULT_PERSONA


def test_phase_transition():
    store = ConversationStore()
    store.set_phase("u1", PHASE_EXPLAINING)
    assert store.get_phase("u1") == PHASE_EXPLAINING
    store.set_phase("u1", PHASE_RESOLVED)
    assert store.get_phase("u1") == PHASE_RESOLVED


def test_persona_switch_isolated_per_user():
    store = ConversationStore()
    store.set_persona("u1", "gamemaster")
    store.set_persona("u2", "artist")
    assert store.get_persona("u1") == "gamemaster"
    assert store.get_persona("u2") == "artist"


def test_message_history_with_persona():
    store = ConversationStore()
    store.add_child_message("u1", "円の面積がわからない")
    store.add_tutor_response("u1", "ヒント出すよ！", persona_used="gamemaster")
    history = store.get_history("u1")
    assert "子供:" in history
    assert "フクロウ先生:" in history
    assert "円の面積" in history


def test_persona_effectiveness_tracking():
    store = ConversationStore()
    store.record_persona_outcome("u1", "gamemaster", positive=True)
    store.record_persona_outcome("u1", "gamemaster", positive=True)
    store.record_persona_outcome("u1", "logic", positive=False)
    eff = store.get_persona_effectiveness("u1")
    assert eff["gamemaster"] == 2
    assert eff["logic"] == -1


def test_subject_selection_flow():
    store = ConversationStore()
    assert not store.is_selecting_subject("u1")
    store.start_subject_selection("u1")
    assert store.is_selecting_subject("u1")
    store.set_selected_subject("u1", "算数")
    store.finish_subject_selection("u1")
    assert not store.is_selecting_subject("u1")
    assert store.get_selected_subject("u1") == "算数"


def test_all_personas_defined():
    expected = {"standard", "gamemaster", "artist", "logic"}
    assert set(PERSONAS.keys()) == expected
    for p in PERSONAS.values():
        assert "name" in p and "style" in p and "description" in p
