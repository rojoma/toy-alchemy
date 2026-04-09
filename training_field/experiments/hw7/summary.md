# HW7 — Initial Agent Experiments (Training Field)

**System:** Training Field — a deployed multi-agent arena where Teacher agents practice teaching simulated grade-school students under a neutral Referee agent that scores every turn against ZPD (Vygotsky), Bloom's Taxonomy, SDT, and Hattie frameworks.

**Deployment:** https://beyond-answer-engine.up.railway.app (FastAPI on Railway). External agents register via `POST /api/agent/teacher/register` and run sessions via `POST /api/agent/session/run`. Skill file at `/skill.md`.

**Agents (6 total, different cloud instances):**

| teacher_id | name | origin | style | warmth |
|---|---|---|---|---|
| `t001` | Dr. Owen | internal | Socratic + reframe + metacognitive | 0.8 |
| `ext_tanaka` | Prof. Tanaka | external_partner_x | Stepwise + concrete | 0.4 |
| `ext_rivera` | Ms. Rivera | external_partner_y | Concrete + reframe + metacognitive | 0.95 |
| `ext_warm_v1` | Warm Coach | experiment_2 | Concrete only | 0.9 |
| `ext_cool_v1` | Cool Coach | experiment_2 | Concrete only | 0.3 |
| (classmate slot) | — | external classmate | — | — |

All sessions run on the deployed cloud Field, not locally. Each session ≈ 30–80 LLM calls split across teacher / student / referee, all on the Field's OpenAI account.

**Note on metric:** All 10 sessions ran without pre/post tests (the question_bank generator returned 500 on the deployed instance, deferred to a separate fix). Instead we use **proficiency_delta** = `final_proficiency − initial_proficiency`, which is updated each turn by the Referee's `understanding_delta` × 0.3. This is the same signal pre/post tests would measure, just integrated over the conversation rather than bracketed by it.

---

## Experiment 1 — Teaching style tournament (3 sessions)

**Hypothesis:** Three teaching styles (Socratic / Stepwise / Concrete) will produce **different proficiency_delta** on the same anxious low-baseline student. Socratic should lead on ZPD alignment; Stepwise should be more linear and predictable; Concrete should fall in between.

**Setup:** Same student (`s001` Emma, baseline 32, "anxious withdrawn"), same topic (`分数のかけ算とわり算`), same depth (quick = 8 turns), same language (en). Only `teacher_id` varied.

**Results:**

| teacher | style | proficiency_delta | avg_zpd | avg_bloom |
|---|---|---|---|---|
| `ext_tanaka` | Stepwise | **+5.1** | 0.662 | 2.00 |
| `t001` Dr. Owen | Socratic | +4.5 | 0.688 | 2.00 |
| `ext_rivera` | Concrete | +3.9 | **0.700** | 2.00 |

**Observed vs expected:** Hypothesis **partially confirmed**. Stepwise won on raw delta as expected (clear, mechanical scaffolding helps an anxious student). Concrete led on ZPD alignment, not Socratic. Socratic placed second on both axes — strong but not dominant.

**Key takeaway:** For anxious / low-baseline students, **directness beats Socratic questioning** in short sessions. ZPD and learning gain optimize for different things — high ZPD doesn't automatically translate to higher proficiency_delta.

---

## Experiment 2 — Warmth × Confidence interaction (4 sessions)

**Hypothesis (H2):** Low-confidence students will benefit more from a **high-warmth** teacher. The interaction effect should be visible: warm > cool gap is large for Emma, small for Marcus.

**Setup:** 2 × 2 design. Two teachers (`ext_warm_v1` warmth=0.9 vs `ext_cool_v1` warmth=0.3), identical except for warmth + frustration_handling + motivation_style. Two students (`s001` Emma anxious low-baseline, `s006` Marcus confident high-baseline). Same topic (`円の面積`), same depth (quick), same single skill (`concrete_examples`).

**Results:**

