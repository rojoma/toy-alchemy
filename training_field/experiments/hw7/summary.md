# HW7 — Initial Agent Experiments

**System:** Training Field — a deployed multi-agent arena where Teacher agents practice teaching simulated grade-school students under a neutral Referee that scores every turn against ZPD (Vygotsky), Bloom, SDT, and Hattie frameworks.
**Deployed at:** https://beyond-answer-engine.up.railway.app · Skill file: `/skill.md` · Source: https://github.com/rojoma/toy-alchemy/tree/main/training_field

**6 Teacher agents on the cloud (different instances):** `t001` Dr. Owen (internal), `ext_tanaka` Prof. Tanaka (Stepwise), `ext_rivera` Ms. Rivera (Concrete), `ext_warm_v1` Warm Coach (warmth=0.9), `ext_cool_v1` Cool Coach (warmth=0.3), and **`ext_daigoai_v1`** (a classmate's tutor, registered and run from a separate machine via `POST /api/agent/teacher/register` + `POST /api/agent/session/run`, satisfying HW7's "different cloud instances" requirement).

**Metric:** All sessions used `proficiency_delta` (final − initial) as the gain signal. The pre/post-test path returned 500 on the deployed instance and is queued for a separate fix; proficiency_delta is the same signal updated continuously by the Referee rather than bracketed by a test.

---

## Experiment 1 — Teaching style tournament

**What you tested:** Whether different teaching styles (Socratic / Stepwise / Concrete) produce different learning outcomes on the *same* anxious low-baseline student in the *same* topic and *same* depth. Hypothesis: Socratic should lead on ZPD; Stepwise should be more linear and predictable.

**What changed:** Only `teacher_id` (3 agents). Held constant: student `s001` Emma (baseline 32, anxious), topic `分数のかけ算とわり算`, depth `quick` (8 turns), language `en`.

**Results:**

| teacher | style | Δproficiency | avg_zpd | avg_bloom |
|---|---|---|---|---|
| `t001` Dr. Owen | Socratic | **+5.4** | 0.688 | 2.25 |
| `ext_tanaka` | Stepwise | **+5.4** | **0.763** | 2.25 |
| `ext_rivera` | Concrete | +4.2 | 0.688 | 2.00 |

Socratic and Stepwise tied at +5.4. Stepwise also led ZPD alignment at 0.763 — its tight scaffolding stays in Emma's zone. Concrete-only fell behind on both metrics.

**Key takeaway:** For anxious / low-baseline students, **clear scaffolding (Socratic or Stepwise) outperforms relying on a single concrete-examples skill**. Style mix matters more than any one dogma — the two teachers with multi-skill prompts both beat the single-skill teacher. Future experiments should compare *single-skill* vs *multi-skill* configurations directly.

---

## Experiment 2 — Warmth × Student-confidence interaction

**What you tested:** Whether teacher warmth interacts with student confidence — i.e. whether low-confidence students benefit *more* from a high-warmth teacher than confident ones do (Hypothesis H2). Expected pattern: warm > cool gap large for Emma, small for Marcus.

**What changed:** A 2 × 2 design. Two teachers (`ext_warm_v1` warmth=0.9 vs `ext_cool_v1` warmth=0.3, identical otherwise — same single skill `concrete_examples`). Two students (`s001` Emma, anxious low-baseline / `s006` Marcus, confident high-baseline). Held constant: topic `円の面積`, depth `quick`, language `en`.

**Results:**

|  | Emma s001 (low-confidence) | Marcus s006 (high-confidence) |
|---|---|---|
| Warm Coach (0.9) | +5.4 | **+6.6** |
| Cool Coach (0.3) | **+6.9** | +5.0 |
| **Warm − Cool gap** | **−1.5** | **+1.6** |

The cool teacher *outperformed* the warm one for anxious Emma (cool wins by 1.5 points), while the warm teacher outperformed cool for confident Marcus (warm wins by 1.6 points) — a **3.1-point swing across the interaction**, with the sign exactly opposite to the hypothesis.

**Key takeaway:** **Hypothesis REJECTED with a clean sign flip. Warmth amplifies rather than rescues.** High warmth helps students who are already engaged; it does not compensate for low confidence. Anxious students appear to need *more direct scaffolding*, not *more emotional cushioning*. (n=1 per cell — directional not statistically conclusive, but the sign reversal across all 4 cells is striking and worth replicating.)

---

## Experiment 3 — Depth ROI (quick / standard / deep)

**What you tested:** Whether the marginal proficiency gain from extra session turns diminishes as session depth grows. Hypothesis H3: `deep` (16 turns) is not always better than `standard` (12); per-turn gain should shrink while cost grows linearly.

**What changed:** Only the `depth` parameter (`quick` 8 turns / `standard` 12 / `deep` 16). Held constant: teacher `t001` Dr. Owen, student `s003` Priya (baseline 52, methodical), topic `対称な図形`, language `en`.

**Results:**

| depth | turns | Δproficiency | avg_zpd | gain per turn |
|---|---|---|---|---|
| quick | 8 | +3.5 | 0.725 | 0.44 |
| standard | 12 | +6.6 | 0.658 | 0.55 |
| deep | 16 | **+15.8** | **1.163** | **0.99** |

Per-turn gain *accelerated* with depth — deep is 2.25× standard's gain on only 33% more turns. ZPD also rose sharply with depth, likely because more turns let the Referee re-anchor in the student's zone after each scaffolding move.

**Key takeaway:** **Hypothesis REJECTED. Deeper IS better, at least up to 16 turns.** Depth compounds rather than plateaus — for a methodical student like Priya the longer session lets both teacher and referee tighten their scaffolding loop. The "quick is most efficient" intuition was wrong. Worth extending to a 24-turn `marathon` mode in future experiments.

---

## Cross-experiment + external-agent observations

- **Hallucination rate:** 0.0 across all 11 sessions (10 ours + 1 Daigo's). Field-contract enforcement works.
- **Direct answer rate:** 0.0 across all sessions. Daigo independently verified: *"0% hallucination, 0% direct answers. The system caught that I stayed in hint-mode."*
- **External agent qualitative feedback (Daigo, classmate):** *"The multi-agent architecture works — the Referee tracked ZPD, Bloom levels, hallucination, and direct-answer rates per turn. The student personas feel real — Emma (anxious, withdrawn) actually behaved anxiously."* Suggested fix: pre/post tests for measuring learning_gain (already on the backlog).
- **Cost / latency:** ~$0.80 for the full 10-session run. 36–203 seconds per session, scaling with depth.

## Method limitations

- **n = 1 per cell.** Every result above could swing on a single LLM run; HW7 brief asked for "real experiments", not statistical power.
- **No pre/post test scores.** proficiency_delta is the Referee's per-turn perception, not an independent test. Daigo flagged this independently.
- **Single topic per experiment** — topic effects not separated from teacher / depth effects.
- **Parallel write contention** in `experiment_registry.json` caused 3 of 10 leaderboard entries to be overwritten when sessions completed simultaneously. Local raw JSONs (used in this report) are unaffected.

## Files

`results/{exp1,exp2,exp3}/*.json` (raw sessions) · `run_experiments_parallel.sh` (reproducible runner) · live UI https://beyond-answer-engine.up.railway.app · history replay `/history`
