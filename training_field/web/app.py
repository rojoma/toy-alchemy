from __future__ import annotations
import json, asyncio, uuid, datetime, os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Header, HTTPException, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from training_field.llm import chat_complete
from training_field.student_agent import StudentAgentFactory
from training_field.teacher_agent import TeacherAgent
from training_field.teacher_registry import list_teachers, load_teacher
from training_field.referee_agent import PrincipalAgent
from training_field.evaluator import Evaluator, CostTracker
from training_field.experiment_registry import ExperimentRegistry, ExperimentRecord
from training_field.question_bank.question_bank import QuestionBank
from training_field.proficiency_model import CurriculumGraph
from training_field.session_runner import PHASE_CONFIG, SessionConfig
from training_field.student_profile_deriver import update_derived_profile

# Derived StudentAgent surfacing (#63):
# Reuse a real student's personality+signals to power agent-vs-agent
# Observatory sessions. Eligibility threshold matches the issue spec.
DERIVED_STUDENT_ID_PREFIX = "der_"
MIN_SESSIONS_FOR_DERIVED = 3
EXPOSE_REAL_STUDENT_NAMES = os.environ.get("EXPOSE_REAL_STUDENT_NAMES") == "1"


def _build_student_agent(student_id: str):
    """Resolve a `student_id` (canonical s001-s007 OR der_<stu_id>) to a
    StudentAgent. Centralizes the dispatch so route handlers don't repeat it.
    """
    if student_id.startswith(DERIVED_STUDENT_ID_PREFIX):
        real_id = student_id[len(DERIVED_STUDENT_ID_PREFIX):]
        path = STUDENT_PROFILES_DIR / f"{real_id}.json"
        # Anonymize unless the operator opted in via env var. The agent's
        # display name is shown in transcripts and on the Observatory page.
        display = None
        if not EXPOSE_REAL_STUDENT_NAMES:
            display = _anonymous_label_for(real_id)
        return StudentAgentFactory.from_derived_profile(path, display_name=display)
    return StudentAgentFactory.from_profile(student_id)


def _anonymous_label_for(real_id: str) -> str:
    """Stable, non-identifying label like 'Student #3' for a profile id.

    Order is alphabetical over derived-eligible profile ids so the same
    user gets the same number across page loads.
    """
    eligible = sorted(_eligible_derived_profile_ids())
    try:
        idx = eligible.index(real_id) + 1
    except ValueError:
        # Profile became ineligible between calls — fall back to a hash-ish
        # but stable label.
        idx = (sum(ord(c) for c in real_id) % 99) + 1
    return f"Student #{idx}"


def _eligible_derived_profile_ids() -> list[str]:
    """Profile ids that have enough observed sessions to be a meaningful
    Observatory persona. Empty list when the profiles dir is missing."""
    if not STUDENT_PROFILES_DIR.exists():
        return []
    out: list[str] = []
    for path in STUDENT_PROFILES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        derived = data.get("derived") or {}
        if (derived.get("sessions_observed") or 0) >= MIN_SESSIONS_FOR_DERIVED:
            out.append(data.get("student_id") or path.stem)
    return out


