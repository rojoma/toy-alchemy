"""
Toy Alchemy - AI家庭教師コアエンジン
CrewAIによるマルチエージェント基盤（TutorAgent + RefereeAgent）

スキル定義はMarkdownファイル（skills/）として外部管理。
エンジンは子供のプロファイル（学年・教科）に応じて適切なスキルを読み込み、
エージェントを動的に構成する。
"""

import json
import re
from pathlib import Path
from textwrap import dedent

from crewai import Agent, Crew, Process, Task

# ---------------------------------------------------------------------------
# パス定義
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"
MEMORY_DIR = Path(__file__).parent / "memory"

# ---------------------------------------------------------------------------
# スキル読み込み
# ---------------------------------------------------------------------------

# 学年・教科 → スキルファイルのマッピング
# キー: (学年プレフィックス, 教科) → ファイル名
# 該当なしの場合は general.md にフォールバック
TUTOR_SKILL_MAP = {
    ("小学6", "算数"): "edu6th_math.md",
    ("小学6", "math"): "edu6th_math.md",
    # 今後追加:
    # ("小学5", "算数"): "edu5th_math.md",
    # ("小学6", "理科"): "edu6th_science.md",
    # ("中学1", "数学"): "edu7th_math.md",
}


def load_skill(skill_path: Path) -> str:
    """Markdownスキルファイルを読み込んで文字列として返す。"""
    if not skill_path.exists():
        raise FileNotFoundError(f"スキルファイルが見つかりません: {skill_path}")
    return skill_path.read_text(encoding="utf-8")


def resolve_tutor_skill(grade: str | None, subject: str | None) -> str:
    """
    子供の学年と教科から適切なTutorスキルファイルを選択して読み込む。

    マッチングロジック:
    1. 学年プレフィックス + 教科で完全一致を探す
    2. 学年不明でも教科だけでマッチを試みる（教科特化 > 汎用）
    3. 見つからなければ general.md にフォールバック
    """
    # 1. 学年 + 教科で完全一致
    if grade and subject:
        for (grade_prefix, subj), filename in TUTOR_SKILL_MAP.items():
            if grade.startswith(grade_prefix) and subject == subj:
                skill_path = SKILLS_DIR / "tutor" / filename
                if skill_path.exists():
                    return load_skill(skill_path)

    # 2. 学年不明でも教科だけでマッチ（最初に見つかった教科特化スキルを使用）
    if subject:
        for (grade_prefix, subj), filename in TUTOR_SKILL_MAP.items():
            if subject == subj:
                skill_path = SKILLS_DIR / "tutor" / filename
                if skill_path.exists():
                    return load_skill(skill_path)

    # 3. フォールバック: 汎用スキル
    return load_skill(SKILLS_DIR / "tutor" / "general.md")


def load_referee_skill() -> str:
    """Refereeのベーススキルを読み込む。"""
    return load_skill(SKILLS_DIR / "referee" / "referee_base.md")


def detect_subject(message: str) -> str | None:
    """子供のメッセージから教科を推定する。"""
    math_keywords = [
        "算数", "数学", "計算", "足し算", "引き算", "かけ算", "割り算",
        "分数", "小数", "面積", "体積", "速さ", "割合", "比",
        "+", "-", "×", "÷", "=",
    ]
    # 数式パターン（数字 + 演算子 + 数字）
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
    """子供の学習プロファイルをJSONから読み込む。存在しなければ空のプロファイルを返す。"""
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
    """子供の学習プロファイルをJSONに保存する。"""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    profile_path = MEMORY_DIR / f"{profile['child_id']}.json"
    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


