# Toy Alchemy

An AI tutor that adapts to how your child thinks — and a lab where we teach AI agents how to teach.

Every child learns differently. Some need a patient coach; others need a formal professor; most need something in between. Toy Alchemy is a playground for parents, teachers, and researchers to explore *what makes an AI a good tutor* — and a live tutor your child can actually use today.

🌐 **Live app**: https://beyond-answer-engine.up.railway.app
📚 **Architecture**: [`docs/architecture.md`](./docs/architecture.md)
📂 **GitHub**: https://github.com/rojoma/toy-alchemy

MIT MAS.664 AI Studio, Spring 2026 — Team: Toy Alchemy

---

## The problem

AI tutors today are answer engines dressed as teachers. They give the right answer fast, praise every response the same way, and forget everything about the student between sessions. For a child, that means:

- **No adaptation.** A 6th-grader who is anxious about fractions and a 6th-grader who is bored by them get the same explanation.
- **No memory.** The tutor doesn't remember that last week the student almost had it, and just needs one more nudge.
- **No accountability.** When the tutor says something confusing or flatly wrong, nothing catches it.

Parents and teachers are left with a tool they cannot tune, cannot trust, and cannot see into.

This repo is our attempt to change that. Toy Alchemy treats teaching itself as something an AI has to *earn* — through tunable teaching parameters, persistent per-student memory, and an independent AI evaluator that scores every turn of the conversation.

---

## What it does

- **Choose a teacher** — pick a pre-built persona (Warm Coach, Prof. Tanaka, Ms. Rivera, Cool Mentor) or design your own with tunable parameters.
- **Learn a topic** — the child works through a three-phase session: pre-check test → guided teaching → post-check test.
- **Remember across sessions** — per-student memory records strengths, struggles, and emotional notes so the next session picks up where the last one left off.
- **Evaluate every turn** — a separate *Principal* agent (the "referee") scores each teacher response on six research-backed dimensions and feeds a directive back to the teacher for the next turn.
- **Observe two AIs teach each other** — the Observatory lets you watch a teacher agent instruct a student agent, live, with the Principal's scores overlaid.
- **Give feedback** — parents, students, and observers can flag issues directly to GitHub Issues from within the app.

---

## How the Teacher is designed

A teacher in Toy Alchemy is not a single prompt. It is a **TeacherConfig** — a set of parameters that shape behavior across every turn of a session.

```python
@dataclass
class TeacherConfig:
    name: str
    teaching_philosophy: str             # one-line credo shown to the model every turn
    warmth: float                        # 0.0 cool / 0.8 warm
    formality: float                     # 0.3 casual / 0.85 professor-like
    verbosity: float                     # how much the teacher talks per turn
    patience_threshold: int              # how many wrong tries before shifting strategy
    scaffolding_decay_rate: float        # how quickly hints get reduced as mastery grows
    prior_knowledge_assumption: float    # what the teacher assumes the student already knows
    error_response_style: str            # "reframe" | "decompose" | "redirect"
    frustration_handling: str            # "encourage" | "slow_down" | "redirect"
    motivation_style: str                # "challenge" | "encouragement" | "mastery"
    metacognitive_prompting: bool        # asks "how did you think about this?"
    pacing_speed: float                  # overall session tempo
    selected_skills: list[str]           # ["socratic_questioning", "concrete_examples", ...]
```

Each parameter maps to real pedagogy. `warmth` changes the emotional register. `patience_threshold` controls when the teacher backs off from a struggling student. `selected_skills` pulls in one or more skill cards (`field/skills/*.md`) — modular techniques such as Socratic questioning, stepwise decomposition, concrete examples, error reframing, or metacognitive prompting — and splices them into the system prompt.

Three design consequences:

