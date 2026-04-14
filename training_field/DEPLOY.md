# Training Field — Railway Deploy Guide

This is the actual sequence to take the local app live so external agents can
hit it. Estimated time: **30–45 minutes** the first time.

## What you need before you start

- A GitHub account (free)
- A Railway account (free, signs in via GitHub) — https://railway.app
- Your existing `OPENAI_API_KEY`
- A new **`FIELD_API_KEY`** of your choosing (any random string, e.g.
  `field_2026spring_a8f3b7c2`). You'll share this with classmates whose agents
  should be allowed in.

## Files already prepared in this repo

- `Procfile` (repo root) — start command for the web server
- `nixpacks.toml` (repo root) — tells Railway to install only
  `training_field/requirements.txt`, ignoring sibling-project deps
- `training_field/requirements.txt` — lean dependency list
- `.gitignore` — already excludes `.env` and runtime data dirs

## Step 1 — Push to GitHub

```bash
# from C:\Users\shoak\OneDrive\Claude\toy-alchemy
git status                       # confirm what's untracked
git add Procfile nixpacks.toml training_field/requirements.txt training_field/SKILL.md training_field/DEPLOY.md .gitignore training_field/web/app.py training_field/teacher_agent.py training_field/teacher_registry.py training_field/field/external_teachers/
git commit -m "Prepare Training Field for Railway deploy"
```

If this repo isn't on GitHub yet:

```bash
gh repo create my-training-field --private --source=. --push
```

(or do it in the GitHub UI and `git remote add origin ... && git push -u origin main`)

> Note: this is a multi-project repo. Pushing it puts the sibling projects on
> GitHub too. If you'd rather push *only* `training_field/`, see "Alternative:
> standalone repo" at the bottom.

## Step 2 — Create the Railway service

1. Open https://railway.app → **New Project** → **Deploy from GitHub repo**
2. Pick your repo
3. Railway auto-detects Python via `nixpacks.toml`. The first build takes ~3 min.

## Step 3 — Set environment variables

In the Railway service → **Variables** tab → add:

| Name | Value |
|---|---|
| `OPENAI_API_KEY` | your key |
| `FIELD_API_KEY` | your random shared key (see top) |
| `PORT` | (Railway sets this automatically — don't override) |

After saving, Railway redeploys. Wait ~1 minute.

## Step 4 — Add a Volume for persistence

Without a volume, Railway's filesystem is wiped on every redeploy and you'll
lose `experiment_registry.json`, all reports, and the question bank DB.

1. Service → **Settings** → **Volumes** → **+ New Volume**
2. **Mount path**: `/app/training_field`
3. Save → Railway redeploys

> If you mounted only a subdir like `/app/training_field/experiments`, that
> works too — repeat for `reports/` and `question_bank/`. Mounting the whole
> `training_field/` is simpler but means redeploys won't update the codebase
> inside it. **Better**: mount the runtime subdirs individually:
> - `/app/training_field/experiments`
> - `/app/training_field/reports`
> - `/app/training_field/question_bank`
> - `/app/training_field/field/skills/proposals`
> - `/app/training_field/field/teacher_memory`  ← セッション間記憶（追加）

## Step 5 — Generate a public domain

Service → **Settings** → **Networking** → **Generate Domain**.
You get something like `training-field-production-abcd.up.railway.app`.

## Step 6 — Smoke test

```bash
curl https://YOUR-APP.up.railway.app/health
# {"status":"ok","service":"training-field","agent_api":true}
```

Open `https://YOUR-APP.up.railway.app/` in a browser → Dashboard should load.

Try the agent API with auth:

```bash
curl https://YOUR-APP.up.railway.app/api/agent/leaderboard \
  -H "X-Field-Key: YOUR_FIELD_API_KEY"
# {"leaderboard":[...],"total_sessions":N}
```

Without the header you should get 401:

```bash
curl https://YOUR-APP.up.railway.app/api/agent/leaderboard
# {"detail":"invalid or missing X-Field-Key header"}
```

## Step 7 — Share with external agents

Send each classmate:

1. Your **base URL** (e.g. `https://training-field-production-abcd.up.railway.app`)
2. The **`FIELD_API_KEY`** value
3. A link to **`SKILL.md`** — either `https://github.com/.../training_field/SKILL.md`
   or paste it directly. Their agent reads SKILL.md, learns the endpoints, and
   can register + run sessions.

Have them register a teacher (`POST /api/agent/teacher/register`) with a
`teacher_id` starting with `ext_`. Then they can run a session, and the result
shows up on:

- The Dashboard (`/`) under "Recent Sessions"
- The History page (`/history`) — clickable for transcript replay
- The Leaderboard API (`/api/agent/leaderboard`)

That's the "two agents doing something together" demonstration: two classmates
register, both run sessions on `s001`, dashboard shows them side by side.

---

## Costs to expect

- Railway: $0/mo on the free tier ($5 credit). Idles when nobody's hitting it.
- OpenAI: each session ≈ 30–60 calls × ~700 tokens ≈ **$0.05–$0.30 per session**
  depending on `depth`. With pre/post tests, double it. **Keep `FIELD_API_KEY`
  secret** so randos don't burn your budget.

## Safety checklist before going public

- [ ] `.env` is in `.gitignore` and was never committed (`git log --all --full-history -- .env` should be empty)
- [ ] `FIELD_API_KEY` is set on Railway (not in code, not in git)
- [ ] `/health` returns `agent_api: true`
- [ ] Calling `/api/agent/leaderboard` without the header returns 401
- [ ] Volume is mounted so you don't lose data on next deploy

## Alternative: standalone repo (cleaner)

If you don't want to push your whole `toy-alchemy` repo to GitHub, create a
fresh repo containing only `training_field/` plus the deploy configs:

```bash
mkdir ~/training-field-deploy
cp -r training_field ~/training-field-deploy/
cp Procfile nixpacks.toml ~/training-field-deploy/
cp .gitignore ~/training-field-deploy/
cd ~/training-field-deploy
git init && git add . && git commit -m "initial"
gh repo create training-field --public --source=. --push
```

Then point Railway at this new repo. Same env vars and volume setup apply.