def format_profile_for_prompt(profile: dict) -> str:
    """プロファイルをエージェントへ注入するプロンプト文字列に変換する。"""
    if not profile.get("display_name"):
        return "（この子供のプロファイル情報はまだありません。初回セッションです。）"

    parts = [f"【生徒プロファイル: {profile['display_name']}】"]

    if profile.get("grade"):
        parts.append(f"- 学年: {profile['grade']}")

    if profile.get("learning_preferences"):
        prefs = "、".join(profile["learning_preferences"])
        parts.append(f"- 好きな学び方: {prefs}")

    if profile.get("error_patterns"):
        recent_errors = profile["error_patterns"][-5:]
        for ep in recent_errors:
            parts.append(
                f"- 過去の間違いパターン [{ep.get('subject', '不明')}]: "
                f"{ep.get('description', '')}"
            )

    if profile.get("strengths"):
        strengths = "、".join(profile["strengths"])
        parts.append(f"- 得意なこと: {strengths}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# エージェント定義（スキルファイルから動的生成）
# ---------------------------------------------------------------------------


def create_referee_agent(model: str = "gpt-4o") -> Agent:
    """RefereeAgent: スキルファイルから構造化された評価基準を読み込んで生成。"""
    referee_skill = load_referee_skill()

    return Agent(
        role="教育ディレクター（Referee）",
        goal=dedent("""\
            Tutor Agentの返答を6つのスキルで評価し、構造化されたディレクティブを出す。
            学習を害する返答（答えの提示、低品質な教授法）を絶対に通さない。
        """),
        backstory=referee_skill,
        verbose=True,
        allow_delegation=False,
        llm=model,
    )


def create_tutor_agent(
    grade: str | None,
    subject: str | None,
    model: str = "gpt-4o",
) -> Agent:
    """TutorAgent: 学年・教科に応じたスキルファイルを読み込んで生成。"""
    tutor_skill = resolve_tutor_skill(grade, subject)

    return Agent(
        role="フクロウ先生（Tutor）",
        goal=dedent("""\
            子供が自分の力で答えにたどり着けるよう、スキル定義に従った教授法で導く。
            絶対に答えそのものを教えない。子供の「わかった！」という瞬間を作る。
        """),
        backstory=tutor_skill,
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
) -> Task:
    """RefereeAgentがTutorの返答方針を決定するタスク。"""
    return Task(
        description=dedent(f"""\
            以下の情報をもとに、Tutor Agentへの構造化ディレクティブを作成してください。
            あなたのスキル定義に記載された6つの評価基準すべてを適用してください。

            {child_profile_text}

            【子供からの質問・メッセージ】
            {child_question}

            【これまでの会話履歴】
            {conversation_history if conversation_history else "（初回の質問です）"}

            【出力形式】
            REFEREE_VERDICT {{
              skill_1_accuracy: PASS | LOGICAL_ERROR | ARITHMETIC_ERROR | NEEDS_REVIEW
              skill_2_pedagogy: PASS | PEDAGOGY_VIOLATION | IMPROVE_SPECIFICITY
              skill_3_crutch: PASS | CRUTCH_DETECTED | REDIRECT_TO_ENGAGEMENT
              skill_4_emotion: NONE | GENTLE_ENCOURAGEMENT | EMOTIONAL_CARE_PRIORITY | GENTLE_REDIRECT
              skill_5_grade_level: PASS | GRADE_LEVEL_MISMATCH
              skill_6_format: PASS | FORMAT_TOO_LONG | MULTIPLE_QUESTIONS
              overall: APPROVED | BLOCKED | FLAGGED_FOR_REVISION
              directive_to_tutor: [具体的な指示: どの教授法を使うべきか、何を避けるべきか、感情ケアが必要か]
            }}
        """),
        expected_output="REFEREE_VERDICT形式の構造化ディレクティブ（日本語の指示を含む）",
        agent=agent,
    )


def create_tutor_task(
    agent: Agent,
    child_question: str,
    child_profile_text: str,
    referee_task: Task,
    conversation_history: str = "",
) -> Task:
    """TutorAgentが子供に返答するタスク。Refereeのディレクティブに従う。"""
    return Task(
        description=dedent(f"""\
            あなたはスキル定義に記載されたキャラクターです。
            以下の情報と、Refereeからのディレクティブを参考にして、子供への返答を作成してください。

            {child_profile_text}

            【子供からの質問・メッセージ】
            {child_question}

            【これまでの会話履歴】
            {conversation_history if conversation_history else "（初回の質問です）"}

            【重要ルール】
            - Refereeのディレクティブに従うこと
            - 答えを絶対に教えないこと
            - 最大3文で返答すること（4文以上は禁止）
            - 質問は1つだけにすること（複数の質問を同時にしない）
            - 必ず問いかけで終わること
            - スキル定義に記載されたキャラクターの話し方・教え方に忠実に従うこと
        """),
        expected_output="スキル定義のキャラクターとして子供に語りかける返答（日本語、最大3文、質問は1つだけ）",
        agent=agent,
        context=[referee_task],
    )


# ---------------------------------------------------------------------------
# Crew（エージェント連携）の実行
# ---------------------------------------------------------------------------


def run_tutoring_session(
    child_id: str,
    child_message: str,
    conversation_history: str = "",
    model: str = "gpt-4o",
    subject_override: str | None = None,
) -> dict:
    """
    家庭教師セッションを実行する。

    1. 子供のプロファイルを読み込む
    2. 教科を決定（明示指定 > メッセージ推定）
    3. 学年×教科に応じた特化型Tutorスキルを選択
    4. RefereeAgentが構造化ディレクティブを生成
    5. TutorAgentがディレクティブに基づき返答を生成
    """
    # プロファイル読み込み
    profile = load_child_profile(child_id)
    profile_text = format_profile_for_prompt(profile)

    # 教科決定（明示指定を優先、なければメッセージから推定）
    subject = subject_override or detect_subject(child_message)
    grade = profile.get("grade")

    # エージェント作成（スキルファイルから動的生成）
    referee = create_referee_agent(model=model)
    tutor = create_tutor_agent(grade=grade, subject=subject, model=model)

    # タスク作成（Referee → Tutor の順序で連携）
    referee_task = create_referee_task(
        agent=referee,
        child_question=child_message,
        child_profile_text=profile_text,
        conversation_history=conversation_history,
    )
    tutor_task = create_tutor_task(
        agent=tutor,
        child_question=child_message,
        child_profile_text=profile_text,
        referee_task=referee_task,
        conversation_history=conversation_history,
    )

    # Crew実行（sequential: Referee → Tutor）
    crew = Crew(
        agents=[referee, tutor],
        tasks=[referee_task, tutor_task],
        process=Process.sequential,
        verbose=True,
    )

    result = crew.kickoff()

    return {
        "tutor_response": result.tasks_output[1].raw,
        "referee_directive": result.tasks_output[0].raw,
    }


# ---------------------------------------------------------------------------
# CLI テスト用エントリポイント
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  Toy Alchemy - フクロウ先生 AI家庭教師（テストモード）")
    print("=" * 60)
    print()

    # テスト用の子供プロファイルを作成
    test_profile = {
        "child_id": "test_child_001",
        "display_name": "ゆうき",
        "grade": "小学6年生",
        "learning_preferences": ["ゲームの例えが好き", "図を使った説明が好き"],
        "error_patterns": [
            {
                "subject": "算数",
                "description": "円の面積で直径をそのまま使ってしまう",
            }
        ],
        "strengths": ["かけ算九九は完璧", "図形の名前をよく覚えている"],
        "session_history": [],
    }
    save_child_profile(test_profile)

    # テスト実行
    test_message = "円の面積がわからない..."

    print(f"子供のメッセージ: {test_message}")
    print(f"検出された教科: {detect_subject(test_message)}")
    print(f"選択されたスキル: {resolve_tutor_skill(test_profile['grade'], detect_subject(test_message))[:50]}...")
    print("-" * 60)

    result = run_tutoring_session(
        child_id="test_child_001",
        child_message=test_message,
    )

    print()
    print("=" * 60)
    print("【フクロウ先生の返答】")
    print(result["tutor_response"])
    print()
    print("【Refereeのディレクティブ（裏側）】")
    print(result["referee_directive"])
