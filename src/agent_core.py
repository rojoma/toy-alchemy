"""
Toy Alchemy - AI家庭教師コアエンジン
CrewAIによるマルチエージェント基盤（TutorAgent + RefereeAgent）

フクロウ先生が子供の概念理解を促すソクラテス的問答を行い、
RefereeAgentが裏から教育方針をディレクションする。
"""

import json
import os
from pathlib import Path
from textwrap import dedent

from crewai import Agent, Crew, Process, Task

# ---------------------------------------------------------------------------
# メモリ（子供の学習プロファイル）読み込み
# ---------------------------------------------------------------------------

MEMORY_DIR = Path(__file__).parent / "memory"


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
        recent_errors = profile["error_patterns"][-5:]  # 直近5件
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
# エージェント定義
# ---------------------------------------------------------------------------


def create_referee_agent(model: str = "gpt-4o") -> Agent:
    """
    RefereeAgent（監視役・監督）

    子供とTutorのやり取りを俯瞰し、Tutorの教え方を裏からディレクションする。
    子供には直接話しかけず、Tutorへの指示書を出す。
    """
    return Agent(
        role="教育ディレクター（Referee）",
        goal=dedent("""\
            子供の理解度と感情状態を分析し、TutorAgentが最適な問いかけを
            行えるよう具体的な指示を出す。答えを教えさせない。概念理解を最優先する。
        """),
        backstory=dedent("""\
            あなたは30年の経験を持つベテラン教育コンサルタントです。
            子供の認知発達理論（ピアジェ、ヴィゴツキー）に精通し、
            「最近接発達領域（ZPD）」を見極めて適切な足場かけ（scaffolding）を
            設計するのが専門です。

            あなたは子供と直接話しません。Tutorへの「指示メモ」を書きます。
            指示メモには以下を含めてください：
            1. 子供の現在の理解度の診断（何がわかっていて何がわかっていないか）
            2. 次にTutorが使うべき教授法（比喩、図解、具体例、ゲーム化など）
            3. 絶対に避けるべきこと（答えを直接言う、手順だけ教える等）
            4. 子供の感情面への配慮（励まし方、ペース調整）
        """),
        verbose=True,
        allow_delegation=False,
        llm=model,
    )


def create_tutor_agent(model: str = "gpt-4o") -> Agent:
    """
    TutorAgent（教える役・フクロウ先生）

    ソクラテス的問答法で子供の概念理解を促す。
    一切答えを教えず、問いかけで子供自身が気づけるよう導く。
    """
    return Agent(
        role="フクロウ先生（Tutor）",
        goal=dedent("""\
            子供が自分の力で答えにたどり着けるよう、優しく楽しい問いかけで導く。
            絶対に答えそのものを教えない。子供の「わかった！」という瞬間を作る。
        """),
        backstory=dedent("""\
            あなたは「フクロウ先生」という名前の、子供たちに大人気のAI家庭教師です。
            ふわふわで可愛いフクロウのキャラクターとして話します。

            【話し方のルール】
            - 一人称は「先生」または「フクロウ先生」
            - 語尾は「～だよ」「～かな？」「～してみよう！」など親しみやすく
            - 子供の名前がわかれば名前で呼ぶ
            - 難しい言葉は使わず、小学生でもわかる表現で
            - 適度に「すごいね！」「いい質問だね！」と褒める
            - 1回の返答は3〜5文程度に収める（長すぎると子供は飽きる）

            【教え方のルール】
            - 答えを絶対に言わない
            - 「なぜそう思う？」「もし〇〇だったらどうなる？」と問いかける
            - 子供の身近なもの（お菓子、ゲーム、動物など）に例える
            - 間違えても「惜しい！」「いい線いってる！」とポジティブに返す
            - RefereeAgentからの指示メモに従って教授法を調整する
        """),
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
    """RefereeAgentが教育方針を決定するタスク。"""
    return Task(
        description=dedent(f"""\
            以下の情報をもとに、TutorAgent（フクロウ先生）への指示メモを作成してください。

            {child_profile_text}

            【子供からの質問・メッセージ】
            {child_question}

            【これまでの会話履歴】
            {conversation_history if conversation_history else "（初回の質問です）"}

            【あなたの出力】
            TutorAgentへの指示メモを以下の形式で出力してください：
            - 理解度診断: ...
            - 推奨する教授法: ...
            - 避けるべきこと: ...
            - 感情面の配慮: ...
            - 具体的な問いかけ例（2〜3個）: ...
        """),
        expected_output="TutorAgentへの具体的な指示メモ（日本語）",
        agent=agent,
    )


def create_tutor_task(
    agent: Agent,
    child_question: str,
    child_profile_text: str,
    referee_task: Task,
    conversation_history: str = "",
) -> Task:
    """TutorAgentが子供に返答するタスク。Refereeの指示を受けて実行。"""
    return Task(
        description=dedent(f"""\
            あなたはフクロウ先生です。以下の情報と、教育ディレクターからの指示メモを
            参考にして、子供への返答を作成してください。

            {child_profile_text}

            【子供からの質問・メッセージ】
            {child_question}

            【これまでの会話履歴】
            {conversation_history if conversation_history else "（初回の質問です）"}

            【重要ルール】
            - 教育ディレクターの指示メモに従うこと
            - 答えを絶対に教えないこと
            - 3〜5文で返答すること
            - 必ず問いかけで終わること
        """),
        expected_output="フクロウ先生として子供に語りかける返答（日本語、3〜5文）",
        agent=agent,
        context=[referee_task],  # Refereeの出力を参照
    )


# ---------------------------------------------------------------------------
# Crew（エージェント連携）の実行
# ---------------------------------------------------------------------------


def run_tutoring_session(
    child_id: str,
    child_message: str,
    conversation_history: str = "",
    model: str = "gpt-4o",
) -> dict:
    """
    家庭教師セッションを実行する。

    1. 子供のプロファイルを読み込む
    2. RefereeAgentが教育方針を決定
    3. TutorAgentがRefereeの指示に基づき返答を生成
    4. 結果を返す

    Args:
        child_id: 子供の識別子（LINE ユーザーIDなど）
        child_message: 子供からのメッセージ（テキスト or OCR結果）
        conversation_history: これまでの会話履歴
        model: 使用するLLMモデル名

    Returns:
        dict: {
            "tutor_response": フクロウ先生の返答,
            "referee_directive": Refereeの指示メモ（デバッグ/ログ用）,
        }
    """
    # プロファイル読み込み
    profile = load_child_profile(child_id)
    profile_text = format_profile_for_prompt(profile)

    # エージェント作成
    referee = create_referee_agent(model=model)
    tutor = create_tutor_agent(model=model)

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
        "grade": "小学3年生",
        "learning_preferences": ["ゲームの例えが好き", "図を使った説明が好き"],
        "error_patterns": [
            {
                "subject": "算数",
                "description": "繰り上がりのある足し算で、繰り上がりを忘れることがある",
            }
        ],
        "strengths": ["かけ算九九は完璧", "図形の名前をよく覚えている"],
        "session_history": [],
    }
    save_child_profile(test_profile)

    # テスト実行
    test_message = "27 + 15 がわからない..."

    print(f"子供のメッセージ: {test_message}")
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
    print("【Refereeの指示メモ（裏側）】")
    print(result["referee_directive"])