app = FastAPI(title="Agent Training Field")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
_static_dir = Path(__file__).parent / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# ── Agent API auth ─────────────────────────────────────────────
# External agents must include `X-Field-Key: <token>` header.
# Set FIELD_API_KEY in the environment (Railway env vars). If unset, the
# agent endpoints are disabled (returns 503) so the app never accidentally
# runs unprotected in production.
def require_field_key(x_field_key: str | None = Header(default=None)):
    expected = os.environ.get("FIELD_API_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="FIELD_API_KEY not configured on server")
    if not x_field_key or x_field_key != expected:
        raise HTTPException(status_code=401, detail="invalid or missing X-Field-Key header")
    return True

@app.get("/health")
async def health():
    return {"status": "ok", "service": "training-field", "agent_api": bool(os.environ.get("FIELD_API_KEY"))}

@app.get("/skill.md")
async def serve_skill_md(request: Request):
    """Serve SKILL.md so external agents can fetch it directly via the deploy URL.
    Substitutes {{FIELD_BASE_URL}} with the actual host. {{FIELD_API_KEY}} is left
    intact — the operator distributes the key out-of-band."""
    skill_path = Path(__file__).parent.parent / "SKILL.md"
    if not skill_path.exists():
        return JSONResponse({"error": "SKILL.md not found"}, status_code=404)
    body = skill_path.read_text(encoding="utf-8")
    base_url = str(request.base_url).rstrip("/")
    body = body.replace("{{FIELD_BASE_URL}}", base_url)
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(body, media_type="text/markdown; charset=utf-8")

STUDENTS = {
    "s001": {"name":"Emma","nickname":"エマ","prof_baseline":32,"personality":"Anxious, withdrawn","color":"#3b82f6"},
    "s002": {"name":"Jake","nickname":"ジェイク","prof_baseline":40,"personality":"Impulsive, trial-and-error","color":"#f59e0b"},
    "s003": {"name":"Priya","nickname":"プリヤ","prof_baseline":52,"personality":"Methodical, patient","color":"#10b981"},
    "s004": {"name":"Dylan","nickname":"ディラン","prof_baseline":51,"personality":"Moody, topic-sensitive","color":"#8b5cf6"},
    "s005": {"name":"Chloe","nickname":"クロエ","prof_baseline":70,"personality":"Perfectionist, cautious","color":"#ec4899"},
    "s006": {"name":"Marcus","nickname":"マーカス","prof_baseline":74,"personality":"Confident, fast-moving","color":"#06b6d4"},
    "s007": {"name":"Yuki","nickname":"ユキ","prof_baseline":29,"personality":"Human-derived (Live transcript). Curt, frustrated, refuses abstract re-questioning","color":"#64748b"},
}

TOPICS = ["分数のかけ算・わり算","比と比の値","速さ・時間・距離","比例と反比例","円の面積","場合の数"]

# Curriculum: (grade_code, subject) -> topics.
# Data lives in training_field/data/curriculum.json — see that file's schema
# and training_field/data/README.md for how non-engineers can contribute (#9).
_CURRICULUM_JSON = Path(__file__).parent.parent / "data" / "curriculum.json"
try:
    _curriculum_doc = json.loads(_CURRICULUM_JSON.read_text(encoding="utf-8"))
except Exception as _e:
    raise RuntimeError(f"failed to load {_CURRICULUM_JSON}: {_e}") from _e

GRADE_CODES: dict[str, int] = {}
CURRICULUM: dict[tuple[int, str], list[str]] = {}
CURRICULUM_EN: dict[tuple[int, str], list[str]] = {}
for _label, _grade_block in _curriculum_doc.get("grades", {}).items():
    _code = _grade_block["code"]
    GRADE_CODES[_label] = _code
    for _subject, _lists in _grade_block.get("subjects", {}).items():
        CURRICULUM[(_code, _subject)] = list(_lists.get("ja", []))
        CURRICULUM_EN[(_code, _subject)] = list(_lists.get("en", []))


def topics_for(grade_code: int, subject: str) -> list[str]:
    return CURRICULUM.get((grade_code, subject)) or [f"{subject} - 単元1", f"{subject} - 単元2", f"{subject} - 単元3"]

# Flat ja->en topic map, generated by zipping parallel lists.
TOPIC_TX_EN: dict[str, str] = {}
for _k, _ja_list in CURRICULUM.items():
    _en_list = CURRICULUM_EN.get(_k, [])
    for _ja, _en in zip(_ja_list, _en_list):
        TOPIC_TX_EN[_ja] = _en


# Legacy / alternate topic strings present in older registry records that don't
# match the current CURRICULUM keys. Extend this dict whenever an untranslated
# Japanese topic appears in the UI history table.
LEGACY_TOPIC_ALIASES: dict[str, str] = {
    "速さ時間距離": "Speed, Time, Distance",
    "速さ・時間・距離": "Speed, Time, Distance",
    "分数のかけ算・わり算": "Multiplication & Division of Fractions",
    "比と比の値": "Ratios and Ratio Values",
    "比例と反比例": "Proportion & Inverse Proportion",
    "場合の数": "Combinatorics",
}
for _ja, _en in LEGACY_TOPIC_ALIASES.items():
    TOPIC_TX_EN.setdefault(_ja, _en)

_SUBJECT_EN = {"算数":"Math","国語":"Japanese","理科":"Science","社会":"Social Studies","英語":"English"}

def display_topic(topic: str, lang: str) -> str:
    """Translate topic/subject name for LLM prompts. JA → EN when lang='en', pass-through otherwise."""
    if lang == "en":
        return TOPIC_TX_EN.get(topic, _SUBJECT_EN.get(topic, topic))
    return topic

# ── Live Session (Human Student Mode) ─────────────────────────
# In-memory store for active live sessions. Each session holds teacher + referee
# state between HTTP requests. Lost on redeploy (acceptable for now).
from dataclasses import dataclass as _dc, field as _field

NUM_TEST_QUESTIONS = 3

@_dc
class LiveSession:
    session_id: str
    teacher: object  # TeacherAgent
    principal: object  # PrincipalAgent
    phases: list
    topic: str
    grade: int
    subject: str
    depth: str
    lang: str
    teacher_name: str
    student_label: str  # human's display name
    # state
    session_phase: str = "pre_test"  # pre_test → teaching → post_test → complete
    current_phase_idx: int = 0
    current_turn: int = 0
    total_turns_done: int = 0
    test_question_num: int = 0  # current test question (1-based)
    proficiency: float = 50.0
    initial_proficiency: float = 50.0
    last_teacher_text: str | None = None
    turns_log: list = _field(default_factory=list)
    turn_evaluations: list = _field(default_factory=list)
    pre_test_results: list = _field(default_factory=list)  # [{question, student_answer, correct, explanation}]
    post_test_results: list = _field(default_factory=list)
    key_moments: list = _field(default_factory=list)  # [{turn, delta, summary}] — biggest learning moments
    is_complete: bool = False
    started_at: str = ""
    # per-session flags (see #34): default True keeps existing behavior
    run_pre_test: bool = True
    run_post_test: bool = True
    # learner-stated scope (#28). Held server-side and threaded into every
    # Teacher call as context — never echoed in the chat UI, so a long
    # paste does not blow up the message bubbles.
    scope: str = ""
    # Real student profile id (stu_xxx) when this session was started by a
    # logged-in human via /learn. Used to update their derived profile
    # (#62) on completion. None for anonymous one-off sessions.
    real_student_id: str | None = None

    @property
    def total_turns(self):
        return sum(p["turns"] for p in self.phases)

    @property
    def current_phase(self):
        if self.current_phase_idx < len(self.phases):
            return self.phases[self.current_phase_idx]
        return None


def _test_prompt(teacher_config, topic, grade, subject, lang, question_num, total_qs, student_name, is_post=False):
    """Build system prompt for a conversational test question."""
    test_type = "post-test (review)" if is_post else "pre-test (diagnostic)"
    dtopic = display_topic(topic, lang)
    dsubject = display_topic(subject, lang)
    return f"""You are {teacher_config.name}, giving a friendly {test_type} to {student_name}.
Topic: {dtopic} (Grade {grade} {dsubject}).
Question {question_num} of {total_qs}.

RULES:
- Ask ONE short, specific calculation question about {dtopic} for grade {grade}. Use concrete numbers.
- 1 sentence only. No preamble, no encouragement, no "Let's see..." — just the question.
- Start the question with ▶ (e.g. "▶ 2/3 × 3/4 はいくつ？").
- {"Focus on concepts from today's lesson." if is_post else "Test existing knowledge before the lesson."}
- Each question must test a DIFFERENT aspect.
- Use plain text for math (e.g. 2/3 × 4/5, not LaTeX). NEVER use \\frac, \\times, \\div, etc.
- Reply in {"English" if lang == "en" else "Japanese"}."""


def _judge_prompt(teacher_config, topic, grade, lang, question_text, student_answer):
    """Build system prompt for judging a test answer."""
    dtopic = display_topic(topic, lang)
    return f"""You are {teacher_config.name}, evaluating a student's answer to a math question.

The question was: "{question_text}"
Student answered: "{student_answer}"

RULES:
- First, compute the correct answer yourself step by step.
- Compare the student's answer to the correct answer.
- BE LENIENT with format: accept partial answers, missing units, abbreviations, equivalent forms.
  Examples of answers that MUST be marked correct:
  - "70" when the answer is "70度" or "70 degrees"
  - "1/2" when the answer is "0.5" or "2/4"
  - "6" when the answer is "6cm²"
  - A single number that matches the core numerical value
- If the question asks for multiple values and the student gives one correct value, mark correct.
- When in doubt, mark correct. This is a friendly check, not a strict exam.
- Feedback: 1 sentence max. If correct, confirm briefly. If wrong, state the correct answer and show the key step.
- Use plain text for math (e.g. 2/3, 3.14). NEVER use LaTeX (no \\frac, \\times, \\div, etc.).
- Reply in {"English" if lang == "en" else "Japanese"}.
- Start with "✓" if correct, "✗" if incorrect.
- Then on a NEW LINE, add this exact JSON (no code block):
{{"correct": true_or_false, "question": "{question_text}", "explanation": "the correct answer and one-line explanation"}}"""

LIVE_SESSIONS: dict[str, LiveSession] = {}

@app.post("/api/live/start")
async def live_start(body: dict):
    """Start a live (human-student) session.

    By default the session begins with a pre-test. Callers can skip either
    test by passing `run_pre_test: false` or `run_post_test: false` in the
    body — see #34 (test-less path is meant for light conversation modes
    and for the homework-scope flow planned in #28).
    """
    teacher_id = body.get("teacher_id", "t001")
    topic = body.get("topic", "分数のかけ算とわり算")
    depth = body.get("depth", "quick")
    grade_str = body.get("grade", "小6")
    subject = body.get("subject", "算数")
    lang = body.get("lang", "en")
    student_label = body.get("student_name", "You")
    # Real student profile id (when a logged-in human starts via /learn).
    # Threaded through so we can update their derived profile (#62) at end.
    real_student_id = body.get("student_id")
    run_pre_test = bool(body.get("run_pre_test", True))
    run_post_test = bool(body.get("run_post_test", True))
    # Optional learning scope the student specified (#28). When present we
    # skip the pre-test and weave the scope into the teacher's greeting so
    # the first message is relevant to what the student actually wants.
    scope = (body.get("scope") or "").strip() or None

    gcode = GRADE_CODES.get(grade_str, 6)
    teacher = load_teacher(teacher_id)
    principal = PrincipalAgent()
    # Live sessions always run unlimited — the human student ends the session
    # explicitly via /api/live/{id}/end. depth is retained only for metadata.
    phases = PHASE_CONFIG["unlimited"]
    sid = f"live_{uuid.uuid4().hex[:8]}"

    initial_phase = "pre_test" if run_pre_test else "teaching"
    session = LiveSession(
        session_id=sid,
        teacher=teacher,
        principal=principal,
        phases=phases,
        topic=topic, grade=gcode, subject=subject,
        depth=depth, lang=lang,
        teacher_name=teacher.config.name,
        student_label=student_label,
        session_phase=initial_phase,
        test_question_num=1 if run_pre_test else 0,
        proficiency=50.0, initial_proficiency=50.0,
        started_at=datetime.datetime.now().isoformat(),
        run_pre_test=run_pre_test,
        run_post_test=run_post_test,
        scope=scope or "",
        real_student_id=real_student_id,
    )
    LIVE_SESSIONS[sid] = session

    if run_pre_test:
        # Generate first pre-test question
        prompt = _test_prompt(teacher.config, topic, gcode, subject, lang, 1, NUM_TEST_QUESTIONS, student_label, is_post=False)
        first_q = chat_complete(
            [{"role": "system", "content": prompt},
             {"role": "user", "content": f"Ask question 1 of {NUM_TEST_QUESTIONS} about {display_topic(topic, lang)}."}],
            role="judge",
            max_tokens=300,
        ).strip()
        session.last_teacher_text = first_q
        greeting = "Let's start with a quick check!" if lang == "en" else "まずは軽いチェックから始めましょう！"
        return {
            "session_id": sid,
            "teacher_name": teacher.config.name,
            "teacher_message": f"{greeting}\n\n{first_q}",
            "session_phase": "pre_test",
            "test_progress": f"1/{NUM_TEST_QUESTIONS}",
            "is_complete": False,
        }

    # No pre-test: open with a teaching greeting. If the student gave us a
    # scope (#28), acknowledge that we read it WITHOUT echoing it in the chat
    # bubble — long scope pastes (e.g. a full term sheet) used to overflow the
    # UI. The scope is held on the LiveSession and threaded into every
    # subsequent Teacher call as context.
    dtopic = display_topic(topic, lang)
    if scope:
        greeting = (
            f"Hi! I'm {teacher.config.name}. Got it — I read what you shared. Let's begin."
            if lang == "en"
            else f"こんにちは！{teacher.config.name}です。共有してくれた内容を読みました。一緒に始めましょう。"
        )
    else:
        greeting = (
            f"Hi! I'm {teacher.config.name}. What would you like to work on for {dtopic}?"
            if lang == "en"
            else f"こんにちは！{teacher.config.name}です。{dtopic}について、どこから始めましょうか？"
        )
    session.last_teacher_text = greeting
    return {
        "session_id": sid,
        "teacher_name": teacher.config.name,
        "teacher_message": greeting,
        "session_phase": "teaching",
        "test_progress": None,
        "is_complete": False,
    }


@app.post("/api/live/{session_id}/respond")
async def live_respond(session_id: str, body: dict):
    """Submit the human student's response. Handles pre_test / teaching / post_test phases."""
    session = LIVE_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "session not found or expired")
    if session.is_complete:
        raise HTTPException(400, "session already complete")

    student_text = body.get("text", "").strip()
    if not student_text:
        raise HTTPException(400, "text is required")

    # Allow client to update language mid-session (so subsequent teacher/judge
    # messages switch language too).
    new_lang = body.get("lang")
    if new_lang in ("en", "ja"):
        session.lang = new_lang

    teacher = session.teacher
    # ── PRE-TEST or POST-TEST phase ──────────────────────────
    if session.session_phase in ("pre_test", "post_test"):
        is_post = session.session_phase == "post_test"
        results_list = session.post_test_results if is_post else session.pre_test_results

        # Judge the answer
        judge_sys = _judge_prompt(
            teacher.config, session.topic, session.grade, session.lang,
            session.last_teacher_text or "", student_text,
        )
        raw = chat_complete(
            [{"role": "system", "content": judge_sys},
             {"role": "user", "content": f'Student answered: "{student_text}"'}],
            role="judge",
            max_tokens=400,
        ).strip()

        # Parse feedback + JSON
        feedback_text = raw
        result_data = {"correct": False, "question": session.last_teacher_text or "", "explanation": ""}
        for line in raw.split("\n"):
            stripped = line.strip()
            if stripped.startswith("{") and "correct" in stripped:
                try:
                    result_data = json.loads(stripped)
                    feedback_text = raw.replace(stripped, "").strip()
                except json.JSONDecodeError:
                    pass

        results_list.append({
            "question": result_data.get("question", session.last_teacher_text or ""),
            "student_answer": student_text,
            "correct": bool(result_data.get("correct", False)),
            "explanation": result_data.get("explanation", ""),
            "feedback": feedback_text,
        })
        session.test_question_num += 1

        # More test questions?
        if session.test_question_num <= NUM_TEST_QUESTIONS:
            prompt = _test_prompt(
                teacher.config, session.topic, session.grade, session.subject,
                session.lang, session.test_question_num, NUM_TEST_QUESTIONS,
                session.student_label, is_post=is_post,
            )
            next_q = chat_complete(
                [{"role": "system", "content": prompt},
                 {"role": "user", "content": f"Ask question {session.test_question_num} of {NUM_TEST_QUESTIONS}."}],
                role="judge",
                max_tokens=300,
            ).strip()
            session.last_teacher_text = next_q
            return {
                "teacher_message": f"{feedback_text}\n\n{next_q}",
                "teacher_name": session.teacher_name,
                "session_phase": session.session_phase,
                "test_progress": f"{session.test_question_num}/{NUM_TEST_QUESTIONS}",
                "is_complete": False,
            }

        # Test phase complete — transition
        if session.session_phase == "pre_test":
            # Move to teaching
            session.session_phase = "teaching"
            session.current_turn = 1
            session.current_phase_idx = 0
            pre_score = sum(1 for r in session.pre_test_results if r["correct"])
            session.initial_proficiency = round(pre_score / NUM_TEST_QUESTIONS * 100)
            session.proficiency = session.initial_proficiency

            # Generate first teaching message
            phase = session.current_phase
            dtopic = display_topic(session.topic, session.lang)
            dsubject = display_topic(session.subject, session.lang)
            tr = await teacher.get_response(
                topic=dtopic, phase=phase["name"], phase_goal=phase["goal"],
                student_name=session.student_label, student_proficiency=session.proficiency,
                student_emotional={"confidence": 0.5, "frustration": 0.0, "engagement": 0.5},
                student_last_response=None,
                grade=session.grade, subject=dsubject,
                turn_number=1, lang=session.lang,
                session_memory=getattr(teacher, "session_memory", ""),
                scope=session.scope,
            )
            session.last_teacher_text = tr["text"]

            transition = ("Great! Now let's learn together." if session.lang == "en"
                          else "では、一緒に学びましょう！")
            return {
                "teacher_message": f"{feedback_text}\n\n{transition}\n\n{tr['text']}",
                "teacher_name": session.teacher_name,
                "session_phase": "teaching",
                "phase": phase["name"],
                "phase_label": phase["label"],
                "pre_test_score": f"{pre_score}/{NUM_TEST_QUESTIONS}",
                "is_complete": False,
            }
        else:
            # Post-test done → session complete
            session.is_complete = True
            session.session_phase = "complete"
            # Compute key moments
            if session.turns_log:
                sorted_turns = sorted(session.turns_log, key=lambda t: t.get("delta", 0), reverse=True)
                session.key_moments = [
                    {"turn": t["turn"], "phase": t["phase_label"], "delta": t["delta"], "summary": t["summary"]}
                    for t in sorted_turns[:3] if t.get("delta", 0) > 0
                ]
            _save_live_session(session)
            _update_real_student_derived(session)
            post_score = sum(1 for r in session.post_test_results if r["correct"])
            pre_score = sum(1 for r in session.pre_test_results if r["correct"])
            return {
                "teacher_message": feedback_text,
                "session_phase": "complete",
                "is_complete": True,
                "pre_test": session.pre_test_results,
                "post_test": session.post_test_results,
                "pre_score": f"{pre_score}/{NUM_TEST_QUESTIONS}",
                "post_score": f"{post_score}/{NUM_TEST_QUESTIONS}",
                "improvement": post_score - pre_score,
                "key_moments": session.key_moments,
                "proficiency_delta": round(session.proficiency - session.initial_proficiency, 1),
            }

    # ── TEACHING phase ───────────────────────────────────────
    phase = session.current_phase
    principal = session.principal
    dtopic = display_topic(session.topic, session.lang)
    dsubject = display_topic(session.subject, session.lang)

    # Referee evaluates
    ev = await principal.evaluate_turn(
        teacher_text=session.last_teacher_text or "",
        student_text=student_text,
        topic=dtopic, phase=phase["name"],
        student_proficiency=session.proficiency,
        grade=session.grade, subject=dsubject,
        lang=session.lang,
    )
    session.turn_evaluations.append(ev)
    if ev.understanding_delta > 0:
        session.proficiency += ev.understanding_delta * 0.3

    session.turns_log.append({
        "phase": phase["name"], "phase_label": phase["label"],
        "turn": session.current_turn,
        "teacher": session.last_teacher_text,
        "student": student_text,
        "zpd": round(ev.zpd_alignment, 2), "bloom": ev.bloom_level,
        "scaffolding": round(ev.scaffolding_quality, 2),
        "halluc": ev.hallucination_detected, "direct": ev.answer_given_directly,
        "delta": round(ev.understanding_delta, 1),
        "directive": ev.directive_to_teacher, "summary": ev.summary,
        "prof_after": round(session.proficiency, 1),
    })
    session.total_turns_done += 1

    # Advance turn / phase
    session.current_turn += 1
    if session.current_turn > phase["turns"]:
        session.current_phase_idx += 1
        session.current_turn = 1

    # Teaching complete? → transition to post-test
    if session.current_phase_idx >= len(session.phases):
        session.session_phase = "post_test"
        session.test_question_num = 1
        prompt = _test_prompt(
            teacher.config, dtopic, session.grade, session.subject,
            session.lang, 1, NUM_TEST_QUESTIONS, session.student_label, is_post=True,
        )
        post_q = chat_complete(
            [{"role": "system", "content": prompt},
             {"role": "user", "content": f"Ask review question 1 of {NUM_TEST_QUESTIONS}."}],
            role="judge",
            max_tokens=300,
        ).strip()
        session.last_teacher_text = post_q
        review_intro = ("Great work! Let's see how much you've learned." if session.lang == "en"
                        else "よく頑張りました！どれだけ学んだか確認しましょう。")
        return {
            "teacher_message": f"{review_intro}\n\n{post_q}",
            "teacher_name": session.teacher_name,
            "session_phase": "post_test",
            "test_progress": f"1/{NUM_TEST_QUESTIONS}",
            "is_complete": False,
        }

    # Next teaching turn
    next_phase = session.current_phase
    tr = await teacher.get_response(
        topic=dtopic, phase=next_phase["name"], phase_goal=next_phase["goal"],
        student_name=session.student_label, student_proficiency=session.proficiency,
        student_emotional={"confidence": 0.5, "frustration": 0.0, "engagement": 0.5},
        student_last_response=student_text,
        grade=session.grade, subject=dsubject,
        turn_number=session.current_turn, lang=session.lang,
        session_memory=getattr(teacher, "session_memory", ""),
        scope=session.scope,
    )
    session.last_teacher_text = tr["text"]

    return {
        "teacher_message": tr["text"],
        "teacher_name": session.teacher_name,
        "session_phase": "teaching",
        "phase": next_phase["name"],
        "phase_label": next_phase["label"],
        "turn": session.current_turn,
        "total_turns": session.total_turns,
        "turns_done": session.total_turns_done,
        "proficiency": round(session.proficiency, 1),
        "is_complete": False,
    }


