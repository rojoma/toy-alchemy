"""
Toy Alchemy - 会話履歴・状態管理

LINEユーザーごとの会話履歴、教科選択、学習フェーズ、ペルソナ選択を管理する。
MVP段階ではインメモリで管理し、サーバー再起動で消える前提。
"""

from datetime import datetime, timedelta
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# 学習フェーズ定義
# ---------------------------------------------------------------------------

PHASE_QUESTIONING = "questioning"  # Phase 1: ヒント＋説明を求める問いかけ
PHASE_EXPLAINING = "explaining"    # Phase 2: 子供が説明中 → 検証
PHASE_RESOLVED = "resolved"        # 解決済み → 次の問題へ


# ---------------------------------------------------------------------------
# ペルソナ定義（Agent Pool）
# ---------------------------------------------------------------------------

PERSONAS = {
    "standard": {
        "id": "standard",
        "name": "🦉 スタンダード先生",
        "description": "共感的で王道のソクラテス的問答。初回や状態不明時のデフォルト。",
        "style": (
            "あなたは「スタンダード先生」です。温かく共感的な口調で、"
            "子供の言葉を受け止めてから問いかけます。\n"
            "口調: 「〜だよね」「〜かな？」「一緒にやってみよう！」\n"
            "特徴: まず共感 → 身近な例え → 問いかけ\n"
            "一人称: 「先生」"
        ),
        "match_preferences": ["共感的", "優しい", "丁寧"],
    },
    "gamemaster": {
        "id": "gamemaster",
        "name": "⚔️ ゲームマスター先生",
        "description": "全てをRPGや冒険のパラメータに例える。ゲーム好きな子に最適。",
        "style": (
            "あなたは「ゲームマスター先生」です。全ての問題をRPGの冒険に例えます。\n"
            "口調: 「さあ冒険者よ！」「この問題はレベル3のモンスターだ！」"
            "「経験値ゲットだな！」\n"
            "特徴: 問題=モンスター、公式=必殺技、正解=レベルアップ、"
            "間違い=HPが減ったけどポーションで回復！\n"
            "一人称: 「俺」"
        ),
        "match_preferences": ["ゲーム", "RPG", "冒険", "ポケモン", "マイクラ"],
    },
    "artist": {
        "id": "artist",
        "name": "🎨 アート先生",
        "description": "ピザやブロックなど視覚的・直感的なメタファーを多用する。",
        "style": (
            "あなたは「アート先生」です。全てを絵や形、食べ物に例えて教えます。\n"
            "口調: 「想像してみて！」「絵に描くとこんな感じ！」"
            "「ピザで考えてみよう！」\n"
            "特徴: 常に視覚的なイメージを使う。ピザ、ケーキ、ブロック、折り紙など。\n"
            "一人称: 「先生」"
        ),
        "match_preferences": ["図", "絵", "視覚的", "イメージ", "お絵かき"],
    },
    "logic": {
        "id": "logic",
        "name": "🧩 ロジック先生",
        "description": "感情よりルールやパズルとして論理的に教える。理系脳の子向け。",
        "style": (
            "あなたは「ロジック先生」です。問題をパズルや謎解きとして論理的に教えます。\n"
            "口調: 「ルールはシンプルだよ」「ステップ1、ステップ2で解ける」"
            "「この法則に気づいた？」\n"
            "特徴: 手順を明確に、ルールベースで、パズル的な面白さを強調。\n"
            "一人称: 「僕」"
        ),
        "match_preferences": ["論理的", "パズル", "ルール", "手順", "なぜなぜ"],
    },
}

DEFAULT_PERSONA = "standard"


# ---------------------------------------------------------------------------
# データモデル
# ---------------------------------------------------------------------------

@dataclass
class Message:
    role: str  # "child" or "tutor"
    text: str
    timestamp: datetime = field(default_factory=datetime.now)
    persona_used: str | None = None  # Tutorの返答時にどのペルソナが担当したか


