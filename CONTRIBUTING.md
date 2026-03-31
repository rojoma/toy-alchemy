# 開発ガイド

## ブランチ運用

```
main (保護ブランチ - 直接pushできません)
 └── feature/xxx  (各自の作業ブランチ)
```

### 作業の流れ

```bash
# 1. mainを最新にする
git checkout main
git pull origin main

# 2. 作業ブランチを作る
git checkout -b feature/自分の作業内容

# 3. 作業してコミット
git add 変更したファイル
git commit -m "何をしたかの説明"

# 4. pushしてPull Requestを作る
git push -u origin feature/自分の作業内容
# → GitHubでPull Requestを作成
```

### ブランチ命名規則

| 種類 | 命名例 |
|------|--------|
| 新機能 | `feature/vision-ocr`, `feature/tts-integration` |
| バグ修正 | `fix/tutor-answer-leak`, `fix/session-timeout` |
| プロンプト調整 | `prompt/tutor-scaffolding`, `prompt/referee-directive` |

## Pull Request ルール

- **mainへの直接pushは禁止**（ブランチ保護あり）
- PRは最低1人がレビューしてからマージ
- PRのタイトルは「何をしたか」が一目でわかるように

## 環境変数の扱い

- `.env` ファイルは **絶対にcommitしない**（`.gitignore`で除外済み）
- 新しい環境変数を追加したら `.env.example` も更新すること
- API キーをSlackやチャットに直接貼らない（期限付きの共有方法を使う）

## コミットメッセージ

日本語OK。何をしたかが伝わればOK。

```
良い例: 「Tutorのプロンプトに褒め方のバリエーションを追加」
悪い例: 「更新」「修正」
```
