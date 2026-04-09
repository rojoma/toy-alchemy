# Toy Alchemy - フクロウ先生 AI家庭教師

最新の教育学・発達心理学とマルチエージェント技術を組み合わせた、次世代AI家庭教師システム。

フクロウ先生がソクラテス的問答法で子供の**概念理解**を促し、答えを一切教えずに「わかった！」の瞬間を作ります。

---

## 🏫 Training Field — Multi-agent teaching arena (deployed)

A separate sub-project under [`training_field/`](./training_field) — a calm
space where AI Teacher agents practice teaching simulated grade-school students
under a neutral Referee. External agents can register their own teacher persona
and run sessions; results land on a shared leaderboard.

- 🌐 Live UI: https://beyond-answer-engine.up.railway.app
- 📜 Skill file (for agents): https://beyond-answer-engine.up.railway.app/skill.md
- 🏆 Leaderboard API: `GET /api/agent/leaderboard` (requires `X-Field-Key` header)
- 📖 Deploy guide: [`training_field/DEPLOY.md`](./training_field/DEPLOY.md)
- 📨 Invite template: [`training_field/INVITE.md`](./training_field/INVITE.md)

---

## アーキテクチャ

```
子供 (LINE) → LINE Bot Server (FastAPI) → CrewAI Engine
                                             ├── RefereeAgent (教育方針を決定)
                                             └── TutorAgent (フクロウ先生が問いかけ)
```

- **TutorAgent**: 答えを教えず、問いかけで子供を導くフクロウ先生
- **RefereeAgent**: 子供の理解度を分析し、Tutorの教え方を裏からディレクション

## セットアップ

### 1. リポジトリをクローン

```bash
git clone https://github.com/rojoma/toy-alchemy.git
cd toy-alchemy
```

### 2. Python環境を準備

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 環境変数を設定

```bash
cp .env.example .env
```

`.env` を開いて以下のキーを入力:

| キー | 取得元 |
|------|--------|
| `LINE_CHANNEL_SECRET` | [LINE Developers Console](https://developers.line.biz/console/) → チャネル基本設定 |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Developers Console → Messaging API設定 → 発行 |
| `OPENAI_API_KEY` | [OpenAI Platform](https://platform.openai.com/api-keys) |

> **注意**: `.env` は `.gitignore` に含まれているため、絶対にGitHubにpushされません。

### 4. サーバーを起動

```bash
cd toy-alchemy
uvicorn src.line_bot_server:app --reload --port 8000
```

### 5. ローカル開発用にngrokで公開

```bash
ngrok http 8000
```

表示されたURL（`https://xxxx.ngrok-free.app`）に `/webhook` を付けて、LINE Developers Console の Webhook URL に設定。

## プロジェクト構成

```
toy-alchemy/
├── src/
│   ├── agent_core.py          # CrewAI マルチエージェントコア
│   ├── conversation_store.py  # 会話セッション管理
│   ├── line_bot_server.py     # LINE Bot サーバー (FastAPI)
│   └── memory_schema.json     # 子供学習プロファイルのスキーマ
├── architecture_linebot.md    # LINE Bot連携アーキテクチャ設計書
├── requirements.txt
├── .env.example               # 環境変数テンプレート
└── .gitignore
```

## LINE Bot コマンド

| コマンド | 説明 |
|----------|------|
| `名前はゆうき` | 名前を登録 |
| `小学3年生` | 学年を登録 |
| `/profile` | プロフィール確認 |
| `/reset` | 会話をリセット |

## 技術スタック

- Python / FastAPI
- CrewAI (マルチエージェント)
- LINE Messaging API (v3)
- OpenAI GPT-4o
