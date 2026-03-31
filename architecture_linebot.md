# Toy Alchemy - LINE Bot 連携アーキテクチャ設計

## 概要

子供がLINEで宿題の写真と質問を送ると、画像認識 → マルチエージェント推論 → 音声合成を経て、
フクロウ先生がテキストと音声で応答する。本ドキュメントはフェーズ2以降の実装ガイドとなる。

---

## システム全体のシーケンス図

```mermaid
sequenceDiagram
    participant Child as 子供（LINE）
    participant LINE as LINE Platform
    participant Bot as LINE Bot Server<br/>(FastAPI)
    participant Store as Cloud Storage<br/>(S3 / GCS)
    participant Vision as 画像認識<br/>(GPT-4o Vision)
    participant Memory as メモリDB<br/>(DynamoDB / Firestore)
    participant Crew as CrewAI Engine<br/>(Referee + Tutor)
    participant TTS as 音声合成<br/>(OpenAI TTS / ElevenLabs)

    Note over Child, TTS: 【フェーズ1】宿題の写真を送信 → フクロウ先生が応答

    Child->>LINE: 宿題の写真 📷 +<br/>「ここがわからない」
    LINE->>Bot: Webhook Event<br/>(image + text message)

    Note over Bot: 1. メッセージ受信・解析

    Bot->>Bot: イベント種別を判定<br/>(画像 / テキスト / スタンプ)
    Bot->>Store: 画像をアップロード
    Store-->>Bot: 画像URL

    Note over Bot: 2. 画像認識（OCR + 問題理解）

    Bot->>Vision: 画像URL +<br/>「この宿題の内容を読み取って」
    Vision-->>Bot: 認識結果<br/>(問題文テキスト + 数式 + 図の説明)

    Note over Bot: 3. 子供プロファイル読み込み

    Bot->>Memory: get_profile(user_id)
    Memory-->>Bot: 子供の学習プロファイル<br/>(得意/苦手/好みのアプローチ)

    Note over Bot: 4. CrewAIマルチエージェント推論

    Bot->>Crew: run_tutoring_session(<br/>  child_id,<br/>  question + OCR結果,<br/>  profile,<br/>  conversation_history<br/>)

    Note over Crew: Referee が教育方針を決定
    Crew->>Crew: RefereeAgent 分析<br/>「繰り上がりの概念が未定着。<br/>ブロックに例えて考えさせよ」

    Note over Crew: Tutor が子供向け応答を生成
    Crew->>Crew: TutorAgent 応答生成<br/>「ゆうきくん、27を<br/>ブロックで考えてみよう！」

    Crew-->>Bot: {<br/>  tutor_response,<br/>  referee_directive<br/>}

    Note over Bot: 5. 音声合成

    Bot->>TTS: tutor_response テキスト +<br/>音声設定（明るい子供向け声）
    TTS-->>Bot: 音声ファイル (MP3)
    Bot->>Store: 音声ファイルをアップロード
    Store-->>Bot: 音声URL

    Note over Bot: 6. LINE返信

    Bot->>LINE: Reply Message API<br/>(テキスト + 音声メッセージ)
    LINE->>Child: 💬 テキスト返信<br/>「ゆうきくん、27をブロックで<br/>考えてみよう！20のかたまりと...」
    LINE->>Child: 🔊 音声メッセージ<br/>（フクロウ先生の声）

    Note over Bot: 7. セッション記録

    Bot->>Memory: update_profile(<br/>  session_log,<br/>  error_patterns更新<br/>)

    Note over Child, TTS: 【繰り返し】子供が返答 → フクロウ先生が次の問いかけ

    Child->>LINE: 「えっと...42？」
    LINE->>Bot: Webhook (text)
    Bot->>Memory: get_profile + conversation_history
    Memory-->>Bot: プロファイル + 会話履歴
    Bot->>Crew: run_tutoring_session(<br/>  継続セッション<br/>)
    Crew-->>Bot: 「惜しい！もう一回<br/>ブロックを数えてみよう」
    Bot->>TTS: テキスト→音声
    TTS-->>Bot: 音声ファイル
    Bot->>LINE: Reply (テキスト + 音声)
    LINE->>Child: フクロウ先生の応答
```

---

## コンポーネント詳細

### 1. LINE Bot Server（FastAPI）