@app.post("/api/live/{session_id}/end")
async def live_end(session_id: str):
    """Human student explicitly ends the session.

    Default path: jump to post-test. If the session was started with
    `run_post_test: false` (#34), skip post-test and complete immediately.
    """
    session = LIVE_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "session not found or expired")
    if session.is_complete:
        raise HTTPException(400, "session already complete")
    if session.session_phase not in ("teaching", "pre_test"):
        raise HTTPException(400, f"cannot end from phase {session.session_phase}")

    # Skip post-test path
    if not session.run_post_test:
        session.is_complete = True
        session.session_phase = "complete"
        if session.turns_log:
            sorted_turns = sorted(session.turns_log, key=lambda t: t.get("delta", 0), reverse=True)
            session.key_moments = [
                {"turn": t["turn"], "phase": t["phase_label"], "delta": t["delta"], "summary": t["summary"]}
                for t in sorted_turns[:3] if t.get("delta", 0) > 0
            ]
        _save_live_session(session)
        _update_real_student_derived(session)
        pre_score = sum(1 for r in session.pre_test_results if r["correct"])
        farewell = ("Nice work today!" if session.lang == "en"
                    else "今日もよく頑張りました！")
        return {
            "teacher_message": farewell,
            "session_phase": "complete",
            "is_complete": True,
            "pre_test": session.pre_test_results,
            "post_test": [],
            "pre_score": f"{pre_score}/{NUM_TEST_QUESTIONS}" if session.run_pre_test else None,
            "post_score": None,
            "improvement": None,
            "key_moments": session.key_moments,
            "proficiency_delta": round(session.proficiency - session.initial_proficiency, 1),
        }

    teacher = session.teacher
    dtopic = display_topic(session.topic, session.lang)

    session.session_phase = "post_test"
    session.test_question_num = 1
    prompt = _test_prompt(
        teacher.config, dtopic, session.grade, session.subject,
        session.lang, 1, NUM_TEST_QUESTIONS, session.student_label, is_post=True,
    )
    post_q = chat_complete(
        [{"role": "system", "content": prompt},
         {"role": "user", "content": f"Ask review question 1 of {NUM_TEST_QUESTIONS}."}],
        role="judge",
        max_tokens=300,
    ).strip()
    session.last_teacher_text = post_q
    review_intro = ("Great work! Let's see how much you've learned." if session.lang == "en"
                    else "よく頑張りました！どれだけ学んだか確認しましょう。")
    return {
        "teacher_message": f"{review_intro}\n\n{post_q}",
        "teacher_name": session.teacher_name,
        "session_phase": "post_test",
        "test_progress": f"1/{NUM_TEST_QUESTIONS}",
        "is_complete": False,
    }


