"""
Toy Alchemy - AI家庭教師コアエンジン v2

【アーキテクチャ】
- Referee = 総合ディレクター（フェーズ判定・ペルソナ選択・品質評価）
- TutorAgent Factory = 4つのペルソナから動的生成（Agent Pool）
- Explain-to-Learn Loop = 子供の自己説明を引き出して検証する2段階フェーズ

【フロー】
1. Referee がフェーズ判定（questioning / explaining）+ ペルソナ選択
2. 選択されたペルソナの Tutor が返答生成
3. Phase 2 では子供の説明をRefereeが論理検証
"""

import json
import re
from pathlib import Path
from textwrap import dedent

from crewai import Agent, Crew, Process, Task

from src.conversation_store import (
    PERSONAS,
    DEFAULT_PERSONA,
    PHASE_QUESTIONING,
    PHASE_EXPLAINING,
    PHASE_RESOLVED,
)

# ---------------------------------------------------------------------------
# パス定義
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"
MEMORY_DIR = Path(__file__).parent / "memory"

# ---------------------------------------------------------------------------
# スキル読み込み（教科×学年）
# ---------------------------------------------------------------------------

TUTOR_SKILL_MAP = {
    ("小学6", "算数"): "edu6th_math.md",
    ("小学6", "math"): "edu6th_math.md",
}


def load_skill(skill_path: Path) -> str:
    if not skill_path.exists():
        raise FileNotFoundError(f"スキルファイルが見つかりません: {skill_path}")
    return skill_path.read_text(encoding="utf-8")


def resolve_tutor_skill(grade: str | None, subject: str | None) -> str:
    if grade and subject:
        for (grade_prefix, subj), filename in TUTOR_SKILL_MAP.items():
            if grade.startswith(grade_prefix) and subject == subj:
                skill_path = SKILLS_DIR / "tutor" / filename
                if skill_path.exists():
                    return load_skill(skill_path)
    if subject:
        for (grade_prefix, subj), filename in TUTOR_SKILL_MAP.items():
            if subject == subj:
                skill_path = SKILLS_DIR / "tutor" / filename
                if skill_path.exists():
                    return load_skill(skill_path)
    return load_skill(SKILLS_DIR / "tutor" / "general.md")


def load_referee_skill() -> str:
    return load_skill(SKILLS_DIR / "referee" / "referee_base.md")


def detect_subject(message: str) -> str | None:
    math_keywords = [
        "算数", "数学", "計算", "足し算", "引き算", "かけ算", "割り算",
        "分数", "小数", "面積", "体積", "速さ", "割合", "比",
        "+", "-", "×", "÷", "=",
    ]
    math_pattern = r"\d+\s*[+\-×÷÷/\*]\s*\d+"
    if any(kw in message for kw in math_keywords) or re.search(math_pattern, message):
        return "算数"

    science_keywords = ["理科", "実験", "植物", "動物", "天気", "星", "月", "電気", "磁石"]
    if any(kw in message for kw in science_keywords):
        return "理科"

    japanese_keywords = ["国語", "漢字", "作文", "読解", "文章", "書き順", "熟語"]
    if any(kw in message for kw in japanese_keywords):
        return "国語"

    return None


# ---------------------------------------------------------------------------
# メモリ（子供の学習プロファイル）
# ---------------------------------------------------------------------------


def load_child_profile(child_id: str) -> dict:
    profile_path = MEMORY_DIR / f"{child_id}.json"
    if profile_path.exists():
        with open(profile_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "child_id": child_id,
        "display_name": "",
        "grade": None,
        "learning_preferences": [],
        "error_patterns": [],
        "strengths": [],
        "session_history": [],
    }


def save_child_profile(profile: dict) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    profile_path = MEMORY_DIR / f"{profile['child_id']}.json"
    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


