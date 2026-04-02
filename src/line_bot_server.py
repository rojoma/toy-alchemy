"""
Toy Alchemy - LINE Bot Server（テキストのみMVP）

FastAPI + line-bot-sdk v3 による Webhook サーバー。
子供からのテキストメッセージを受け取り、CrewAIエンジンで処理して返信する。

起動方法:
    uvicorn src.line_bot_server:app --reload --port 8000

ローカル開発時は ngrok 等で公開URLを作り、LINE Developersの Webhook URL に設定する:
    ngrok http 8000
    → https://xxxx.ngrok-free.app/webhook を LINE Developers Console に登録
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from src.conversation_store import ConversationStore
from src.agent_core import run_tutoring_session, load_child_profile, save_child_profile

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

load_dotenv()

LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("toy-alchemy")

# ---------------------------------------------------------------------------
# グローバルオブジェクト
# ---------------------------------------------------------------------------

conversation_store = ConversationStore(session_timeout_minutes=30)

parser = WebhookParser(channel_secret=LINE_CHANNEL_SECRET)

api_config = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)


# ---------------------------------------------------------------------------
# FastAPI アプリ
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Toy Alchemy LINE Bot Server を起動しました 🦉")
    yield
    logger.info("サーバーを停止します")


app = FastAPI(
    title="Toy Alchemy - フクロウ先生 LINE Bot",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "toy-alchemy"}


@app.post("/webhook")
async def webhook(request: Request):
    """LINE Webhook エンドポイント。"""
    signature = request.headers.get("X-Line-Signature", "")
    body = (await request.body()).decode("utf-8")

    # 署名検証 & イベント解析
    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 各イベントを処理
    for event in events:
        if not isinstance(event, MessageEvent):
            continue
        if not isinstance(event.message, TextMessageContent):
            # テキスト以外（画像・スタンプ等）は Phase3 以降で対応
            await _reply_text(
                event.reply_token,
                "ごめんね、今はテキストメッセージだけ対応しているよ！"
                "文字で質問を送ってみてね 🦉",
            )
            continue

        await _handle_text_message(event)

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# メッセージ処理
# ---------------------------------------------------------------------------

async def _handle_text_message(event: MessageEvent):
    """テキストメッセージを処理してフクロウ先生の返答を返す。"""
    user_id = event.source.user_id
    user_text = event.message.text.strip()

    logger.info(f"[{user_id}] 受信: {user_text}")

    # 特殊コマンド
    if user_text in ("/reset", "リセット"):
        conversation_store.clear_session(user_id)
        await _reply_text(
            event.reply_token,
            "会話をリセットしたよ！新しい質問をどうぞ 🦉",
        )
        return

    if user_text in ("/profile", "プロフィール"):
        profile = load_child_profile(user_id)
        if profile.get("display_name"):
            await _reply_text(
                event.reply_token,
                f"名前: {profile['display_name']}\n"
                f"学年: {profile.get('grade', '未設定')}\n"
                f"好きな学び方: {', '.join(profile.get('learning_preferences', []))}",
            )
        else:
            await _reply_text(
                event.reply_token,
                "まだプロフィールが登録されていないよ。\n"
                "「名前は〇〇」「小学〇年生」と教えてね！",
            )
        return

    # プロフィール設定の簡易パース
    profile_updated = _try_update_profile(user_id, user_text)
    if profile_updated:
        await _reply_text(event.reply_token, profile_updated)
        return

    # --- メイン処理: CrewAI で返答生成 ---

    # 会話履歴に子供のメッセージを追加
    conversation_store.add_child_message(user_id, user_text)
    history = conversation_store.get_history(user_id)

    try:
        result = run_tutoring_session(
            child_id=user_id,
            child_message=user_text,
            conversation_history=history,
        )
        tutor_response = result["tutor_response"]
    except Exception as e:
        logger.error(f"[{user_id}] CrewAI エラー: {e}", exc_info=True)
        tutor_response = (
            "ごめんね、フクロウ先生がちょっと考え中だよ。"
            "もう一回メッセージを送ってみてね！"
        )

    # 会話履歴にTutorの返答を追加
    conversation_store.add_tutor_response(user_id, tutor_response)

    logger.info(f"[{user_id}] 返信: {tutor_response}")

    await _reply_text(event.reply_token, tutor_response)


# ---------------------------------------------------------------------------
# プロフィール簡易設定
# ---------------------------------------------------------------------------

def _try_update_profile(user_id: str, text: str) -> str | None:
    """
    メッセージから名前・学年を検出してプロファイルを更新する。
    更新した場合は確認メッセージを返す。更新しなければ None。
    """
    import re

    profile = load_child_profile(user_id)
    updated = False
    reply_parts = []

    # 名前の検出: 「名前は〇〇」「〇〇だよ」「〇〇です」
    name_match = re.search(r"名前[はわ]\s*(.{1,10})", text)
    if name_match:
        name = name_match.group(1).strip().rstrip("だよですでーす。、")
        profile["display_name"] = name
        reply_parts.append(f"{name}さんだね！よろしくね！")
        updated = True

    # 学年の検出: 「小学3年生」「小3」「中学1年」
    grade_match = re.search(r"(小学?|中学?)\s*(\d)\s*年生?", text)
    if grade_match:
        level = "小学" if "小" in grade_match.group(1) else "中学"
        num = grade_match.group(2)
        grade = f"{level}{num}年生"
        profile["grade"] = grade
        reply_parts.append(f"{grade}なんだね！")
        updated = True

    if updated:
        save_child_profile(profile)
        return " ".join(reply_parts) + " 🦉"

    return None


# ---------------------------------------------------------------------------
# LINE 返信ヘルパー
# ---------------------------------------------------------------------------

async def _reply_text(reply_token: str, text: str) -> None:
    """LINE にテキストメッセージを返信する。"""
    with ApiClient(api_config) as client:
        api = MessagingApi(client)
        api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)],
            )
        )


# ---------------------------------------------------------------------------
# 直接実行
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
