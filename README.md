# Toy Alchemy

AIエージェントが「教え方」を学習・実験するプラットフォーム + 子供向けAI家庭教師（LINE Bot）。

メインの実験場は **Training Field**（`training_field/`）。Railway上で稼働しており、誰でもブラウザから使えます。

🌐 **本番URL**: https://beyond-answer-engine.up.railway.app

---

## 👥 チームメンバー向けガイド

### 非エンジニアの方へ（daigo, mach）

コードを書かなくても貢献できます。以下の3つだけ覚えてください。

#### 1. 使う
ブラウザで https://beyond-answer-engine.up.railway.app を開く → そのまま使えます。

| 何をしたい？ | URL |
|---|---|
| AIエージェント同士の対話を観察 | トップページ → Observatory |
| 自分が生徒として学ぶ | トップページ → Start Learning |
| 過去のセッション履歴を見る | トップページ → View all |

#### 2. フィードバックする
気になった点があれば GitHub Issue で報告してください。
👉 https://github.com/rojoma/toy-alchemy/issues/new/choose

| 種類 | テンプレ |
|---|---|
| 先生の発言が変、判定がおかしい | 📝 セッションのフィードバック |
| 先生のキャラを変えたい、新しい先生を作りたい | 👩‍🏫 Teacher調整リクエスト |
| エラーが出る | 🐛 バグ報告 |
| 新しい機能がほしい | ✨ 新機能リクエスト |

スクリーンショットや実際の会話のコピペがあると最高に助かります。

#### 3. システムを知る
全体像はここに書いてあります → [`docs/architecture.md`](./docs/architecture.md)

---

### エンジニア向け

#### セットアップ

```bash
# 1. クローン
git clone https://github.com/rojoma/toy-alchemy.git
cd toy-alchemy

# 2. Python仮想環境
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r training_field/requirements.txt

# 3. 環境変数
cp .env.example .env
# .env を開いて OPENAI_API_KEY を設定

# 4. サーバー起動
uvicorn training_field.web.app:app --port 8765 --host 127.0.0.1 --reload
```

ブラウザで http://127.0.0.1:8765 を開く。

#### LINE Bot 側を動かす場合

```bash
uvicorn src.line_bot_server:app --reload --port 8000
ngrok http 8000
# 表示されたURL/webhook を LINE Developers Console に登録
```

`.env` に `LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN` も追加。

#### 開発フロー

```bash
git checkout main && git pull
git checkout -b feature/your-task
# 作業
git add . && git commit -m "何をしたか"
git push -u origin feature/your-task
# GitHubでPR作成 → レビュー → main へマージ
```

詳細は [`CONTRIBUTING.md`](./CONTRIBUTING.md) を参照。

#### コードを読む順番

1. [`docs/architecture.md`](./docs/architecture.md) — 全体像
2. `training_field/web/app.py` — APIエンドポイント
3. `training_field/teacher_agent.py` — Teacher AIの本体
4. `training_field/referee_agent.py` — 評価エージェント
5. `training_field/web/templates/` — UI

---

## 📁 リポジトリ構成

```
toy-alchemy/
├── training_field/         # ★メインの実験場（Railway デプロイ対象）
│   ├── web/                # FastAPIアプリ
│   ├── teacher_agent.py    # 教師AI
│   ├── student_agent.py    # 生徒AI
│   ├── referee_agent.py    # 審判AI
│   ├── teacher_memory.py   # セッション間記憶
│   └── field/              # 教師・スキル定義
├── src/                    # LINE Bot（旧）
├── docs/
│   └── architecture.md     # アーキテクチャドキュメント
├── tests/                  # テスト
├── .github/                # PR/Issueテンプレ
├── CONTRIBUTING.md         # 開発フロー
├── Procfile / nixpacks.toml # Railway デプロイ設定
└── requirements.txt
```

---

## 🚀 デプロイ

main ブランチへのpushで Railway が自動デプロイ。

- 設定: `Procfile` (web起動) + `nixpacks.toml` (Pythonビルド)
- 環境変数は Railway ダッシュボードで管理
- 永続データ（teacher_memory, reports等）は Railway Volume に保存

---

## 🔐 セキュリティ

- `.env` は **絶対にcommitしない**（`.gitignore`済み）
- APIキーをSlack/チャットに直接貼らない
- 学習者プロファイル (`reports/students/`) は個人情報相当として扱う

---

## 技術スタック

- Python 3.11 / FastAPI / Jinja2
- OpenAI GPT-4o
- バニラ JS (フレームワーク無し)
- Web Speech API (音声入力)
- Railway (デプロイ)

---

## ライセンス
（未設定）