def format_profile_for_prompt(profile: dict) -> str:
    if not profile.get("display_name"):
        return "（この子供のプロファイル情報はまだありません。初回セッションです。）"

    parts = [f"【生徒プロファイル: {profile['display_name']}】"]
    if profile.get("grade"):
        parts.append(f"- 学年: {profile['grade']}")
    if profile.get("learning_preferences"):
        prefs = "、".join(profile["learning_preferences"])
        parts.append(f"- 好きな学び方: {prefs}")
    if profile.get("error_patterns"):
        for ep in profile["error_patterns"][-5:]:
            parts.append(
                f"- 過去の間違いパターン [{ep.get('subject', '不明')}]: "
                f"{ep.get('description', '')}"
            )
    if profile.get("strengths"):
        parts.append(f"- 得意なこと: {'、'.join(profile['strengths'])}")
    if profile.get("persona_effectiveness"):
        best = max(profile["persona_effectiveness"], key=profile["persona_effectiveness"].get)
        parts.append(f"- 最も効果的だったペルソナ: {PERSONAS.get(best, {}).get('name', best)}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Agent Pool: TutorAgent Factory
# ---------------------------------------------------------------------------

def _format_persona_list() -> str:
    """全ペルソナの一覧をプロンプト用に整形する。"""
    lines = []
    for pid, p in PERSONAS.items():
        lines.append(f"- {p['name']} (id={pid}): {p['description']}")
    return "\n".join(lines)


def create_tutor_agent(
    grade: str | None,
    subject: str | None,
    persona_id: str = DEFAULT_PERSONA,
    model: str = "gpt-4o",
) -> Agent:
    """
    TutorAgent Factory: 教科スキル × ペルソナスタイルを合成して生成。

    教科スキル = 何を教えるか（知識・カリキュラム）
    ペルソナスタイル = どう教えるか（話し方・例え方）
    """
    subject_skill = resolve_tutor_skill(grade, subject)
    persona = PERSONAS.get(persona_id, PERSONAS[DEFAULT_PERSONA])

    combined_backstory = dedent(f"""\
        【あなたのペルソナ: {persona['name']}】
        {persona['style']}

        【絶対ルール】
        - 答えそのものを絶対に教えない
        - 最大3文で返答（4文以上禁止）
        - 質問は1つだけ（複数同時禁止）
        - Phase 1 では必ず「なんでそうなると思う？先生に教えて！」のように、
          子供に自分の推論を説明するよう求める問いかけで終わる
        - Phase 2 では子供の説明に対してフィードバック（褒める or 追加で問う）

        【教科知識（以下のスキル定義に従って教える）】
        {subject_skill}
    """)

    return Agent(
        role=f"{persona['name']}（Tutor）",
        goal=dedent("""\
            子供が自分の力で答えにたどり着けるよう、ペルソナのスタイルで導く。
            絶対に答えそのものを教えない。子供自身に「なぜそうなるか」を説明させる。
        """),
        backstory=combined_backstory,
        verbose=True,
        allow_delegation=False,
        llm=model,
    )


# ---------------------------------------------------------------------------
# RefereeAgent: 総合ディレクター
# ---------------------------------------------------------------------------

def create_referee_agent(model: str = "gpt-4o") -> Agent:
    """Referee = 総合ディレクター。フェーズ判定・ペルソナ選択・品質評価を一手に担う。"""
    referee_skill = load_referee_skill()

    persona_list = _format_persona_list()

    enhanced_backstory = dedent(f"""\
        {referee_skill}

        ---
        ## 追加責務: 総合ディレクター機能

        あなたは品質評価に加えて、以下の判断も毎回行います。

        ### A. フェーズ判定
        子供の発言が以下のどの段階かを判定してください:
        - **questioning**: 子供が質問している / まだ答えを考えている段階
          → Tutorはヒントを出しつつ「なんでそう思う？教えて！」と説明を求める
        - **explaining**: 子供が自分なりの推論・説明を述べている段階
          → Tutorは説明の論理を検証してフィードバック（褒める or 追加で問う）
        - **resolved**: 子供が正しく理解できた段階
          → Tutorは褒めて、次の問題や発展的な問いかけに進む

        ### B. ペルソナ選択（Agent Pool）
        以下の4つのペルソナから、今の子供に最適なものを選んでください:
        {persona_list}

        選択基準:
        1. 子供の `learning_preferences`（ゲーム好き → gamemaster 等）
        2. 現在の感情状態（落ち込み → standard、退屈そう → gamemaster）
        3. 前のペルソナで効果がなかった場合 → 別のペルソナに切り替え
        4. 迷ったら standard をデフォルトにする

        ### C. 文脈引き継ぎ
        前のターンからの問題・ヒント・子供の回答を確実に引き継ぐよう、
        Tutorへの指示に含めてください。
    """)

    return Agent(
        role="総合ディレクター（Referee）",
        goal=dedent("""\
            毎回のセッションで以下を判断し、構造化ディレクティブを出す:
            1. フェーズ判定（questioning / explaining / resolved）
            2. 最適なTutorペルソナの選択
            3. Tutorへの具体的な教授法指示
            4. 品質評価（答えを教えていないか、適切な教授法か）
        """),
        backstory=enhanced_backstory,
        verbose=True,
        allow_delegation=False,
        llm=model,
    )


# ---------------------------------------------------------------------------
# タスク定義
# ---------------------------------------------------------------------------

def create_referee_task(
    agent: Agent,
    child_question: str,
    child_profile_text: str,
    conversation_history: str = "",
    current_phase: str = PHASE_QUESTIONING,
    current_persona: str = DEFAULT_PERSONA,
) -> Task:
    """Refereeが総合判断を行うタスク。"""
    return Task(
        description=dedent(f"""\
            以下の情報をもとに、総合ディレクティブを作成してください。

            {child_profile_text}

            【現在の状態】
            - 現在のフェーズ: {current_phase}
            - 現在のペルソナ: {PERSONAS.get(current_persona, {}).get('name', current_persona)}

            【子供からの質問・メッセージ】
            {child_question}

            【これまでの会話履歴】
            {conversation_history if conversation_history else "（初回の質問です）"}

            【出力形式】
            DIRECTOR_VERDICT {{
              phase: questioning | explaining | resolved
              selected_persona: standard | gamemaster | artist | logic
              persona_reason: [なぜこのペルソナを選んだかの一言理由]
              emotion: NONE | GENTLE_ENCOURAGEMENT | EMOTIONAL_CARE_PRIORITY | GENTLE_REDIRECT
              accuracy: PASS | LOGICAL_ERROR | ARITHMETIC_ERROR
              pedagogy: PASS | PEDAGOGY_VIOLATION | IMPROVE_SPECIFICITY
              crutch: PASS | CRUTCH_DETECTED
              directive_to_tutor: [具体的な指示（日本語）]
              context_carryover: [前のターンから引き継ぐべき情報]
              prev_persona_signal: POSITIVE | NEGATIVE | NEUTRAL
              # ↑ 直前のペルソナ「{PERSONAS.get(current_persona, {}).get('name', current_persona)}」が
              # 子供に効いていたか判定（理解進展あり=POSITIVE、混乱や無反応=NEGATIVE、
              # 初回や判断不能=NEUTRAL）。これは将来のペルソナ選択に蓄積されます。
            }}
        """),
        expected_output="DIRECTOR_VERDICT形式の構造化ディレクティブ",
        agent=agent,
    )


def create_tutor_task(
    agent: Agent,
    child_question: str,
    child_profile_text: str,
    referee_task: Task,
    conversation_history: str = "",
    current_phase: str = PHASE_QUESTIONING,
) -> Task:
    """TutorAgentが子供に返答するタスク。"""

    phase_instruction = ""
    if current_phase == PHASE_QUESTIONING:
        phase_instruction = (
            "【Phase 1: 導入・ヒント段階】\n"
            "ヒントを出しつつ、最後に必ず「なんでそうなると思う？先生に教えて！」の"
            "ように、子供自身に推論の説明を求める問いかけで終わること。"
        )
    elif current_phase == PHASE_EXPLAINING:
        phase_instruction = (
            "【Phase 2: 説明の検証段階】\n"
            "子供が自分なりに説明してくれた内容に対して、"
            "正しい部分を具体的に褒め、足りない部分があれば追加で問いかけること。"
            "論理が正しければ「すごい！その通り！」と称えてPhase resolvedへ。"
        )
    elif current_phase == PHASE_RESOLVED:
        phase_instruction = (
            "【Phase: 解決済み】\n"
            "子供を褒めて、次の問題や発展的な問いかけに進むこと。"
        )

    return Task(
        description=dedent(f"""\
            あなたはペルソナのスタイルに忠実に従って返答してください。

            {child_profile_text}

            {phase_instruction}

            【子供からの質問・メッセージ】
            {child_question}

            【これまでの会話履歴】
            {conversation_history if conversation_history else "（初回の質問です）"}

            【重要ルール】
            - Refereeのディレクティブに従うこと
            - 答えを絶対に教えないこと
            - 最大3文で返答すること（4文以上は禁止）
            - 質問は1つだけにすること
            - ペルソナのスタイル（話し方・例え方）に忠実に従うこと
        """),
        expected_output="ペルソナのスタイルで子供に語りかける返答（日本語、最大3文、質問は1つだけ）",
        agent=agent,
        context=[referee_task],
    )


# ---------------------------------------------------------------------------
# Refereeの判定結果をパース
# ---------------------------------------------------------------------------

def parse_referee_verdict(verdict_text: str) -> dict:
    """Refereeの出力テキストから構造化データを抽出する。"""
    result = {
        "phase": PHASE_QUESTIONING,
        "selected_persona": DEFAULT_PERSONA,
        "emotion": "NONE",
        "prev_persona_signal": "NEUTRAL",
    }

    signal_match = re.search(
        r"prev_persona_signal:\s*(POSITIVE|NEGATIVE|NEUTRAL)",
        verdict_text, re.IGNORECASE,
    )
    if signal_match:
        result["prev_persona_signal"] = signal_match.group(1).upper()

    # フェーズ抽出
    phase_match = re.search(r"phase:\s*(questioning|explaining|resolved)", verdict_text, re.IGNORECASE)
    if phase_match:
        result["phase"] = phase_match.group(1).lower()

    # ペルソナ抽出
    persona_match = re.search(
        r"selected_persona:\s*(standard|gamemaster|artist|logic)", verdict_text, re.IGNORECASE
    )
    if persona_match:
        result["selected_persona"] = persona_match.group(1).lower()

    # 感情抽出
    emotion_match = re.search(
        r"emotion:\s*(NONE|GENTLE_ENCOURAGEMENT|EMOTIONAL_CARE_PRIORITY|GENTLE_REDIRECT)",
        verdict_text, re.IGNORECASE,
    )
    if emotion_match:
        result["emotion"] = emotion_match.group(1).upper()

    return result


# ---------------------------------------------------------------------------
# Crew（エージェント連携）の実行
# ---------------------------------------------------------------------------

def run_tutoring_session(
    child_id: str,
    child_message: str,
    conversation_history: str = "",
    model: str = "gpt-4o",
    subject_override: str | None = None,
    current_phase: str = PHASE_QUESTIONING,
    current_persona: str = DEFAULT_PERSONA,
) -> dict:
    """
    家庭教師セッションを実行する。

    1. Referee が総合判断（フェーズ判定・ペルソナ選択・品質評価）
    2. 選択されたペルソナのTutorが返答生成
    3. 結果にフェーズ・ペルソナ情報を含めて返す
    """
    profile = load_child_profile(child_id)
    profile_text = format_profile_for_prompt(profile)
    subject = subject_override or detect_subject(child_message)
    grade = profile.get("grade")

    # --- Step 1: Referee が総合判断 ---
    referee = create_referee_agent(model=model)
    referee_task = create_referee_task(
        agent=referee,
        child_question=child_message,
        child_profile_text=profile_text,
        conversation_history=conversation_history,
        current_phase=current_phase,
        current_persona=current_persona,
    )

    referee_crew = Crew(
        agents=[referee],
        tasks=[referee_task],
        process=Process.sequential,
        verbose=True,
    )
    referee_result = referee_crew.kickoff()
    referee_output = referee_result.tasks_output[0].raw

    # Refereeの判定をパース
    verdict = parse_referee_verdict(referee_output)
    new_phase = verdict["phase"]
    selected_persona = verdict["selected_persona"]

    # --- Step 2: 選択されたペルソナのTutorが返答 ---
    tutor = create_tutor_agent(
        grade=grade,
        subject=subject,
        persona_id=selected_persona,
        model=model,
    )
    tutor_task = create_tutor_task(
        agent=tutor,
        child_question=child_message,
        child_profile_text=profile_text,
        referee_task=referee_task,
        conversation_history=conversation_history,
        current_phase=new_phase,
    )

    tutor_crew = Crew(
        agents=[tutor],
        tasks=[tutor_task],
        process=Process.sequential,
        verbose=True,
    )
    tutor_result = tutor_crew.kickoff()
    tutor_output = tutor_result.tasks_output[0].raw

    # --- Step 3: 直前のペルソナへのフィードバックを永続化 ---
    prev_signal = verdict.get("prev_persona_signal", "NEUTRAL")
    if conversation_history and prev_signal in ("POSITIVE", "NEGATIVE"):
        delta = 1 if prev_signal == "POSITIVE" else -1
        eff = profile.setdefault("persona_effectiveness", {})
        eff[current_persona] = eff.get(current_persona, 0) + delta
        save_child_profile(profile)

    return {
        "tutor_response": tutor_output,
        "referee_directive": referee_output,
        "phase": new_phase,
        "persona_used": selected_persona,
        "emotion": verdict.get("emotion", "NONE"),
        "prev_persona_signal": prev_signal,
    }


# ---------------------------------------------------------------------------
# CLI テスト用エントリポイント
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  Toy Alchemy v2 - Agent Pool + Explain-to-Learn")
    print("=" * 60)

    test_profile = {
        "child_id": "test_child_001",
        "display_name": "ゆうき",
        "grade": "小学6年生",
        "learning_preferences": ["ゲームの例えが好き", "図を使った説明が好き"],
        "error_patterns": [
            {"subject": "算数", "description": "円の面積で直径をそのまま使ってしまう"}
        ],
        "strengths": ["かけ算九九は完璧"],
        "session_history": [],
    }
    save_child_profile(test_profile)

    result = run_tutoring_session(
        child_id="test_child_001",
        child_message="円の面積がわからない...",
    )

    print(f"\n【ペルソナ】{PERSONAS[result['persona_used']]['name']}")
    print(f"【フェーズ】{result['phase']}")
    print(f"【返答】\n{result['tutor_response']}")
    print(f"\n【Referee】\n{result['referee_directive']}")
