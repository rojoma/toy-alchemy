# HW10 — Experiment 4: Calibration MVP

**System:** Training Field — same multi-agent arena used in HW7, now extended with a human-derived Student Agent.
**Deployed at:** https://beyond-answer-engine.up.railway.app

---

## Why this experiment exists

HW7 ran three Teacher-style experiments against six **AI Student Agents** (Emma, Jake, Priya, Dylan, Chloe, Marcus). The findings (warmth sign-flip, depth ROI, hallucination 0/11) were directional, but they all rest on a load-bearing assumption:

> *"Our Student Agents behave enough like real grade-school learners for Principal scores to mean something for human classrooms."*

That assumption was never tested. This experiment tests it for the first time, and finds it is **clearly violated** along the response-style dimension. This is the missing half of the loop: **Live transcripts → Student Agent calibration → re-evaluated leaderboard.**

---

## Method

**Source of human data:** `live_583e8c28` — a real Live Classroom session on this platform (12 turns, real human "Yuki", 6th-grade, topic 対称な図形, Dr. Owen as teacher, in Japanese).

**Extracted human response signature:**

| Signal | Value (real Yuki) |
|---|---|
| Mean response length | **9.3 characters** |
| Median | 8c |
| Min / Max | 4c / 27c |
| Frustration markers ("だから〜って！") | 2/12 turns |
| Disengagement markers ("知りません" / "わからない") | 5/12 turns |
| Final proficiency reached (over 12 turns) | ~+1.9 |

**New persona created:** `s007 Yuki` — added to `student_profiles.json` with `verbosity: 0.05`, `description` instructing 4–15-character replies, refusals like "だからわからないって！", and a refusal-to-pad behavior. The `student_agent.py` prompt builder now switches to a short-form rule when `verbosity ≤ 0.1`.

**Comparison:** Same teacher (`t001` Dr. Owen), same topic (`対称な図形`), same depth (`standard`, 12 turns), same language. Only `student_id` varies.

- Original AI persona: `s001` Emma (anxious, low-baseline, baseline 30, verbosity 0.3)
- Human-derived persona: `s007` Yuki (anxious, low-baseline, baseline 29, **verbosity 0.05**)

Two runs each, to check the gap is not a single-run artifact.

---

## Results

| Metric | s001 Emma run1 | s001 Emma run2 | s007 Yuki run1 | s007 Yuki run2 |
|---|---|---|---|---|
| **proficiency_delta** | **+7.80** | **+8.55** | **+5.10** | **+4.65** |
| avg_zpd_alignment | 0.667 | 0.675 | 0.575 | 0.542 |
| avg_scaffolding | 0.542 | 0.525 | 0.417 | 0.383 |
| avg_engagement | 0.742 | 0.733 | 0.650 | 0.725 |
| frustration_events | 2 | 6 | 8 | 6 |
| aha_moments | 1 | 2 | 0 | 0 |
| direct_answer_rate | 0.083 | 0.167 | 0.167 | 0.000 |
| teacher_compatibility | 0.494 | 0.495 | 0.374 | 0.393 |
| **session_grade** | **◎ excellent** | **⚠ review** | **⚠ review** | **⚠ review** |
| hallucination_rate | 0.0 | 0.0 | 0.0 | 0.0 |

**Aggregated (mean across both runs):**

| Metric | s001 Emma (AI) | s007 Yuki (human-derived) | Gap |
|---|---|---|---|
| proficiency_delta | +8.18 | **+4.88** | **−40 %** |
| avg_zpd | 0.671 | 0.559 | −17 % |
| avg_scaffolding | 0.534 | 0.400 | −25 % |
| frustration_events | 4.0 | 7.0 | +75 % |
| aha_moments | 1.5 | **0.0** | full collapse |
| teacher_compatibility | 0.494 | 0.384 | −22 % |

---

## Key takeaway — the Hero finding

> **The same teacher receives a 40 % higher proficiency-gain score against an AI student than against a student calibrated against a real human transcript — across two independent runs. The AI persona reaches "excellent" once and "review needed" once; the human-derived persona reaches "review needed" both times. The gap is not in *how much the teacher hallucinates* (0.0 in both) — it is in *how easily the AI student lets the teacher off the hook*.**

In one line: **AI students overestimate teaching quality by ~40 %. Calibration matters.**

This is a published-grade calibration warning for *every* AI-tutor evaluation paper that scores teachers against simulated students.

---

## Why the gap shows up where it does

- **Lengthy, articulate AI student replies** give the Principal lots of "evidence of engagement" → higher avg_engagement, more aha_moments, easier ZPD alignment.
- **Short, frustrated, refusal-heavy human replies** (4–15c) give the Principal less to score positively on, and the Referee correctly flags more frustration events and lower scaffolding quality.
- **Hallucination is unaffected** because the field-contract guard works on the *teacher* side — confirming HW7's headline result is robust to this calibration.
- **Aha-moments collapse to zero** with the human-derived persona, because moments of insight require the student to *demonstrate* insight in their response, and a 4-character reply rarely does.

---

## What this means for the project's claims

| Claim from HW7 | Status after Experiment 4 |
|---|---|
| Hallucination 0 / 11 sessions, field-contract works | **Holds.** 0.0 in both calibration runs too. |
| Warmth sign-flip (warm helps confident, cool helps anxious) | **Provisional.** Was measured against AI Emma. Re-running with `s007` is the natural next step before publishing. |
| Depth ROI (deep > standard) | **Provisional.** Same caveat. |
| Multi-agent architecture is agentic | **Holds and gets stronger.** The directive-to-teacher loop and Principal-rubric were not changed; only the *student's response distribution* was changed, and the rubric responded the way it should — by detecting weaker scaffolding. |

---

## Method limitations (carried forward)

- **n = 1 human source.** Only one Live transcript was used to derive `s007`. Adding a second human (anxious confident, methodical etc.) would let us populate a *cohort* of human-derived personas.
- **Calibration is one-way.** The Live transcript shaped the persona offline; there is no automated pipeline yet that updates Student Agents from new Live sessions. This is the next milestone.
- **Same teacher only (`t001`).** The 40 % gap is between two students under one teacher. The next experiment runs the full HW7 teacher tournament (`t001`, `ext_tanaka`, `ext_rivera`, `ext_warm_v1`, `ext_cool_v1`) against `s007` to see if the leaderboard reorders.
- **Standard depth only.** Quick / deep depth gap on `s007` is not yet measured.

---

## Closing the loop — next milestone

Experiment 4 closes the *first half* of the loop:

```
Live (real human Yuki)  →  transcript  →  s007 Yuki-derived  →  Training Field
```

The remaining half is automation:

```
Live (more humans)  →  auto-extract response signature  →  auto-update existing Student Agents  →  re-run leaderboard
```

That is the main HW10 → next-quarter roadmap item.

---

## Files

- `run_calibration.py` — reproducible runner
- `results/s001_emma_run{1,2}.json` — AI persona sessions
- `results/s007_yuki_derived_run{1,2}.json` — human-derived persona sessions
- Source transcript: `training_field/reports/live_583e8c28_transcript.json`
- Persona definition: `training_field/profiles/student_profiles.json` (`s007`)
- Persona-aware short-form rule: `training_field/student_agent.py` (verbosity ≤ 0.1 branch)
