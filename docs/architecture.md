# Beyond Answer Engine / Training Field — システム概要

このドキュメントは初めての人向けに、Training Field（`training_field/` 配下）の構造を説明します。
最新の状態を知りたい場合は実コードを正としてください。

---

## 1. これは何か

**AIエージェントの「教え方」を学習・実験するためのプラットフォーム**。
教師AIエージェントが生徒（AI または 人間）に対して指導を行い、第三者の審判AI（Principal）が指導を評価する。評価結果を蓄積することで、教師AIが時間とともに改善していく仕組み。

---

## 2. 2つの利用モード

| モード | URL | 生徒 | 用途 |
|---|---|---|---|
| **Observatory** | `/` → `/session/{id}` | AI生徒（6種ペルソナ） | エージェント間の対話を観察・実験 |
| **Live (Classroom)** | `/learn` → `/learn/session` | 実在の人間 | 人間がAI教師から学ぶ |

---

## 3. エージェント構成

### Teacher Agent (`training_field/teacher_agent.py`)
- **Config（人格）**: 不変の dataclass。warmth, formality, patience, selected_skills など
- **Skills（教え方の道具）**: `field/skills/*.md` から動的読み込み（socratic, concrete, stepwise, visual, error_reframing, metacognitive）
- **Memory（学んだこと）**: `field/teacher_memory/{teacher_id}.json` に過去5セッションの教訓を蓄積、次セッションのプロンプトに自動注入
- 内部教師: Dr. Owen (t001)、外部教師: `field/external_teachers/*.json`（Warm Coach等）

### Student Agent (`training_field/student_agent.py`)
6種の生徒ペルソナ（Emma=不安型、Jake=衝動型、Priya=几帳面、Dylan=気分屋、Chloe=完璧主義、Ren=外部評価重視）。各々プロファイル習熟度・性格パラメータが異なる。

### Principal / Referee Agent (`training_field/referee_agent.py`)
中立評価者。各ターンで以下を評価：
- **ZPD alignment**: 生徒の発達領域に合っているか
- **Bloom level**: 認知レベル（記憶/理解/応用/分析/評価/創造）
- **Scaffolding quality**: 足場かけの質
- **Hallucination detected**: 嘘を教えていないか
- **Answer given directly**: 直接答えを言ってないか
- **Understanding delta**: 生徒の理解度の変化
- **Directive to teacher**: 次ターンへの改善指示

セッション終了時に `check_skills_update_trigger()` で総合判定し、必要なら `field/skills/proposals/` にスキル改訂提案を生成。

---

## 4. セッション構造（4フェーズ）

```
Diagnosis → Exploration → Practice → Reflection
```
深さ設定: Quick (8ターン) / Standard (12) / Deep (16)

Live モードのみ前後にテストが追加：
```
Pre-test (3問) → Teaching (4フェーズ) → Post-test (3問) → Review
```

---

## 5. データフロー（Live Sessionの例）

```
ユーザー学習開始
  ↓
/learn でオンボーディング（名前/学年/科目/教師選択）
  → POST /api/student/register → reports/students/{id}.json
  ↓
/learn/session 起動
  → POST /api/live/start
  → load_teacher() で TeacherAgent生成 + memoryをロード
  → LiveSession in-memory store に登録
  ↓
各ターン：POST /api/live/{id}/respond
  → Pre-test: judge → 次の問題
  → Teaching: Referee評価 → Teacher応答 → 次ターン
  → Post-test: judge → 次の問題
  ↓
セッション完了
  → Evaluator が総合評価
  → ExperimentRegistry に記録 (CSV)
  → reports/{session_id}_transcript.json に対話保存
  → teacher_memory/{teacher_id}.json に教訓追記
  → review カードで pre/post 比較表示
```

---

## 6. ファイル構成

```
training_field/
├── teacher_agent.py        # 教師AI本体（プロンプト構築）
├── student_agent.py        # 生徒AI（ペルソナ別）
├── referee_agent.py        # 審判AI（評価）
├── teacher_memory.py       # セッション間記憶
├── teacher_registry.py     # 教師の読み込み
├── evaluator.py            # 総合評価
├── experiment_registry.py  # CSV登録
├── proficiency_model.py    # 単元習熟度モデル
├── session_runner.py       # セッション制御
├── question_bank/          # テスト問題生成
├── field/
│   ├── skills/             # スキル定義 (.md) + proposals/
│   ├── external_teachers/  # 外部教師JSON
│   └── teacher_memory/     # 教師の経験記憶（runtime, gitignore）
├── reports/                # セッション記録 (.json/.md, runtime, gitignore)
└── web/
    ├── app.py              # FastAPIエンドポイント全部
    ├── templates/          # dashboard, learn, session, history
    └── static/
```

---

## 7. UI構成

| ページ | 役割 |
|---|---|
| `/` Dashboard | 全体俯瞰、Observatory/Learn入口、最近のセッション |
| `/session/{id}` | Observatory モード：AI vs AI のリアルタイム観戦、評価軸表示 |
| `/learn` | 人間学習者のオンボーディング/Welcome Back |
| `/learn/session` | 人間 vs AI のチャット（音声入力対応、JA/EN切替） |
| `/history` | 過去全セッションの一覧 |

---

## 8. 主要な技術スタック

- **Backend**: FastAPI + Jinja2
- **LLM**: OpenAI GPT-4o（Teacher、Student、Referee、Judge全て）
- **Frontend**: バニラ JS + CSS（フレームワーク無し）
- **音声入力**: ブラウザ Web Speech API（外部依存無し）
- **永続化**: ファイルベース（JSON/CSV/Markdown）。DB無し
- **国際化**: クライアントサイド辞書方式（JA/EN）
- **デプロイ**: Railway (Procfile + nixpacks.toml)

---

## 9. 「学ぶ仕組み」の現状

```
1ターン単位の学び
  Referee → directive_to_teacher を毎ターン生成 → ログ記録のみ

セッション内の学び
  生徒のEmotional Stateが更新 → Teacherの応答が変化

セッション間の学び（Teacher Memory）
  Refereeの評価 → teacher_memory/{teacher_id}.json に蓄積
  → 次セッション開始時にTeacherのシステムプロンプトに自動注入
  → 「過去5セッションでこういう傾向があった」と教師が自覚

スキル自体の学び（提案のみ・人間レビュー必須）
  Trigger発火 → proposals/ にMD案を生成 → 人間レビュー待ち
```

---

## 10. 拡張ポイント

- **新しい教師を追加**: `field/external_teachers/*.json` を作るだけ
- **新しいスキルを追加**: `field/skills/{name}.md` + `selected_skills` に追加
- **新しい生徒ペルソナ**: `student_agent.py` の `STUDENT_PROFILES` 辞書に追加
- **新しい評価軸**: `referee_agent.py` の `TurnEvaluation` dataclass + プロンプト
- **新しい単元/学年/科目**: `app.py` の `CURRICULUM` 辞書に追加（現在は小6算数のみ実体あり）

---

## 11. 共有データ（チーム運用）

以下はRailway Volume上で共有され、ローカルにはコミットされません（`.gitignore` 対象）：

- `training_field/reports/` — セッション履歴・transcript
- `training_field/field/teacher_memory/` — Teacher の経験記憶
- `training_field/field/skills/proposals/` — Refereeが生成したスキル改訂案
- `training_field/experiments/experiment_registry.json` — 実験CSV

ローカル開発時は空の状態から始まります。本番のデータを見たい時は Railway のVolumeから取得してください。