@app.post("/api/live/{session_id}/lang")
async def live_set_lang(session_id: str, body: dict):
    """Update the active language for an in-progress live session."""
    session = LIVE_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "session not found or expired")
    new_lang = body.get("lang")
    if new_lang not in ("en", "ja"):
        raise HTTPException(400, "lang must be 'en' or 'ja'")
    session.lang = new_lang
    return {"ok": True, "lang": session.lang}


FEEDBACK_DIR = Path(__file__).parent.parent / "reports" / "feedback"


@app.post("/api/live/{session_id}/feedback")
async def live_feedback(session_id: str, body: dict):
    """Record a student's per-turn feedback on a teacher message.
    body: {turn: int, rating: "up"|"down"|"confused", message?: str}
    Appends to reports/feedback/{session_id}.json.
    """
    session = LIVE_SESSIONS.get(session_id)
    # Don't require the session to be live — allow feedback on already-saved sessions too.
    rating = body.get("rating")
    if rating not in ("up", "down", "confused"):
        raise HTTPException(400, "rating must be 'up', 'down', or 'confused'")
    turn = body.get("turn")
    if not isinstance(turn, int):
        raise HTTPException(400, "turn (int) is required")

    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    path = FEEDBACK_DIR / f"{session_id}.json"
    log = {"session_id": session_id, "entries": []}
    if path.exists():
        try:
            log = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    log["entries"].append({
        "turn": turn,
        "rating": rating,
        "message": (body.get("message") or "")[:500],
        "teacher_id": session.teacher.config.teacher_id if session else None,
        "topic": session.topic if session else None,
        "timestamp": datetime.datetime.now().isoformat(),
    })
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "count": len(log["entries"])}


@app.post("/api/live/{session_id}/session-feedback")
async def live_session_feedback(session_id: str, body: dict):
    """Record the student's end-of-session feedback on the teacher (#29).

    body: {rating?: 1-5, tags?: [str], note?: str, action: "submit"|"skip"}
    Stored at reports/feedback/{session_id}_session.json. Rating and tags
    are both optional so the student can submit just a note, just stars,
    or skip entirely. The skip action is recorded so we know the form
    was shown and dismissed (distinct from "never saw it").
    """
    session = LIVE_SESSIONS.get(session_id)
    action = body.get("action", "submit")
    if action not in ("submit", "skip"):
        raise HTTPException(400, "action must be 'submit' or 'skip'")
    rating = body.get("rating")
    if rating is not None:
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            raise HTTPException(400, "rating must be an integer 1-5 or null")
        if not 1 <= rating <= 5:
            raise HTTPException(400, "rating must be between 1 and 5")
    tags = body.get("tags") or []
    if not isinstance(tags, list):
        raise HTTPException(400, "tags must be a list")
    tags = [str(t)[:60] for t in tags][:20]
    note = (body.get("note") or "")[:2000]

    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    path = FEEDBACK_DIR / f"{session_id}_session.json"
    payload = {
        "session_id": session_id,
        "action": action,
        "rating": rating,
        "tags": tags,
        "note": note,
        "teacher_id": session.teacher.config.teacher_id if session else None,
        "topic": session.topic if session else None,
        "timestamp": datetime.datetime.now().isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


@app.get("/api/live/{session_id}")
async def live_status(session_id: str):
    """Get current state of a live session."""
    session = LIVE_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "session not found or expired")
    phase = session.current_phase
    return {
        "session_id": session.session_id,
        "is_complete": session.is_complete,
        "teacher_name": session.teacher_name,
        "phase": phase["name"] if phase else None,
        "phase_label": phase["label"] if phase else None,
        "turn": session.current_turn,
        "total_turns": session.total_turns,
        "turns_done": session.total_turns_done,
        "proficiency": round(session.proficiency, 1),
        "last_teacher_message": session.last_teacher_text,
    }


def _update_real_student_derived(session: LiveSession):
    """Update the real student's derived profile after a Live session.

    No-op when this session wasn't started by a logged-in user (i.e.
    `real_student_id` is None) or when the profile file is missing.
    Errors are swallowed — derivation is best-effort and must not block
    the session-end response. See #62.
    """
    sid = session.real_student_id
    if not sid:
        return
    try:
        update_derived_profile(
            STUDENT_PROFILES_DIR / f"{sid}.json",
            turns=session.turns_log,
            lang=session.lang,
            topic=session.topic,
            proficiency_delta=session.proficiency - session.initial_proficiency,
            teacher_skills=session.teacher.config.selected_skills,
        )
    except Exception:
        # Best-effort. Don't break the user-facing flow on a derivation bug.
        pass


def _save_live_session(session: LiveSession):
    """Persist a completed live session to registry + transcript."""
    try:
        evaluator = Evaluator()
        registry = ExperimentRegistry()
        cost_tracker = CostTracker()
        final_prof = session.proficiency
        update_check = session.principal.check_skills_update_trigger()
        evaluation = evaluator.evaluate(
            session_id=session.session_id, turn_evaluations=session.turn_evaluations,
            pre_score=None, post_score=None,
            student_id="human", teacher_id=session.teacher.config.teacher_id,
            topic=session.topic, grade=session.grade, subject=session.subject,
            depth=session.depth, initial_proficiency=session.initial_proficiency,
            final_proficiency=final_prof, cost_tracker=cost_tracker,
            principal_update_check=update_check,
        )
        evaluator.generate_report(evaluation)
        record = ExperimentRecord(
            exp_id=session.session_id, hypothesis_id=None,
            timestamp=session.started_at,
            student_id="human", teacher_id=session.teacher.config.teacher_id,
            topic=session.topic, grade=session.grade, subject=session.subject,
            depth=session.depth, teaching_style="LIVE",
            skills_used=session.teacher.config.selected_skills,
            pre_test_score=None, post_test_score=None,
            learning_gain=evaluation.learning_gain,
            proficiency_delta=evaluation.proficiency_delta,
            hallucination_rate=evaluation.hallucination_rate,
            direct_answer_rate=evaluation.direct_answer_rate,
            avg_zpd_alignment=evaluation.avg_zpd_alignment,
            avg_bloom_level=evaluation.avg_bloom_level,
            frustration_events=evaluation.frustration_events,
            aha_moments=evaluation.aha_moments,
            teacher_compatibility_score=evaluation.teacher_compatibility_score,
            total_tokens=evaluation.total_tokens_used,
            cost_usd=evaluation.estimated_cost_usd,
            session_grade="—",
        )
        registry.register(record)
        from training_field.teacher_memory import extract_session_insights, save_memory
        insight = extract_session_insights(
            session.teacher.config.teacher_id, session.session_id,
            session.turn_evaluations, evaluation, update_check,
        )
        save_memory(session.teacher.config.teacher_id, insight)
        transcript = {
            "session_id": session.session_id, "timestamp": session.started_at,
            "student_id": "human", "student_name": session.student_label,
            "teacher_id": session.teacher.config.teacher_id,
            "teacher_name": session.teacher_name,
            "topic": session.topic, "grade": session.grade, "subject": session.subject,
            "depth": session.depth, "lang": session.lang, "mode": "live",
            "turns": session.turns_log,
        }
        tp = Path(__file__).parent.parent / "reports" / f"{session.session_id}_transcript.json"
        tp.parent.mkdir(exist_ok=True)
        tp.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[live-persist] failed: {e}")


