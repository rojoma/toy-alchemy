"""
Toy Alchemy - テスト用 Web UI（Streamlit）

ブラウザ上でフクロウ先生と会話しながら、
裏側のReferee判定（ペルソナ選択・フェーズ・ディレクティブ）を確認できる。

起動方法:
    cd toy-alchemy
    streamlit run src/app_ui.py
"""

import os
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import streamlit as st

from src.agent_core import (
    run_tutoring_session,
    load_child_profile,
    save_child_profile,
    detect_subject,
)
from src.conversation_store import PERSONAS, PHASE_QUESTIONING

# ---------------------------------------------------------------------------
# ページ設定
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Toy Alchemy - フクロウ先生 🦉",
    page_icon="🦉",
    layout="wide",
)

# ---------------------------------------------------------------------------
# セッション状態の初期化
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []
if "phase" not in st.session_state:
    st.session_state.phase = PHASE_QUESTIONING
if "persona" not in st.session_state:
    st.session_state.persona = "standard"
if "history_text" not in st.session_state:
    st.session_state.history_text = ""
if "debug_logs" not in st.session_state:
    st.session_state.debug_logs = []
if "subject" not in st.session_state:
    st.session_state.subject = "算数"
if "child_id" not in st.session_state:
    st.session_state.child_id = "streamlit_test_user"

# ---------------------------------------------------------------------------
# サイドバー: 設定パネル
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("⚙️ 設定")

    st.session_state.subject = st.selectbox(
        "教科", ["算数", "国語", "理科", "社会", "その他"]
    )

    child_name = st.text_input("子供の名前", value="ゆうき")
    child_grade = st.selectbox(
        "学年",
        ["小学1年生", "小学2年生", "小学3年生", "小学4年生",
         "小学5年生", "小学6年生", "中学1年生", "中学2年生", "中学3年生"],
        index=5,
    )

    if st.button("プロフィールを保存"):
        profile = load_child_profile(st.session_state.child_id)
        profile["display_name"] = child_name
        profile["grade"] = child_grade
        save_child_profile(profile)
        st.success(f"保存しました: {child_name} ({child_grade})")

    st.divider()

    st.subheader("📊 現在の状態")
    persona_info = PERSONAS.get(st.session_state.persona, {})
    st.metric("フェーズ", st.session_state.phase)
    st.metric("ペルソナ", persona_info.get("name", st.session_state.persona))

    st.divider()

    if st.button("🔄 会話をリセット"):
        st.session_state.messages = []
        st.session_state.phase = PHASE_QUESTIONING
        st.session_state.persona = "standard"
        st.session_state.history_text = ""
        st.session_state.debug_logs = []
        st.rerun()

# ---------------------------------------------------------------------------
# メイン画面: チャット
# ---------------------------------------------------------------------------

st.title("🦉 フクロウ先生 - AI家庭教師")
st.caption("Agent Pool + Explain-to-Learn テストUI")

# チャット履歴を表示
for msg in st.session_state.messages:
    if msg["role"] == "child":
        with st.chat_message("user", avatar="👧"):
            st.write(msg["text"])
    else:
        persona_name = PERSONAS.get(msg.get("persona", "standard"), {}).get("name", "🦉")
        with st.chat_message("assistant", avatar="🦉"):
            st.write(msg["text"])
            st.caption(f"{persona_name} | Phase: {msg.get('phase', '?')}")

        # デバッグ情報（折りたたみ）
        if msg.get("referee_directive"):
            with st.expander("🔍 Referee ディレクティブ（裏側）"):
                st.code(msg["referee_directive"], language=None)

# ---------------------------------------------------------------------------
# 入力フォーム
# ---------------------------------------------------------------------------

if user_input := st.chat_input("質問を入力してね！（例: 円の面積がわからない）"):
    # 子供のメッセージを表示・記録
    st.session_state.messages.append({"role": "child", "text": user_input})
    with st.chat_message("user", avatar="👧"):
        st.write(user_input)

    # 会話履歴を更新
    history_lines = []
    for msg in st.session_state.messages[-20:]:
        speaker = "子供" if msg["role"] == "child" else "フクロウ先生"
        history_lines.append(f"{speaker}: {msg['text']}")
    st.session_state.history_text = "\n".join(history_lines)

    # CrewAI 実行
    with st.chat_message("assistant", avatar="🦉"):
        with st.spinner("フクロウ先生が考え中... 🤔"):
            try:
                result = run_tutoring_session(
                    child_id=st.session_state.child_id,
                    child_message=user_input,
                    conversation_history=st.session_state.history_text,
                    subject_override=st.session_state.subject,
                    current_phase=st.session_state.phase,
                    current_persona=st.session_state.persona,
                )

                tutor_response = result["tutor_response"]
                referee_directive = result["referee_directive"]
                new_phase = result["phase"]
                persona_used = result["persona_used"]

                # 状態を更新
                st.session_state.phase = new_phase
                st.session_state.persona = persona_used

            except Exception as e:
                tutor_response = f"エラーが発生しました: {e}"
                referee_directive = ""
                persona_used = st.session_state.persona
                new_phase = st.session_state.phase

        # 返答を表示
        st.write(tutor_response)
        persona_name = PERSONAS.get(persona_used, {}).get("name", "🦉")
        st.caption(f"{persona_name} | Phase: {new_phase}")

    # デバッグ情報
    if referee_directive:
        with st.expander("🔍 Referee ディレクティブ（裏側）"):
            st.code(referee_directive, language=None)

    # メッセージ履歴に追加
    st.session_state.messages.append({
        "role": "tutor",
        "text": tutor_response,
        "persona": persona_used,
        "phase": new_phase,
        "referee_directive": referee_directive,
    })