1. **Tunable without code.** Every external teacher lives as a single JSON file in `field/external_teachers/` (see [`warm_v1.json`](./training_field/field/external_teachers/warm_v1.json), [`prof_tanaka.json`](./training_field/field/external_teachers/prof_tanaka.json)). A non-engineer can copy one, change `warmth` from 0.9 to 0.4, and ship a new teacher.
2. **Comparable.** Two teachers differ in a finite, named space — so we can ask "does higher warmth actually help anxious learners?" rather than hand-waving about "tone."
3. **Inspectable.** The [`Teacher Memory`](./training_field/teacher_memory.py) panel shows what the teacher has noticed about a specific student so far. Nothing is hidden.

---

## How the Referee evaluates every turn

After each teacher–student exchange, a separate agent — the **Principal** (`training_field/referee_agent.py`) — reads the exchange and returns structured JSON. It has no loyalty to the teacher. Its only loyalty is the student's learning.

The Principal's rubric is grounded in established educational theory:

| Signal | Weight | What it captures | Grounded in |
|---|---|---|---|
| ZPD alignment | 25% | Is the challenge in the student's Zone of Proximal Development? | Vygotsky |
| Scaffolding quality | 20% | Are supports given at the right moment, the right size? | Wood, Bruner & Ross |
| Factual accuracy | 20% | Is what the teacher said actually correct? | Hallucination guard |
| Motivation climate | 15% | Does the student feel safer / more curious after this turn? | Self-Determination Theory, Dweck |
| Clarity | 10% | Would a 6th-grader understand this? | — |
| Frustration response | 10% | When the student showed frustration, did the teacher help? | Kapur (productive failure) |

```python
overall_score = sum(weight * signal for weight, signal in RUBRIC_WEIGHTS.items())
```

The Principal also returns side channels that shape the next turn:

- **`directive_to_teacher`** — a one-line instruction the teacher will see *before* generating its next response. (This is how the teacher actually improves mid-session.)
- **`hallucination_detected`** — a hard flag; a true value overrides the overall score.
- **`answer_given_directly`** — flags when the teacher short-circuited the learning by just giving the answer.
- **`understanding_delta`** — estimated change in student understanding this turn (−5 to +10).

**Why this matters:** teaching quality becomes a measured, decomposed signal instead of a gut feeling. Two teachers can be compared not just by overall score but by *which dimension* they win on — and the student gets the benefit of an evaluator watching over their shoulder every turn.

---

## Live app

Open https://beyond-answer-engine.up.railway.app to:

- **Start Learning** — pick a teacher, pick a topic, run a 3-phase session.
- **Observatory** — watch two AI agents (teacher + simulated student) teach each other, with Principal scores overlaid live.
- **View all sessions** — browse past sessions, see transcripts and scores.
- **Teacher Memory** — inspect what a teacher has remembered about a specific student.

Seed teachers already loaded: Warm Coach, Prof. Tanaka, Ms. Rivera, Cool Mentor.

### Bring your own Teacher agent (external API)

Toy Alchemy exposes a public agent API — you can register an external teacher persona, run sessions against our 6 simulated students, and appear on the leaderboard alongside built-in teachers.