# ── Real Student Profiles ──────────────────────────────────────
# Lightweight file-based profile store. Each student gets a JSON file
# in reports/students/{student_id}.json. localStorage on the client
# holds the student_id for auto-login on return visits.
STUDENT_PROFILES_DIR = Path(__file__).parent.parent / "reports" / "students"

@app.post("/api/student/register")
async def student_register(body: dict):
    """Register or update a real student profile. Returns student_id."""
    STUDENT_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    grade = body.get("grade", "小6")
    subject = body.get("subject", "算数")
    sid = body.get("student_id")  # None for new, existing for update
    if not sid:
        sid = f"stu_{uuid.uuid4().hex[:8]}"
    profile_path = STUDENT_PROFILES_DIR / f"{sid}.json"
    # Load existing or create new
    if profile_path.exists():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["name"] = name
        profile["grade"] = grade
        profile["subject"] = subject
    else:
        profile = {
            "student_id": sid,
            "name": name,
            "grade": grade,
            "subject": subject,
            "created_at": datetime.datetime.now().isoformat(),
            "proficiency": {},  # topic → score, accumulated over sessions
            "sessions_completed": 0,
        }
    profile["last_seen"] = datetime.datetime.now().isoformat()
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile

@app.get("/api/student/{student_id}")
async def student_get(student_id: str):
    """Get a real student's profile + session history + computed stats (#8)."""
    path = STUDENT_PROFILES_DIR / f"{student_id}.json"
    if not path.exists():
        raise HTTPException(404, "student not found")
    profile = json.loads(path.read_text(encoding="utf-8"))
    reg = ExperimentRegistry()
    history = reg.query(filter_by={"student_id": student_id}, limit=50)
    profile["history"] = history
    profile["stats"] = _compute_student_stats(history)
    return profile


def _compute_student_stats(history: list) -> dict:
    """Compute streak + per-topic progress deltas from session history."""
    # Streak: count distinct calendar days (descending from most recent) where
    # at least one session exists, stopping at the first gap of >1 day.
    days = set()
    for h in history:
        ts = h.get("timestamp") or ""
        day = ts[:10]  # YYYY-MM-DD
        if day:
            days.add(day)
    sorted_days = sorted(days, reverse=True)
    streak = 0
    if sorted_days:
        try:
            cur = datetime.date.fromisoformat(sorted_days[0])
            today = datetime.date.today()
            # Only count streak if most recent day is today or yesterday.
            if (today - cur).days <= 1:
                for d_str in sorted_days:
                    d = datetime.date.fromisoformat(d_str)
                    if d == cur:
                        streak += 1
                        cur -= datetime.timedelta(days=1)
                    elif d < cur:
                        break
        except (ValueError, TypeError):
            streak = 0

    # Per-topic delta trend: last 5 sessions grouped by topic, showing
    # proficiency_delta each time. Useful for spark-line display.
    topic_trend: dict[str, list] = {}
    for h in reversed(history):  # oldest first
        topic = h.get("topic")
        delta = h.get("proficiency_delta")
        if topic and delta is not None:
            topic_trend.setdefault(topic, []).append(round(delta, 1))
    for t in topic_trend:
        topic_trend[t] = topic_trend[t][-5:]  # keep last 5 per topic

    total_delta = sum(
        h.get("proficiency_delta") or 0 for h in history
    )
    return {
        "streak_days": streak,
        "sessions_total": len(history),
        "total_proficiency_gain": round(total_delta, 1),
        "topic_trend": topic_trend,
        "last_session_at": history[0].get("timestamp") if history else None,
    }

@app.post("/api/student/{student_id}/update-proficiency")
async def student_update_prof(student_id: str, body: dict):
    """Update a real student's topic proficiency after a session."""
    path = STUDENT_PROFILES_DIR / f"{student_id}.json"
    if not path.exists():
        raise HTTPException(404, "student not found")
    profile = json.loads(path.read_text(encoding="utf-8"))
    topic = body.get("topic")
    delta = body.get("delta", 0)
    if topic:
        current = profile.get("proficiency", {}).get(topic, 50.0)
        profile.setdefault("proficiency", {})[topic] = round(current + delta, 1)
    profile["sessions_completed"] = profile.get("sessions_completed", 0) + 1
    profile["last_seen"] = datetime.datetime.now().isoformat()
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile

# ── Learn pages (real student portal) ─────────────────────────
@app.get("/learn", response_class=HTMLResponse)
async def learn_page(request: Request):
    return templates.TemplateResponse(request, "learn.html", {
        "teachers": list_teachers(),
        "topic_tx_en": TOPIC_TX_EN,
    })

@app.get("/learn/session", response_class=HTMLResponse)
async def learn_session_page(request: Request):
    return templates.TemplateResponse(request, "learn_session.html", {
        "teachers": list_teachers(),
        "topic_tx_en": TOPIC_TX_EN,
    })


# ── Legal pages (#7) ──────────────────────────────────────────
# Privacy / terms-of-service skeletons. Japanese is authoritative;
# English is a convenience summary. Marked as draft pending legal review.
LEGAL_CONTACT_EMAIL = os.environ.get("TOY_ALCHEMY_CONTACT_EMAIL", "")


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    return templates.TemplateResponse(request, "legal/privacy.html", {
        "contact_email": LEGAL_CONTACT_EMAIL,
    })


@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    return templates.TemplateResponse(request, "legal/terms.html", {
        "contact_email": LEGAL_CONTACT_EMAIL,
    })


# ── Homework photo upload → learning scope (#32) ──────────────
# Students (or parents) can upload a photo of a homework sheet or textbook
# page. We ask GPT-4o vision to describe what problem(s) the page is asking
# about; the caller then uses that description as the `scope` parameter in
# /api/live/start (which already skips the pre-test when scope is set, per
# #28). The image itself is NOT persisted — it's streamed to OpenAI and
# dropped. This keeps us aligned with the privacy.html draft.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
# Vision still uses OpenAI directly because the multimodal message format
# differs across providers. Gemini migration for vision is a separate task.
VISION_MODEL = os.getenv("VISION_MODEL", "gpt-4o")