@dataclass
class Session:
    messages: list[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    selected_subject: str | None = None
    selecting_subject: bool = False
    current_phase: str = PHASE_QUESTIONING
    current_persona: str = DEFAULT_PERSONA
    persona_effectiveness: dict = field(default_factory=dict)  # {persona_id: score}

    def is_expired(self, timeout_minutes: int = 30) -> bool:
        return datetime.now() - self.last_active > timedelta(minutes=timeout_minutes)

    def add_message(self, role: str, text: str, persona_used: str | None = None) -> None:
        self.messages.append(Message(role=role, text=text, persona_used=persona_used))
        self.last_active = datetime.now()

    def format_history(self, max_turns: int = 10) -> str:
        """直近の会話履歴をCrewAIに注入する文字列として整形する。"""
        recent = self.messages[-(max_turns * 2) :]
        if not recent:
            return ""
        lines = []
        for msg in recent:
            speaker = "子供" if msg.role == "child" else "フクロウ先生"
            lines.append(f"{speaker}: {msg.text}")
        return "\n".join(lines)

    def record_persona_outcome(self, persona_id: str, positive: bool) -> None:
        """ペルソナの効果を記録する。"""
        current = self.persona_effectiveness.get(persona_id, 0)
        self.persona_effectiveness[persona_id] = current + (1 if positive else -1)


# ---------------------------------------------------------------------------
# 教科メニュー
# ---------------------------------------------------------------------------

SUBJECT_MENU = {
    "1": "算数",
    "2": "国語",
    "3": "理科",
    "4": "社会",
    "5": "その他",
}

SUBJECT_MENU_TEXT = (
    "どの教科をお手伝いしようかな？\n"
    "番号で教えてね！\n\n"
    "1️⃣ 算数\n"
    "2️⃣ 国語\n"
    "3️⃣ 理科\n"
    "4️⃣ 社会\n"
    "5️⃣ その他"
)


# ---------------------------------------------------------------------------
# ConversationStore
# ---------------------------------------------------------------------------

class ConversationStore:
    """ユーザーごとの会話セッション・状態をインメモリで管理する。"""

    def __init__(self, session_timeout_minutes: int = 30):
        self._sessions: dict[str, Session] = {}
        self._timeout = session_timeout_minutes

    def get_session(self, user_id: str) -> Session:
        session = self._sessions.get(user_id)
        if session is None or session.is_expired(self._timeout):
            session = Session()
            self._sessions[user_id] = session
        return session

    def add_child_message(self, user_id: str, text: str) -> None:
        session = self.get_session(user_id)
        session.add_message("child", text)

    def add_tutor_response(self, user_id: str, text: str, persona_used: str | None = None) -> None:
        session = self.get_session(user_id)
        session.add_message("tutor", text, persona_used=persona_used)

    def get_history(self, user_id: str, max_turns: int = 10) -> str:
        session = self.get_session(user_id)
        return session.format_history(max_turns)

    # --- 教科選択 ---
    def get_selected_subject(self, user_id: str) -> str | None:
        return self.get_session(user_id).selected_subject

    def set_selected_subject(self, user_id: str, subject: str) -> None:
        self.get_session(user_id).selected_subject = subject

    def is_selecting_subject(self, user_id: str) -> bool:
        return self.get_session(user_id).selecting_subject

    def start_subject_selection(self, user_id: str) -> None:
        self.get_session(user_id).selecting_subject = True

    def finish_subject_selection(self, user_id: str) -> None:
        self.get_session(user_id).selecting_subject = False

    # --- フェーズ管理 ---
    def get_phase(self, user_id: str) -> str:
        return self.get_session(user_id).current_phase

    def set_phase(self, user_id: str, phase: str) -> None:
        self.get_session(user_id).current_phase = phase

    # --- ペルソナ管理 ---
    def get_persona(self, user_id: str) -> str:
        return self.get_session(user_id).current_persona

    def set_persona(self, user_id: str, persona_id: str) -> None:
        self.get_session(user_id).current_persona = persona_id

    def record_persona_outcome(self, user_id: str, persona_id: str, positive: bool) -> None:
        self.get_session(user_id).record_persona_outcome(persona_id, positive)

    def get_persona_effectiveness(self, user_id: str) -> dict:
        return self.get_session(user_id).persona_effectiveness

    # --- セッション管理 ---
    def clear_session(self, user_id: str) -> None:
        self._sessions.pop(user_id, None)