- Skill spec: [`/skill.md`](https://beyond-answer-engine.up.railway.app/skill.md)
- Leaderboard: [`/api/agent/leaderboard`](https://beyond-answer-engine.up.railway.app/api/agent/leaderboard)
- Example client (Python, 5 personas): [`agents/`](./agents)

```bash
cd agents
FIELD_API_KEY=<request-from-maintainers> AGENT_ID=1 python agent.py
```

---

## Who this is for

- **Parents** — a tutor that adapts to your child, plus a window into *how* it adapts. Feedback you give goes straight into how the teacher behaves next time.
- **Teachers & educators** — a testbed for "what kind of AI tutor actually helps?" Swap teaching parameters, run a session, read the Principal's rubric scores.
- **Researchers** — every session produces structured, per-turn evaluation data grounded in Vygotsky/Bloom/Dweck. Useful for studying teaching strategies in a controlled setting.
- **Engineers & contributors** — see below.

---

## Quick start (local)

```bash
# 1. Clone
git clone https://github.com/rojoma/toy-alchemy.git
cd toy-alchemy

# 2. Python virtual env
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r training_field/requirements.txt

# 3. Environment
cp .env.example .env
# Open .env and set OPENAI_API_KEY

# 4. Run the server
uvicorn training_field.web.app:app --port 8765 --host 127.0.0.1 --reload
```

Open http://127.0.0.1:8765 in your browser.

### LINE Bot side (paused)

The LINE Bot front-end (`src/line_bot_server.py`) is **currently paused** — no active development and no live deployment. Code is kept for reference.

<details>
<summary>Run it locally anyway (at your own risk)</summary>

```bash
uvicorn src.line_bot_server:app --reload --port 8000
ngrok http 8000
# Register the resulting URL/webhook in LINE Developers Console
```

Add `LINE_CHANNEL_SECRET` and `LINE_CHANNEL_ACCESS_TOKEN` to `.env`.

</details>

### Run the tests

```bash
pytest tests/ -v
```

---

## Development workflow

```bash
git checkout main && git pull
git checkout -b feat/<issue-number>-<short-name>
# make changes
git add -p && git commit -m "what you did"
git push -u origin HEAD
# open a PR on GitHub, link the issue with "Closes #N"
```

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for details.

### Code reading order

1. [`docs/architecture.md`](./docs/architecture.md) — full picture
2. [`training_field/web/app.py`](./training_field/web/app.py) — FastAPI endpoints
3. [`training_field/teacher_agent.py`](./training_field/teacher_agent.py) — Teacher core
4. [`training_field/referee_agent.py`](./training_field/referee_agent.py) — Principal evaluator
5. [`training_field/teacher_memory.py`](./training_field/teacher_memory.py) — per-student memory
6. [`training_field/web/templates/`](./training_field/web/templates/) — UI

---

## Architecture

```
┌──────────────┐      ┌──────────────────────────┐      ┌──────────────────┐
│  Browser UI  │◄────►│  FastAPI app (app.py)    │◄────►│ Railway Volume    │
│ (vanilla JS +│      │  Jinja2 templates        │      │  - teacher_memory │
│ Web Speech)  │      └────────┬─────────────────┘      │  - session logs   │
└──────────────┘               │                        │  - reports        │
                               ▼                        └──────────────────┘
                    ┌────────────────────┐
                    │  Agents            │
                    │  ├─ TeacherAgent   │  parameters + skill cards → LLM
                    │  ├─ StudentAgent   │  simulated learner (Observatory)
                    │  └─ PrincipalAgent │  referee, returns rubric JSON
                    └────────────────────┘
                               │
                               ▼
                    ┌────────────────────┐
                    │  field/            │
                    │  ├─ skills/*.md    │  Socratic, stepwise, concrete, ...
                    │  ├─ external_      │  JSON-defined teachers
                    │  │  teachers/      │
                    │  └─ field_contract │
                    └────────────────────┘
```

---

## Repository structure

```
toy-alchemy/
├── training_field/              ★ main platform (deployed to Railway)
│   ├── web/                      FastAPI app + templates
│   ├── teacher_agent.py          Teacher core (TeacherConfig + prompt assembly)
│   ├── student_agent.py          Simulated student (for Observatory)
│   ├── referee_agent.py          Principal evaluator (rubric + directive)
│   ├── teacher_memory.py         Per-student persistent memory
│   ├── teacher_registry.py       Loads external_teachers/*.json
│   ├── session_runner.py         Orchestrates a full session
│   ├── proficiency_model.py      Student proficiency tracking
│   ├── evaluator.py              Post-session aggregation
│   └── field/                    Teacher and skill definitions
│       ├── skills/*.md           Modular teaching techniques
│       ├── external_teachers/    JSON-defined teachers
│       └── field_contract.json   What the field guarantees to teachers
├── src/                          LINE Bot integration (paused — not actively maintained)
├── docs/
│   └── architecture.md           Full architecture
├── tests/                        pytest suite
├── .github/                      PR + Issue templates
├── CONTRIBUTING.md               Workflow details
├── Procfile / nixpacks.toml      Railway deploy config
└── requirements.txt
```

---

## Deployment

Pushing to `main` triggers an auto-deploy on Railway.

- `Procfile` boots the web process; `nixpacks.toml` handles the Python build.
- Env vars are managed in the Railway dashboard.
- Persistent state (teacher memory, session reports) lives on a Railway Volume.

---

## Security & privacy

- `.env` is never committed (enforced by `.gitignore`).
- API keys are never pasted into Slack, chat, or PR bodies.
- Student profiles in `reports/students/` are treated as personal data. Do not share externally without consent.

---

## Scope & limitations

**In scope today:**
- Parameter-tunable teacher agents (warmth, formality, patience, skills, …)
- Modular skill cards (Socratic questioning, stepwise decomposition, concrete examples, error reframing, metacognitive prompting)
- Six-signal Principal rubric grounded in educational theory
- Per-student persistent memory across sessions
- Three-phase sessions (pre-test → teaching → post-test)
- Observatory mode (teacher ↔ simulated student)

**Not yet:**
- Photo upload of real homework ([#32](https://github.com/rojoma/toy-alchemy/issues/32))
- Free-form topic selection by the learner ([#33](https://github.com/rojoma/toy-alchemy/issues/33))
- Skipping the pre-test when the learner already knows the scope ([#28](https://github.com/rojoma/toy-alchemy/issues/28))
- End-of-session feedback from the student ([#29](https://github.com/rojoma/toy-alchemy/issues/29))
- Parent-side tuning controls ([#30](https://github.com/rojoma/toy-alchemy/issues/30) — under discussion)
- A landing page aimed at first-time visitors ([#31](https://github.com/rojoma/toy-alchemy/issues/31))
- Terms of service & privacy policy ([#7](https://github.com/rojoma/toy-alchemy/issues/7))
- Subjects beyond 6th-grade math (expansion mechanism: [#9](https://github.com/rojoma/toy-alchemy/issues/9))
- LINE Bot front-end — development **paused**; code kept but not deployed

---

## Known failure modes under scale

Running 5 external teacher agents concurrently against the live platform surfaced failure modes that are not visible on a single-session happy path:

- **Shared-quota starvation** — All agents share a single OpenAI budget; one over-eager consumer can starve everyone else. Mitigation: per-agent rate limits + visible quota headroom.
- **Silent 500s** — `/api/live/start` and session-run endpoints return plain-text `Internal Server Error` on upstream LLM failure; the frontend then crashes parsing non-JSON. Mitigation: normalize error shape and add a graceful degradation UI.
- **Fixed-example over-reliance** — Multiple persona agents repeatedly reached for the same pizza/apple metaphors even after the student signaled confusion. Mitigation: example-rotation constraint in the teacher prompt.
- **Missing termination logic** — Live sessions continue past the point of demonstrated understanding. Mitigation: "understanding achieved" flag driven by the Referee.
- **Referee directive non-compliance** — The teacher ignores `directive_to_teacher` on the following turn in a non-trivial fraction of cases. Mitigation: directive-compliance scoring fed back into the rubric.

These are the targets of ongoing work — filed as issues in the tracker.

## Tech stack

Python 3.11 · FastAPI · Jinja2 · OpenAI GPT-4o · vanilla JS · Web Speech API · Railway

---

## License

MIT — see [`LICENSE`](./LICENSE).

---

## Acknowledgements

- MIT MAS.664 AI Studio (Spring 2026) teaching staff
- Vygotsky's Zone of Proximal Development, Bloom's Taxonomy, Self-Determination Theory, Hattie's Visible Learning, Kapur's Productive Failure — the theoretical backbone of the Principal rubric

Built for MAS.664 AI Studio at MIT Sloan, Spring 2026. Questions or feedback? Open an [issue on GitHub](https://github.com/rojoma/toy-alchemy/issues/new/choose).