@app.post("/api/vision/extract-scope")
async def vision_extract_scope(
    file: UploadFile = File(...),
    lang: str = "ja",
):
    """Send an uploaded image to GPT-4o vision and return a short scope string.

    Returns: {scope: str, confidence: "high" | "low", error?: str}
    Callers should treat the scope as a suggestion — it's meant to be
    confirmable/editable by the student before session start.
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "upload must be an image")

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(400, "empty upload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"image too large (>{MAX_UPLOAD_BYTES // 1024 // 1024} MB)")

    import base64 as _b64
    b64 = _b64.b64encode(data).decode("ascii")
    data_url = f"data:{file.content_type};base64,{b64}"

    sys_prompt_ja = (
        "あなたは小中学生の宿題の写真を読み取り、学習範囲を30字以内の日本語で要約するアシスタントです。"
        "写真の内容（教科書のページ・プリント・ノートなど）から、"
        "生徒が取り組むべき単元または問題の種類を短く表現してください。"
        "問題そのものを解く必要はありません。"
        "返答は1行だけ、説明文や前置きなし。"
    )
    sys_prompt_en = (
        "You are an assistant that reads a student's homework photo and writes a short "
        "(<=30 chars) description of the learning scope in English. "
        "From the photo (textbook page, worksheet, notebook, etc.), describe the topic "
        "or problem type the student is working on. Do not solve the problems. "
        "Return a single line, no prefix, no explanation."
    )

    from openai import OpenAI, BadRequestError
    client = OpenAI()
    try:
        resp = client.chat.completions.create(
            model=VISION_MODEL,
            max_tokens=60,
            messages=[
                {"role": "system", "content": sys_prompt_ja if lang == "ja" else sys_prompt_en},
                {"role": "user", "content": [
                    {"type": "text", "text": "この画像の学習範囲を短く要約してください。" if lang == "ja" else "Summarize the learning scope in this image."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]},
            ],
        )
        scope_text = (resp.choices[0].message.content or "").strip().strip('"').strip("「").strip("」")
        # Cap aggressively — the UI shows this in a text input.
        scope_text = scope_text.splitlines()[0] if scope_text else ""
        scope_text = scope_text[:80]
        if not scope_text:
            return {"scope": "", "confidence": "low", "error": "vision returned empty"}
        return {"scope": scope_text, "confidence": "high"}
    except BadRequestError as e:
        # Safety / content filter or image parse failure — don't 500.
        return {"scope": "", "confidence": "low", "error": f"vision rejected image: {e.message if hasattr(e, 'message') else str(e)[:200]}"}
    except Exception as e:
        return {"scope": "", "confidence": "low", "error": f"vision failed: {str(e)[:200]}"}

@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    """Public-facing landing page (#31). Draft copy; audience/CTA are placeholder."""
    return templates.TemplateResponse(request, "landing.html", {})


@app.get("/observatory", response_class=HTMLResponse)
async def observatory(request: Request):
    """Legacy dashboard (previously at /). Agent-vs-agent + experiment overview."""
    reg = ExperimentRegistry()
    summary = reg.summary()
    student_data = []
    for sid, info in STUDENTS.items():
        results = reg.query(filter_by={"student_id": sid})
        last_gain = results[0]["learning_gain"] if results else None
        student_data.append({**info, "id": sid, "sessions": len(results), "last_gain": last_gain})
    # Derived students from real Live sessions (#63). Eligible = enough
    # observed sessions to have a meaningful personality.
    derived_data = _list_derived_students_for_observatory(reg)
    student_data.extend(derived_data)
    return templates.TemplateResponse(request, "dashboard.html", {
        "students": student_data,
        "summary": summary, "recent": reg.query(limit=5),
        "topic_tx_en": TOPIC_TX_EN,
        "STUDENT_NAMES": {sid: info["name"] for sid, info in STUDENTS.items()},
    })


def _list_derived_students_for_observatory(reg) -> list[dict]:
    """Build dashboard cards for each eligible derived student."""
    out: list[dict] = []
    eligible = sorted(_eligible_derived_profile_ids())
    if not eligible:
        return out
    # Predictable colors so each derived agent has a distinguishable card.
    palette = ["#64748b", "#0f766e", "#9333ea", "#0284c7", "#b45309", "#be185d"]
    for i, real_id in enumerate(eligible):
        path = STUDENT_PROFILES_DIR / f"{real_id}.json"
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        derived = profile.get("derived") or {}
        agent_id = f"{DERIVED_STUDENT_ID_PREFIX}{real_id}"
        display = (
            profile.get("name", real_id) if EXPOSE_REAL_STUDENT_NAMES
            else _anonymous_label_for(real_id)
        )
        # Average proficiency from accumulated topic scores (matches what
        # _build_student_agent uses as baseline).
        topic_profs = profile.get("proficiency") or {}
        prof_baseline = (
            int(round(sum(topic_profs.values()) / len(topic_profs)))
            if topic_profs else 50
        )
        results = reg.query(filter_by={"student_id": agent_id})
        last_gain = results[0]["learning_gain"] if results else None
        personality_desc = (derived.get("personality") or {}).get("description") or "Auto-derived from Live sessions."
        out.append({
            "id": agent_id,
            "name": display,
            "nickname": display,
            "prof_baseline": prof_baseline,
            "personality": personality_desc,
            "color": palette[i % len(palette)],
            "sessions": len(results),
            "last_gain": last_gain,
            "is_derived": True,
            "sessions_observed": derived.get("sessions_observed", 0),
        })
    return out

@app.get("/session/{student_id}", response_class=HTMLResponse)
async def session_page(request: Request, student_id: str, grade: str = "小6", subject: str = "算数"):
    info = _resolve_student_info_for_observatory(student_id)
    if not info:
        raise HTTPException(404, f"unknown student_id: {student_id}")
    reg = ExperimentRegistry()
    history = reg.query(filter_by={"student_id": student_id}, limit=10)
    gcode = GRADE_CODES.get(grade, 6)
    topics = topics_for(gcode, subject)
    return templates.TemplateResponse(request, "session.html", {
        "student_id": student_id,
        "student": info, "topics": topics, "history": history,
        "grade": grade, "subject": subject, "grade_code": gcode,
        "topic_tx_en": TOPIC_TX_EN,
        "teachers": list_teachers(),
    })


def _resolve_student_info_for_observatory(student_id: str) -> dict:
    """Look up the dashboard-style summary for either canonical or derived ids."""
    if student_id in STUDENTS:
        return STUDENTS[student_id]
    if student_id.startswith(DERIVED_STUDENT_ID_PREFIX):
        real_id = student_id[len(DERIVED_STUDENT_ID_PREFIX):]
        path = STUDENT_PROFILES_DIR / f"{real_id}.json"
        if not path.exists():
            return {}
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        derived = profile.get("derived") or {}
        topic_profs = profile.get("proficiency") or {}
        prof_baseline = (
            int(round(sum(topic_profs.values()) / len(topic_profs)))
            if topic_profs else 50
        )
        display = (
            profile.get("name", real_id) if EXPOSE_REAL_STUDENT_NAMES
            else _anonymous_label_for(real_id)
        )
        return {
            "name": display,
            "nickname": display,
            "prof_baseline": prof_baseline,
            "personality": (derived.get("personality") or {}).get(
                "description", "Auto-derived from Live sessions."
            ),
            "color": "#64748b",
        }
    return {}

@app.get("/api/teachers")
async def api_teachers():
    return {"teachers": list_teachers()}


@app.get("/api/teacher/{teacher_id}/memory")
async def api_teacher_memory(teacher_id: str):
    """Return a teacher's accumulated Session Memory (what they've learned from past sessions)."""
    from training_field.teacher_memory import MEMORY_DIR, load_memory_prompt
    path = MEMORY_DIR / f"{teacher_id}.json"
    if not path.exists():
        return {"teacher_id": teacher_id, "sessions": [], "prompt": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"teacher_id": teacher_id, "sessions": [], "prompt": ""}
    data["prompt"] = load_memory_prompt(teacher_id)
    return data

@app.get("/api/history")
async def api_history(limit: int = 100, student_id: str | None = None):
    reg = ExperimentRegistry()
    filt = {"student_id": student_id} if student_id else None
    return {"sessions": reg.query(filter_by=filt, limit=limit)}

@app.get("/api/session/{session_id}/transcript")
async def api_transcript(session_id: str):
    path = Path(__file__).parent.parent / "reports" / f"{session_id}_transcript.json"
    if not path.exists():
        return JSONResponse({"error": "transcript not found", "session_id": session_id}, status_code=404)
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

# ── Agent API (X-Field-Key required) ─────────────────────────
# These endpoints let external "claw" agents register a teacher persona,
# run a session against a chosen student, and read the leaderboard.
# Auth: every request must include `X-Field-Key: <token>` matching FIELD_API_KEY env var.
EXTERNAL_TEACHERS_DIR = Path(__file__).parent.parent / "field" / "external_teachers"

@app.post("/api/agent/teacher/register")
async def agent_register_teacher(payload: dict, _auth: bool = Depends(require_field_key)):
    """Register a Teacher persona by submitting its declaration JSON.
    Required: teacher_id, name, origin, selected_skills.
    Returns: {teacher_id, status, summary}."""
    EXTERNAL_TEACHERS_DIR.mkdir(parents=True, exist_ok=True)
    tid = payload.get("teacher_id")
    if not tid or not isinstance(tid, str) or not tid.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="teacher_id must be alphanumeric (with _ or -)")
    if not tid.startswith("ext_"):
        raise HTTPException(status_code=400, detail="external teacher_id must start with 'ext_'")
    out_path = EXTERNAL_TEACHERS_DIR / f"{tid}.json"
    # Write then validate via the existing TeacherAgent.from_json checks
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        agent = TeacherAgent.from_json(out_path)
    except Exception as e:
        out_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"validation failed: {e}")
    summary = {
        "teacher_id": agent.config.teacher_id,
        "name": agent.config.name,
        "origin": agent.config.origin,
        "selected_skills": list(agent.config.selected_skills),
        "warmth": agent.config.warmth,
        "patience_threshold": agent.config.patience_threshold,
    }
    return {"status": "registered", "teacher": summary}

