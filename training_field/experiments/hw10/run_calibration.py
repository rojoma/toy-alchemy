"""HW10 — Calibration experiment (Experiment 4).

Runs the same teacher (t001 Dr. Owen) on the same topic against:
  - s001 Emma (original AI persona, anxious low-baseline)
  - s007 Yuki (human-derived persona, calibrated from live_583e8c28 transcript)

The purpose is to measure how much Principal-rubric scores and learning-gain
estimates change when the Student Agent is calibrated against a real human's
response style (curt 4-15 char replies, frustration with abstract re-questioning).

This is the "first half-loop" of the Live -> Training Field calibration cycle:
human transcripts -> derived Student Agent -> re-evaluated leaderboard.
"""
from __future__ import annotations
import asyncio, json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from training_field.session_runner import run_training_session, SessionConfig

OUT = Path(__file__).parent / "results"
OUT.mkdir(parents=True, exist_ok=True)

# Same teacher, same topic, same depth, same language as the original Live session
# (live_583e8c28: t001 Dr. Owen × 対称な図形 × Yuki).
# Standard depth (12 turns) matches the live session length for fair comparison.
SESSIONS = [
    ("s001_emma_run2",         {"student_id": "s001", "topic": "対称な図形", "depth": "standard", "teacher_id": "t001",
                                "run_pre_test": False, "run_post_test": False}),
    ("s007_yuki_derived_run2", {"student_id": "s007", "topic": "対称な図形", "depth": "standard", "teacher_id": "t001",
                                "run_pre_test": False, "run_post_test": False}),
]


async def run_one(label: str, kwargs: dict):
    config = SessionConfig(**kwargs)
    result = await run_training_session(config)
    evaluation = result["evaluation"]

    summary = {
        "label": label,
        "session_id": result["session_id"],
        "student_id": evaluation.student_id,
        "teacher_id": evaluation.teacher_id,
        "topic": evaluation.topic,
        "depth": evaluation.depth,
        "proficiency_delta": evaluation.proficiency_delta,
        "avg_zpd_alignment": evaluation.avg_zpd_alignment,
        "avg_bloom_level": evaluation.avg_bloom_level,
        "avg_scaffolding_quality": evaluation.avg_scaffolding_quality,
        "avg_engagement": evaluation.avg_engagement,
        "frustration_events": evaluation.frustration_events,
        "aha_moments": evaluation.aha_moments,
        "hallucination_rate": evaluation.hallucination_rate,
        "direct_answer_rate": evaluation.direct_answer_rate,
        "teacher_compatibility_score": evaluation.teacher_compatibility_score,
        "session_grade": evaluation.session_grade,
        "skills_update_needed": evaluation.skills_update_needed,
        "report": result["report"],
    }
    out_path = OUT / f"{label}.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK  {label:24s}  delta={summary['proficiency_delta']:+.2f}  "
          f"zpd={summary['avg_zpd_alignment']:.3f}  scaffold={summary['avg_scaffolding_quality']:.3f}  "
          f"frustration={summary['frustration_events']}  grade={summary['session_grade']['grade']}  "
          f"saved={out_path.name}")
    return summary


async def main():
    print(f"Running {len(SESSIONS)} calibration sessions locally")
    results = []
    for label, kwargs in SESSIONS:
        try:
            r = await run_one(label, kwargs)
            results.append(r)
        except Exception as e:
            print(f"ERR {label}: {e}")
            import traceback; traceback.print_exc()

    if len(results) == 2:
        emma, yuki = results[0], results[1]
        print("\n=== Calibration comparison (same teacher t001, same topic, same depth) ===")
        rows = [
            ("proficiency_delta",       "+{:.2f}",     emma['proficiency_delta'], yuki['proficiency_delta']),
            ("avg_zpd_alignment",        "{:.3f}",     emma['avg_zpd_alignment'], yuki['avg_zpd_alignment']),
            ("avg_scaffolding",          "{:.3f}",     emma['avg_scaffolding_quality'], yuki['avg_scaffolding_quality']),
            ("avg_engagement",           "{:.3f}",     emma['avg_engagement'], yuki['avg_engagement']),
            ("frustration_events",       "{}",         emma['frustration_events'], yuki['frustration_events']),
            ("aha_moments",              "{}",         emma['aha_moments'], yuki['aha_moments']),
            ("direct_answer_rate",       "{:.3f}",     emma['direct_answer_rate'], yuki['direct_answer_rate']),
            ("teacher_compatibility",    "{:.3f}",     emma['teacher_compatibility_score'], yuki['teacher_compatibility_score']),
            ("session_grade",            "{}",         emma['session_grade']['grade'], yuki['session_grade']['grade']),
        ]
        print(f"  {'metric':25s}  {'s001 Emma (AI)':>16s}   {'s007 Yuki (human)':>16s}")
        for name, fmt, e, y in rows:
            print(f"  {name:25s}  {fmt.format(e):>16s}   {fmt.format(y):>16s}")
        print("\n  Real Yuki (live_583e8c28): mean response 9.3c, prof_after ~+1.9 over 12 turns")


if __name__ == "__main__":
    asyncio.run(main())