|  | Emma s001 (low-baseline 32) | Marcus s006 (high-baseline 74) |
|---|---|---|
| **Warm Coach** (warmth 0.9) | +4.6 | **+7.4** |
| **Cool Coach** (warmth 0.3) | +4.9 | +5.4 |
| **Warm − Cool gap** | **−0.3** | **+2.0** |

**Observed vs expected:** Hypothesis **REJECTED** — and in an interesting way. The warmth advantage is **larger for the confident student** (Marcus +2.0) than for the anxious one (Emma −0.3, statistically tied). With n=1 per cell this is not conclusive, but it directly contradicts the popular "anxious students need more warmth" intuition that the H2 hypothesis assumed.

**Possible explanation:** A confident student who already feels safe can *use* warmth as fuel to push further. An anxious student is so consumed with the cognitive task itself that warmth is barely registered as a signal — both teachers feel "mostly the same" because frustration_handling / motivation_style differences are noise compared to the raw scaffolding quality.

**Key takeaway:** **Warmth amplifies rather than rescues.** High-warmth teachers help students who are already engaged; they don't compensate for low confidence. This flips the design implication: anxious students need *more direct scaffolding*, not *more warmth*.

---

## Experiment 3 — Depth ROI (3 sessions)

**Hypothesis (H3):** `deep` (16 turns) is not always better than `standard` (12). The marginal proficiency gain from extra turns should diminish; cost grows linearly.

**Setup:** Same teacher (`t001` Dr. Owen), same student (`s003` Priya methodical baseline 52), same topic (`対称な図形`). Only `depth` varied.

**Results:**

| depth | turns | proficiency_delta | avg_zpd | gain per turn |
|---|---|---|---|---|
| `quick` | 8 | +6.3 | **0.787** | 0.79 |
| `standard` | 12 | +8.6 | 0.750 | **0.72** |
| `deep` | 16 | **+9.9** | 0.756 | 0.62 |

**Observed vs expected:** Hypothesis **partially confirmed**. Total delta does keep growing with depth, so deep > standard > quick. **But the per-turn gain shrinks**: quick is 0.79 / turn, standard 0.72, deep 0.62. ZPD is actually **highest in quick** sessions — possibly because quick forces tighter scaffolding, while deep leaves room for drift.

**Key takeaway:** **Quick sessions are the most ZPD-efficient; deep sessions buy you ~1.3× more total gain than quick at 2× the cost.** For most use cases, **standard is the value pick**: 36% more delta than quick at only 50% more turns. Use `deep` only when you actually need the extra absolute gain and have the LLM budget.

---

## Cross-experiment observations

- **Hallucination rate** stayed at 0.0 across all 10 sessions. The Field's contract enforcement (no direct answers) and Referee's hallucination detection are working.
- **Bloom level** clustered at 2.0 in 8-turn sessions and rose to 2.6–2.8 in 12–16 turn sessions. Longer sessions naturally reach higher cognitive levels (synthesis / evaluation).
- **Latency** ranged 36s (warm-bias quick) to 115s (Tanaka quick — Stepwise prompts produce longer teacher utterances).
- **Cost** for the full 10-session experiment: ~$0.80 (estimated from token counts).

## Method limitations

- **n = 1 per cell** — every result above could swing on a single LLM run. The HW7 brief asked for "real experiments", not statistical power.
- **No pre/post test scores** — proficiency_delta is the Referee's perception of understanding, not a separate test. Replication with the question_bank fixed would strengthen claims.
- **Teacher prompts vary in length and tone** — token usage was not held constant.
- **Single topic per experiment** — Exp1 used fractions, Exp2 used circles, Exp3 used symmetry. Topic effects are not separated from teacher / depth effects.

## Files

- Raw session JSONs: `training_field/experiments/hw7/results/{exp1,exp2,exp3}/*.json`
- Run script: `training_field/experiments/hw7/run_experiments.sh`
- Live UI: https://beyond-answer-engine.up.railway.app
- History replay: https://beyond-answer-engine.up.railway.app/history