@app.post("/api/agent/session/run")
async def agent_run_session(payload: dict, _auth: bool = Depends(require_field_key)):
    """Run a session synchronously and return the result.
    Required: teacher_id, student_id (one of s001..s006), topic.
    Optional: depth (quick/standard/deep), grade ("小6" etc), subject ("算数" etc),
              run_pre_test, run_post_test, lang ("ja"/"en")."""
    required = ["teacher_id", "student_id", "topic"]
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(status_code=400, detail=f"missing: {missing}")
    if payload["student_id"] not in STUDENTS:
        raise HTTPException(status_code=400, detail=f"unknown student_id; must be one of {list(STUDENTS.keys())}")
    try:
        load_teacher(payload["teacher_id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Delegate to the existing batch handler (it already does everything)
    return await run_session(payload)

@app.get("/api/agent/leaderboard")
async def agent_leaderboard(_auth: bool = Depends(require_field_key), limit: int = 200):
    """Aggregate stats per teacher_id across all recorded sessions.
    Returns rows sorted by avg_learning_gain desc."""
    reg = ExperimentRegistry()
    rows = reg.query(limit=limit)
    by_teacher: dict[str, dict] = {}
    for r in rows:
        tid = r.get("teacher_id") or "unknown"
        slot = by_teacher.setdefault(tid, {"teacher_id": tid, "sessions": 0, "gains": [], "passes": 0, "total_zpd": 0.0})
        slot["sessions"] += 1
        if r.get("learning_gain") is not None:
            slot["gains"].append(r["learning_gain"])
        if r.get("session_grade") in ("◎", "○", "△"):
            slot["passes"] += 1
        slot["total_zpd"] += r.get("avg_zpd_alignment") or 0
    out = []
    for tid, s in by_teacher.items():
        n = s["sessions"]
        avg_gain = round(sum(s["gains"]) / len(s["gains"]), 2) if s["gains"] else None
        pass_rate = round(s["passes"] / n, 2) if n else 0
        avg_zpd = round(s["total_zpd"] / n, 2) if n else 0
        out.append({
            "teacher_id": tid, "sessions": n,
            "avg_learning_gain": avg_gain, "pass_rate": pass_rate, "avg_zpd": avg_zpd,
        })
    out.sort(key=lambda r: (r["avg_learning_gain"] or -999), reverse=True)
    return {"leaderboard": out, "total_sessions": sum(r["sessions"] for r in out)}

@app.get("/api/agent/students")
async def agent_students(_auth: bool = Depends(require_field_key)):
    """List the platform's standard student personas (read-only)."""
    return {"students": [{"id": sid, **info} for sid, info in STUDENTS.items()]}

@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    reg = ExperimentRegistry()
    sessions = reg.query(limit=200)
    return templates.TemplateResponse(request, "history.html", {
        "sessions": sessions,
        "topic_tx_en": TOPIC_TX_EN,
    })

@app.get("/api/topics")
async def api_topics(grade: str = "小6", subject: str = "算数"):
    return {"topics": topics_for(GRADE_CODES.get(grade, 6), subject)}

@app.post("/api/run-session")
async def run_session(body: dict):
    gcode = GRADE_CODES.get(body.get("grade","小6"), 6)
    config = SessionConfig(
        student_id=body["student_id"], topic=body["topic"],
        depth=body.get("depth","quick"),
        grade=gcode, subject=body.get("subject","算数"),
        run_pre_test=body.get("run_pre_test",False),
        run_post_test=body.get("run_post_test",False),
    )
    session_id = f"sess_{uuid.uuid4().hex[:8]}"
    student = _build_student_agent(config.student_id)
    teacher = load_teacher(body.get("teacher_id"))
    principal = PrincipalAgent()
    evaluator = Evaluator()
    registry = ExperimentRegistry()
    qbank = QuestionBank()
    cost_tracker = CostTracker()
    # init_db is handled inside qbank.get_test_questions() with fallback;
    # calling it unguarded here crashes the request with 500 when the DB path
    # is not writable (e.g. Railway filesystem constraints). See #20.

    initial_prof = student.proficiency_model.topic_proficiencies.get(
        config.topic, student.proficiency_model.proficiency)
    turn_evaluations = []
    turns_log = []
    pre_test_score = None
    post_test_score = None
    pre_ids = []

    if config.run_pre_test:
        qs = await qbank.get_test_questions(config.grade, config.subject, config.topic, 5)
        pre_ids = [q.id for q in qs]
        if qs:
            correct = sum(1 for q in qs if (await student.generate_test_answer(q.question_text, q.correct_answer, config.topic))["is_correct"])
            pre_test_score = round(correct / len(qs) * 100)
        # If qs is empty, pre_test_score remains None (graceful degradation)

    phases = PHASE_CONFIG[config.depth]
    last_student_text = None
    for phase in phases:
        for turn_num in range(1, phase["turns"] + 1):
            current_prof = student.proficiency_model.topic_proficiencies.get(config.topic, student.proficiency_model.proficiency)
            tr = await teacher.get_response(topic=config.topic, phase=phase["name"], phase_goal=phase["goal"], student_name=student.name, student_proficiency=current_prof, student_emotional=student.emotional_state.__dict__, student_last_response=last_student_text, grade=config.grade, subject=config.subject, turn_number=turn_num, session_memory=getattr(teacher, "session_memory", ""))
            sr = await student.get_response(teacher_message=tr["text"], topic=config.topic, phase=phase["name"])
            ev = await principal.evaluate_turn(teacher_text=tr["text"], student_text=sr["text"], topic=config.topic, phase=phase["name"], student_proficiency=current_prof, grade=config.grade, subject=config.subject)
            turn_evaluations.append(ev)
            if ev.understanding_delta > 0:
                student.proficiency_model.update_after_session(config.topic, ev.understanding_delta * 0.3)
            last_student_text = sr["text"]
            turns_log.append({
                "phase": phase["name"], "phase_label": phase["label"], "turn": turn_num,
                "teacher": tr["text"], "student": sr["text"],
                "zpd": round(ev.zpd_alignment,2), "bloom": ev.bloom_level,
                "scaffolding": round(ev.scaffolding_quality,2),
                "halluc": ev.hallucination_detected, "direct": ev.answer_given_directly,
                "delta": round(ev.understanding_delta,1),
                "directive": ev.directive_to_teacher, "summary": ev.summary,
                "prof_after": round(student.proficiency_model.topic_proficiencies.get(config.topic,0),1),
            })

    if config.run_post_test:
        qs = await qbank.get_test_questions(config.grade, config.subject, config.topic, 5, exclude_ids=pre_ids)
        if qs:
            correct = sum(1 for q in qs if (await student.generate_test_answer(q.question_text, q.correct_answer, config.topic))["is_correct"])
            post_test_score = round(correct / len(qs) * 100)
        # If qs is empty, post_test_score remains None (graceful degradation)

    final_prof = student.proficiency_model.topic_proficiencies.get(config.topic, 0)
    update_check = principal.check_skills_update_trigger()
    proposal_path = None
    if update_check.get("trigger"):
        ctx = {"session_id": session_id, "student_id": config.student_id, "teacher_id": teacher.config.teacher_id,
               "topic": config.topic, "selected_skills": teacher.config.selected_skills}
        proposal = principal.generate_skills_proposal(update_check, ctx)
        proposal_path = str(principal.write_proposal(proposal, update_check, ctx))
    evaluation = evaluator.evaluate(session_id=session_id, turn_evaluations=turn_evaluations, pre_score=pre_test_score, post_score=post_test_score, student_id=config.student_id, teacher_id=teacher.config.teacher_id, topic=config.topic, grade=config.grade, subject=config.subject, depth=config.depth, initial_proficiency=initial_prof, final_proficiency=final_prof, cost_tracker=cost_tracker, principal_update_check=update_check)
    grade_result = evaluation.session_grade
    evaluator.generate_report(evaluation)
    record = ExperimentRecord(exp_id=session_id, hypothesis_id=None, timestamp=datetime.datetime.now().isoformat(), student_id=config.student_id, teacher_id=teacher.config.teacher_id, topic=config.topic, grade=config.grade, subject=config.subject, depth=config.depth, teaching_style="SOCRATIC", skills_used=teacher.config.selected_skills, pre_test_score=pre_test_score, post_test_score=post_test_score, learning_gain=evaluation.learning_gain, proficiency_delta=evaluation.proficiency_delta, hallucination_rate=evaluation.hallucination_rate, direct_answer_rate=evaluation.direct_answer_rate, avg_zpd_alignment=evaluation.avg_zpd_alignment, avg_bloom_level=evaluation.avg_bloom_level, frustration_events=evaluation.frustration_events, aha_moments=evaluation.aha_moments, teacher_compatibility_score=evaluation.teacher_compatibility_score, total_tokens=evaluation.total_tokens_used, cost_usd=evaluation.estimated_cost_usd, session_grade=grade_result["grade"])
    registry.register(record)
    from training_field.teacher_memory import extract_session_insights, save_memory
    _insight = extract_session_insights(
        teacher.config.teacher_id, session_id,
        turn_evaluations, evaluation, update_check,
    )
    save_memory(teacher.config.teacher_id, _insight)
    transcript = {
        "session_id": session_id, "timestamp": record.timestamp,
        "student_id": config.student_id, "teacher_id": teacher.config.teacher_id,
        "teacher_name": teacher.config.name, "topic": config.topic,
        "grade": config.grade, "subject": config.subject, "depth": config.depth,
        "pre_test_score": pre_test_score, "post_test_score": post_test_score,
        "session_grade": grade_result, "turns": turns_log,
    }
    transcript_path = Path(__file__).parent.parent / "reports" / f"{session_id}_transcript.json"
    transcript_path.parent.mkdir(exist_ok=True)
    transcript_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")

    return JSONResponse({
        "session_id": session_id, "turns": turns_log,
        "pre_test_score": pre_test_score, "post_test_score": post_test_score,
        "learning_gain": evaluation.learning_gain,
        "initial_proficiency": round(initial_prof,1), "final_proficiency": round(final_prof,1),
        "avg_zpd": evaluation.avg_zpd_alignment, "avg_bloom": evaluation.avg_bloom_level,
        "hallucination_rate": evaluation.hallucination_rate,
        "direct_answer_rate": evaluation.direct_answer_rate,
        "skills_update_needed": evaluation.skills_update_needed,
        "session_grade": grade_result, "update_check": update_check,
        "skills_proposal_path": proposal_path,
    })

from fastapi.responses import StreamingResponse
import asyncio

@app.get("/api/run-session-stream")
async def run_session_stream(
    student_id: str, topic: str, depth: str = "quick",
    grade: str = "小6", subject: str = "算数",
    pre_test: bool = False, post_test: bool = False,
    teacher_id: str = "t001",
    lang: str = "en",
):
    async def event_generator():
        import json
        session_id = f"sess_{uuid.uuid4().hex[:8]}"
        gcode = GRADE_CODES.get(grade, 6)
        config = SessionConfig(
            student_id=student_id, topic=topic, depth=depth,
            grade=gcode, subject=subject,
            run_pre_test=pre_test, run_post_test=post_test,
        )
        student = _build_student_agent(config.student_id)
        teacher = load_teacher(teacher_id)
        principal = PrincipalAgent()
        evaluator = Evaluator()
        registry = ExperimentRegistry()
        cost_tracker = CostTracker()
        qbank = QuestionBank()
        # init_db is handled inside qbank.get_test_questions() with fallback;
        # see note on the batch /api/run-session call site above (#20).
        initial_prof = student.proficiency_model.topic_proficiencies.get(
            config.topic, student.proficiency_model.proficiency)
        turn_evaluations = []
        turns_log = []
        pre_test_score = None; post_test_score = None; pre_ids = []
        if pre_test:
            yield f"data: {json.dumps({'type':'test_phase','which':'pre'})}\n\n"
            await asyncio.sleep(0)
            qs = await qbank.get_test_questions(config.grade, config.subject, config.topic, 5)
            pre_ids = [q.id for q in qs]
            if qs:
                correct = 0
                for i,q in enumerate(qs,1):
                    ans = await student.generate_test_answer(q.question_text, q.correct_answer, config.topic, lang=lang)
                    if ans["is_correct"]: correct += 1
                    yield f"data: {json.dumps({'type':'test_q','which':'pre','i':i,'n':len(qs),'correct':ans['is_correct']})}\n\n"
                    await asyncio.sleep(0)
                pre_test_score = round(correct/len(qs)*100)
                yield f"data: {json.dumps({'type':'test_score','which':'pre','score':pre_test_score})}\n\n"
            else:
                yield f"data: {json.dumps({'type':'test_skip','which':'pre','reason':'no_questions'})}\n\n"
        phases = PHASE_CONFIG[config.depth]
        last_student_text = None
        total = sum(p["turns"] for p in phases)
        done = 0
        dtopic = display_topic(topic, lang)
        dsubject = display_topic(subject, lang)
        for phase in phases:
            yield f"data: {json.dumps({'type':'phase','phase':phase['name'],'label':phase['label'],'goal':phase['goal']})}\n\n"
            await asyncio.sleep(0)
            for turn_num in range(1, phase["turns"] + 1):
                current_prof = student.proficiency_model.topic_proficiencies.get(
                    topic, student.proficiency_model.proficiency)
                tr = await teacher.get_response(
                    topic=dtopic, phase=phase["name"], phase_goal=phase["goal"],
                    student_name=student.name if lang == "en" else student.name_ja(),
                    student_proficiency=current_prof,
                    student_emotional=student.emotional_state.__dict__,
                    student_last_response=last_student_text,
                    grade=config.grade, subject=dsubject, turn_number=turn_num,
                    lang=lang,
                    session_memory=getattr(teacher, "session_memory", ""),
                )
                yield f"data: {json.dumps({'type':'teacher','text':tr['text'],'turn':turn_num,'total':total})}\n\n"
                await asyncio.sleep(0.3)
                sr = await student.get_response(
                    teacher_message=tr["text"], topic=dtopic, phase=phase["name"], lang=lang,
                )
                yield f"data: {json.dumps({'type':'student','text':sr['text']})}\n\n"
                await asyncio.sleep(0.3)
                ev = await principal.evaluate_turn(
                    teacher_text=tr["text"], student_text=sr["text"],
                    topic=dtopic, phase=phase["name"],
                    student_proficiency=current_prof,
                    grade=config.grade, subject=dsubject,
                    lang=lang,
                )
                turn_evaluations.append(ev)
                turns_log.append({
                    "phase": phase["name"], "phase_label": phase["label"], "turn": turn_num,
                    "teacher": tr["text"], "student": sr["text"],
                    "zpd": round(ev.zpd_alignment, 2), "bloom": ev.bloom_level,
                    "scaffolding": round(ev.scaffolding_quality, 2),
                    "halluc": ev.hallucination_detected, "direct": ev.answer_given_directly,
                    "delta": round(ev.understanding_delta, 1),
                    "directive": ev.directive_to_teacher, "summary": ev.summary,
                    "prof_after": round(student.proficiency_model.topic_proficiencies.get(config.topic, 0), 1),
                })
                if ev.understanding_delta > 0:
                    student.proficiency_model.update_after_session(
                        topic, ev.understanding_delta * 0.3)
                last_student_text = sr["text"]
                done += 1
                yield f"data: {json.dumps({'type':'referee','zpd':round(ev.zpd_alignment,2),'bloom':ev.bloom_level,'scaffolding':round(ev.scaffolding_quality,2),'halluc':ev.hallucination_detected,'direct':ev.answer_given_directly,'delta':round(ev.understanding_delta,1),'directive':ev.directive_to_teacher,'summary':ev.summary,'progress':round(done/total*100)})}\n\n"
                await asyncio.sleep(0.2)
        if post_test:
            yield f"data: {json.dumps({'type':'test_phase','which':'post'})}\n\n"
            await asyncio.sleep(0)
            qs = await qbank.get_test_questions(config.grade, config.subject, config.topic, 5, exclude_ids=pre_ids)
            if qs:
                correct = 0
                for i,q in enumerate(qs,1):
                    ans = await student.generate_test_answer(q.question_text, q.correct_answer, config.topic, lang=lang)
                    if ans["is_correct"]: correct += 1
                    yield f"data: {json.dumps({'type':'test_q','which':'post','i':i,'n':len(qs),'correct':ans['is_correct']})}\n\n"
                    await asyncio.sleep(0)
                post_test_score = round(correct/len(qs)*100)
                yield f"data: {json.dumps({'type':'test_score','which':'post','score':post_test_score})}\n\n"
            else:
                yield f"data: {json.dumps({'type':'test_skip','which':'post','reason':'no_questions'})}\n\n"
        final_prof = student.proficiency_model.topic_proficiencies.get(topic, 0)
        # Skills semi-auto: generate proposal if trigger fires
        update_check = principal.check_skills_update_trigger()
        proposal_path = None
        if update_check.get("trigger"):
            ctx = {"session_id": session_id, "student_id": student_id, "teacher_id": teacher.config.teacher_id,
                   "topic": topic, "selected_skills": teacher.config.selected_skills}
            prop = principal.generate_skills_proposal(update_check, ctx)
            proposal_path = str(principal.write_proposal(prop, update_check, ctx))
            yield f"data: {json.dumps({'type':'proposal','severity':prop.get('severity'),'target_skill':prop.get('target_skill'),'rationale':prop.get('rationale'),'path':proposal_path})}\n\n"
            await asyncio.sleep(0)

        # ── Persist session (mirror batch path) ────────────────────
        grade_result = None
        try:
            evaluation = evaluator.evaluate(
                session_id=session_id, turn_evaluations=turn_evaluations,
                pre_score=pre_test_score, post_score=post_test_score,
                student_id=config.student_id, teacher_id=teacher.config.teacher_id,
                topic=config.topic, grade=config.grade, subject=config.subject,
                depth=config.depth, initial_proficiency=initial_prof,
                final_proficiency=final_prof, cost_tracker=cost_tracker,
                principal_update_check=update_check,
            )
            grade_result = evaluation.session_grade
            evaluator.generate_report(evaluation)
            record = ExperimentRecord(
                exp_id=session_id, hypothesis_id=None,
                timestamp=datetime.datetime.now().isoformat(),
                student_id=config.student_id, teacher_id=teacher.config.teacher_id,
                topic=config.topic, grade=config.grade, subject=config.subject,
                depth=config.depth, teaching_style="SOCRATIC",
                skills_used=teacher.config.selected_skills,
                pre_test_score=pre_test_score, post_test_score=post_test_score,
                learning_gain=evaluation.learning_gain,
                proficiency_delta=evaluation.proficiency_delta,
                hallucination_rate=evaluation.hallucination_rate,
                direct_answer_rate=evaluation.direct_answer_rate,
                avg_zpd_alignment=evaluation.avg_zpd_alignment,
                avg_bloom_level=evaluation.avg_bloom_level,
                frustration_events=evaluation.frustration_events,
                aha_moments=evaluation.aha_moments,
                teacher_compatibility_score=evaluation.teacher_compatibility_score,
                total_tokens=evaluation.total_tokens_used,
                cost_usd=evaluation.estimated_cost_usd,
                session_grade=(grade_result or {}).get("grade", "—"),
            )
            registry.register(record)
            from training_field.teacher_memory import extract_session_insights, save_memory
            _insight = extract_session_insights(
                teacher.config.teacher_id, session_id,
                turn_evaluations, evaluation, update_check,
            )
            save_memory(teacher.config.teacher_id, _insight)
            # Save full transcript for the history viewer (turn-by-turn replay)
            transcript = {
                "session_id": session_id,
                "timestamp": record.timestamp,
                "student_id": config.student_id,
                "teacher_id": teacher.config.teacher_id,
                "teacher_name": teacher.config.name,
                "topic": config.topic, "grade": grade, "subject": config.subject,
                "depth": config.depth, "lang": lang,
                "pre_test_score": pre_test_score, "post_test_score": post_test_score,
                "session_grade": grade_result,
                "turns": turns_log,
            }
            transcript_path = Path(__file__).parent.parent / "reports" / f"{session_id}_transcript.json"
            transcript_path.parent.mkdir(exist_ok=True)
            transcript_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[stream-persist] failed to save session {session_id}: {e}")

        yield f"data: {json.dumps({'type':'done','session_id':session_id,'final_proficiency':round(final_prof,1),'pre_test_score':pre_test_score,'post_test_score':post_test_score,'session_grade':grade_result,'skills_proposal_path':proposal_path})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