| 項目 | 内容 |
|------|------|
| フレームワーク | FastAPI + line-bot-sdk (v3) |
| ホスティング | AWS Lambda + API Gateway / Cloud Run |
| 役割 | Webhook受信、各サービスのオーケストレーション |

**主要エンドポイント:**

```
POST /webhook    … LINE Webhookイベント受信
GET  /health     … ヘルスチェック
```

**処理フロー（擬似コード）:**

```python
@app.post("/webhook")
async def handle_webhook(request: Request):
    events = parse_webhook(request)

    for event in events:
        user_id = event.source.user_id

        # 画像メッセージの場合
        if event.message.type == "image":
            image_url = upload_to_storage(event.message)
            ocr_result = await vision_recognize(image_url)
            store_context(user_id, ocr_result)

        # テキストメッセージの場合
        if event.message.type == "text":
            profile = load_child_profile(user_id)
            history = get_conversation_history(user_id)
            context = get_stored_context(user_id)  # OCR結果があれば結合

            result = run_tutoring_session(
                child_id=user_id,
                child_message=event.message.text + context,
                conversation_history=history,
            )

            audio_url = await synthesize_speech(result["tutor_response"])

            await reply(event, [
                TextMessage(text=result["tutor_response"]),
                AudioMessage(original_content_url=audio_url),
            ])

            save_session_log(user_id, event.message.text, result)
```

### 2. 画像認識（Vision API）

| 項目 | 内容 |
|------|------|
| API | OpenAI GPT-4o（Vision機能） |
| 入力 | 宿題の写真（手書きノート、プリント等） |
| 出力 | 問題文テキスト、数式、図の説明 |

**プロンプト設計のポイント:**
- 手書き文字のOCR精度を上げるため、「小学生の手書き」であることを明示
- 数式はLaTeX形式ではなく平文で出力（CrewAIに渡しやすくするため）
- 図がある場合は「何が描かれているか」を自然言語で説明

### 3. メモリDB

| 項目 | 内容 |
|------|------|
| サービス | DynamoDB / Firestore（どちらでも可） |
| パーティションキー | `child_id`（= LINE ユーザーID） |
| データ | `memory_schema.json` に準拠 |

**MVP段階ではJSON ファイルベース**（`src/memory/` ディレクトリ）で十分。
ユーザー数が増えた段階でDBに移行する。

### 4. 音声合成（TTS）

| 項目 | 内容 |
|------|------|
| 第1候補 | OpenAI TTS API（`tts-1-hd`, voice: `nova`） |
| 第2候補 | ElevenLabs（カスタム声が作れる） |
| 出力形式 | MP3（LINE AudioMessageが対応） |

**音声キャラ設定:**
- 明るく優しいトーン
- 話速はやや遅め（子供が聞き取りやすい）
- 将来的にElevenLabsでフクロウ先生専用の声を作成

### 5. 会話履歴管理

**LINE Bot固有の考慮事項:**
- LINEのReply APIはイベントごとに1回しか返信できない
- 会話の「セッション」はサーバー側で管理（30分無操作でセッション終了）
- 会話履歴は直近10往復を保持し、CrewAIに注入

---

## 環境変数

```env
# LINE Bot
LINE_CHANNEL_SECRET=xxx
LINE_CHANNEL_ACCESS_TOKEN=xxx

# OpenAI (Vision + TTS)
OPENAI_API_KEY=xxx

# Cloud Storage
STORAGE_BUCKET=toy-alchemy-media

# メモリDB (本番用)
DYNAMODB_TABLE=toy-alchemy-profiles
```

---

## フェーズ別ロードマップ

| フェーズ | 内容 | 状態 |
|----------|------|------|
| **1. コアエンジン** | CrewAI Tutor+Referee 連携 | ✅ 完了 |
| **2. LINE Bot 基盤** | Webhook受信、テキスト対話 | 🔜 次回 |
| **3. 画像認識統合** | 宿題写真 → OCR → エンジン | 📋 計画中 |
| **4. 音声合成統合** | テキスト → 音声 → LINE返信 | 📋 計画中 |
| **5. メモリDB移行** | JSON → DynamoDB/Firestore | 📋 計画中 |
| **6. 保護者ダッシュボード** | 学習レポート、設定画面 | 💡 構想 |
