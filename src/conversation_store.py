"""
Toy Alchemy - 会話履歴管理

LINEユーザーごとの会話履歴を管理する。
セッション（一定時間操作がなければ自動終了）の概念を持つ。
MVP段階ではインメモリで管理し、サーバー再起動で消える前提。
"""

from datetime import datetime, timedelta
from dataclasses import dataclass, field


@dataclass
class Message:
    role: str  # "child" or "tutor"
    text: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Session:
    messages: list[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    selected_subject: str | None = None  # 選択された教科
    selecting_subject: bool = False  # 教科選択中フラグ

    def is_expired(self, timeout_minutes: int = 30) -> bool:
        return datetime.now() - self.last_active > timedelta(minutes=timeout_minutes)

    def add_message(self, role: str, text: str) -> None:
        self.messages.append(Message(role=role, text=text))
        self.last_active = datetime.now()

    def format_history(self, max_turns: int = 10) -> str:
        """直近の会話履歴をCrewAIに注入する文字列として整形する。"""
        recent = self.messages[-(max_turns * 2) :]  # 往復数 × 2
        if not recent:
            return ""
        lines = []
        for msg in recent:
            speaker = "子供" if msg.role == "child" else "フクロウ先生"
            lines.append(f"{speaker}: {msg.text}")
        return "\n".join(lines)


# 利用可能な教科メニュー
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


class ConversationStore:
    """
    ユーザーごとの会話セッションをインメモリで管理する。

    - セッションが30分無操作で自動期限切れ
    - 期限切れの場合は新しいセッションを開始
    """

    def __init__(self, session_timeout_minutes: int = 30):
        self._sessions: dict[str, Session] = {}
        self._timeout = session_timeout_minutes

    def get_session(self, user_id: str) -> Session:
        """ユーザーのアクティブなセッションを取得。期限切れなら新規作成。"""
        session = self._sessions.get(user_id)
        if session is None or session.is_expired(self._timeout):
            session = Session()
            self._sessions[user_id] = session
        return session

    def add_child_message(self, user_id: str, text: str) -> None:
        session = self.get_session(user_id)
        session.add_message("child", text)

    def add_tutor_response(self, user_id: str, text: str) -> None:
        session = self.get_session(user_id)
        session.add_message("tutor", text)

    def get_history(self, user_id: str, max_turns: int = 10) -> str:
        """CrewAIに渡すための会話履歴文字列を返す。"""
        session = self.get_session(user_id)
        return session.format_history(max_turns)

    def get_selected_subject(self, user_id: str) -> str | None:
        session = self.get_session(user_id)
        return session.selected_subject

    def set_selected_subject(self, user_id: str, subject: str) -> None:
        session = self.get_session(user_id)
        session.selected_subject = subject

    def is_selecting_subject(self, user_id: str) -> bool:
        session = self.get_session(user_id)
        return session.selecting_subject

    def start_subject_selection(self, user_id: str) -> None:
        session = self.get_session(user_id)
        session.selecting_subject = True

    def finish_subject_selection(self, user_id: str) -> None:
        session = self.get_session(user_id)
        session.selecting_subject = False

    def clear_session(self, user_id: str) -> None:
        self._sessions.pop(user_id, None)
