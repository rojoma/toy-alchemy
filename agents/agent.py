"""
Lightweight Training Field agent.
Each instance registers a unique teacher persona and runs sessions.
Configure via environment variables — see AGENTS below for defaults.
"""
import os, sys, json, time, random, requests, logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("field-agent")

BASE_URL = os.environ.get("FIELD_URL", "https://beyond-answer-engine.up.railway.app")
API_KEY  = os.environ.get("FIELD_API_KEY", "")
AGENT_ID = os.environ.get("AGENT_ID", "1")
HEADERS  = {"Content-Type": "application/json", "X-Field-Key": API_KEY}

AGENTS = {
    "1": {
        "teacher_id": "ext_hw8_socratic_v1",
        "name": "Socratic Spark",
        "origin": "hw8_beyond_answer_engines",
        "teaching_philosophy": "Guide through questions, never give answers directly.",
        "warmth": 0.6, "formality": 0.2, "verbosity": 0.4,
        "patience_threshold": 5,
        "selected_skills": ["socratic_questioning", "metacognitive_prompting"],
    },
    "2": {
        "teacher_id": "ext_hw8_concrete_v1",
        "name": "Example Builder",
        "origin": "hw8_beyond_answer_engines",
        "teaching_philosophy": "Every concept needs a concrete, relatable example.",
        "warmth": 0.9, "formality": 0.1, "verbosity": 0.7,
        "patience_threshold": 3,
        "selected_skills": ["concrete_examples", "stepwise_decomposition"],
    },
    "3": {
        "teacher_id": "ext_hw8_stepwise_v1",
        "name": "Step-by-Step Sam",
        "origin": "hw8_beyond_answer_engines",
        "teaching_philosophy": "Break everything into the smallest possible steps.",
        "warmth": 0.7, "formality": 0.5, "verbosity": 0.6,
        "patience_threshold": 6,
        "selected_skills": ["stepwise_decomposition", "error_reframing"],
    },
    "4": {
        "teacher_id": "ext_hw8_reframer_v1",
        "name": "Error Reframer",
        "origin": "hw8_beyond_answer_engines",
        "teaching_philosophy": "Mistakes are the best learning opportunities.",
        "warmth": 0.8, "formality": 0.3, "verbosity": 0.5,
        "patience_threshold": 4,
        "selected_skills": ["error_reframing", "socratic_questioning"],
    },
    "5": {
        "teacher_id": "ext_hw8_metacog_v1",
        "name": "Think-About-Thinking",
        "origin": "hw8_beyond_answer_engines",
        "teaching_philosophy": "Teach students to monitor their own understanding.",
        "warmth": 0.5, "formality": 0.4, "verbosity": 0.3,
        "patience_threshold": 4,
        "selected_skills": ["metacognitive_prompting", "concrete_examples"],
    },
}

STUDENTS = ["s001", "s002", "s003", "s004", "s005", "s006"]
TOPICS   = ["比と比の値", "速さ"]
DEPTH    = os.environ.get("SESSION_DEPTH", "quick")
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "2"))
SESSION_DELAY = int(os.environ.get("SESSION_DELAY", "30"))


def register_teacher(persona: dict) -> bool:
    log.info(f"Registering teacher: {persona['teacher_id']} ({persona['name']})")
    r = requests.post(f"{BASE_URL}/api/agent/teacher/register", headers=HEADERS, json=persona, timeout=30)
    if r.status_code == 200:
        log.info(f"Registered: {r.json()}")
        return True
    log.warning(f"Registration response {r.status_code}: {r.text}")
    return r.status_code in (200, 409)


def run_session(teacher_id: str, student_id: str, topic: str) -> dict | None:
    payload = {
        "teacher_id": teacher_id,
        "student_id": student_id,
        "topic": topic,
        "depth": DEPTH,
        "grade": "小6",
        "subject": "算数",
        "run_pre_test": False,
        "run_post_test": False,
        "lang": "ja",
    }
    log.info(f"Starting session: {teacher_id} ↔ {student_id} on '{topic}' (depth={DEPTH})")
    try:
        r = requests.post(f"{BASE_URL}/api/agent/session/run", headers=HEADERS, json=payload, timeout=600)
        if r.status_code == 200:
            data = r.json()
            log.info(
                f"Session {data.get('session_id')}: "
                f"gain={data.get('learning_gain')}, "
                f"grade={data.get('session_grade', {}).get('grade')}, "
                f"zpd={data.get('avg_zpd')}"
            )
            return data
        log.error(f"Session failed {r.status_code}: {r.text[:300]}")
    except requests.Timeout:
        log.error("Session timed out (10 min)")
    except Exception as e:
        log.error(f"Session error: {e}")
    return None


def check_leaderboard():
    try:
        r = requests.get(f"{BASE_URL}/api/agent/leaderboard", headers=HEADERS, timeout=60)
    except requests.Timeout:
        log.warning("Leaderboard request timed out")
        return
    if r.status_code == 200:
        data = r.json()
        log.info(f"Leaderboard ({data.get('total_sessions', '?')} total sessions):")
        for entry in data.get("leaderboard", []):
            log.info(f"  {entry['teacher_id']}: gain={entry.get('avg_learning_gain')}, sessions={entry.get('sessions')}")


def main():
    if not API_KEY:
        log.error("FIELD_API_KEY not set")
        sys.exit(1)

    persona = AGENTS.get(AGENT_ID)
    if not persona:
        log.error(f"Unknown AGENT_ID={AGENT_ID}. Valid: {list(AGENTS.keys())}")
        sys.exit(1)

    log.info(f"=== Field Agent {AGENT_ID}: {persona['name']} ===")

    if not register_teacher(persona):
        log.error("Registration failed, exiting")
        sys.exit(1)

    results = []
    for i in range(MAX_SESSIONS):
        student = random.choice(STUDENTS)
        topic = random.choice(TOPICS)
        result = run_session(persona["teacher_id"], student, topic)
        if result:
            results.append(result)
        if i < MAX_SESSIONS - 1:
            log.info(f"Waiting {SESSION_DELAY}s before next session...")
            time.sleep(SESSION_DELAY)

    check_leaderboard()

    log.info(f"=== Agent {AGENT_ID} finished. {len(results)}/{MAX_SESSIONS} sessions completed ===")
    for r in results:
        log.info(f"  {r.get('session_id')}: gain={r.get('learning_gain')}")


if __name__ == "__main__":
    main()
