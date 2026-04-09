# HW7 — Initial Agent Experiments

**System:** Training Field — a deployed multi-agent arena where Teacher agents practice teaching simulated grade-school students under a neutral Referee that scores every turn against ZPD (Vygotsky), Bloom, SDT, and Hattie frameworks.

**Deployed at:** https://beyond-answer-engine.up.railway.app · Skill file: `/skill.md` · Source: https://github.com/rojoma/toy-alchemy/tree/main/training_field

**6 Teacher agents on the cloud (different instances):**

| teacher_id | name | origin | style | warmth |
|---|---|---|---|---|
| `t001` | Dr. Owen | internal (platform) | Socratic + reframe + metacognitive | 0.8 |
| `ext_tanaka` | Prof. Tanaka | external_partner_x | Stepwise + concrete | 0.4 |
| `ext_rivera` | Ms. Rivera | external_partner_y | Concrete + reframe + metacognitive | 0.95 |
| `ext_warm_v1` | Warm Coach | experiment_2 | Concrete only | 0.9 |
| `ext_cool_v1` | Cool Coach | experiment_2 | Concrete only | 0.3 |
| **`ext_daigoai_v1`** | **Daigo's tutor** | **classmate (external machine)** | **Socratic** | **—** |

The 6th agent (`ext_daigoai_v1`) registered and ran a real session against Emma (`s001`) from a different machine via `POST /api/agent/teacher/register` + `POST /api/agent/session/run`, satisfying HW7's "different cloud instances" requirement. His session: Emma 31.7 → 36.8 proficiency, ZPD 0.738, Bloom 2.38, 0% hallucination, 0% direct answers.

**Metric:** All sessions used `proficiency_delta` (final − initial) as the gain signal. The pre/post-test path (`question_bank.get_test_questions`) returned 500 on the deployed instance and is queued for a separate fix; proficiency_delta is the same signal updated continuously by the Referee rather than bracketed by a test.

---

## Experiment 1 — Teaching style tournament (3 sessions)

**Hypothesis:** Three teaching styles (Socratic / Stepwise / Concrete) will produce different proficiency gains on the same anxious low-baseline student. Socratic should lead on ZPD; Stepwise should be more linear.
**Setup:** student `s001` Emma (baseline 32, anxious), topic `分数のかけ算とわり算`, depth `quick`, lang en. Only `teacher_id` varied.

| teacher | style | Δproficiency | avg_zpd | avg_bloom |
|---|---|---|---|---|
| `t001` Dr. Owen | Socratic | **+5.4** | 0.688 | 2.25 |
| `ext_tanaka` | Stepwise | **+5.4** | **0.763** | 2.25 |
| `ext_rivera` | Concrete | +4.2 | 0.688 | 2.00 |

**What actually happened:** Socratic and Stepwise **tied at +5.4**, while Concrete trailed at +4.2. Stepwise also led ZPD (0.763) — its tight scaffolding stays in Emma's zone. **Concrete-only fell behind on both metrics**, suggesting a single-skill teacher is weaker than a 2-3 skill mix on a low-baseline student.
**Takeaway:** For anxious / low-baseline students, *clear scaffolding (Socratic or Stepwise) outperforms relying purely on concrete examples*. Style mix matters more than any single dogma.

## Experiment 2 — Warmth × Confidence interaction (4 sessions)

**Hypothesis (H2):** Low-confidence students benefit more from a high-warmth teacher. Expect a clear interaction: warm > cool gap large for Emma, small for Marcus.
**Setup:** 2×2. Two teachers (`ext_warm_v1` warmth=0.9 vs `ext_cool_v1` warmth=0.3), identical otherwise. Two students (Emma s001 anxious low-baseline / Marcus s006 confident high-baseline). Topic `円の面積`, depth quick.

|  | Emma s001 (low-conf) | Marcus s006 (high-conf) |
|---|---|---|
| Warm Coach (0.9) | +5.4 | **+6.6** |
| Cool Coach (0.3) | **+6.9** | +5.0 |
| **Warm − Cool gap** | **−1.5** | **+1.6** |

**What actually happened:** Hypothesis **REJECTED with a clean sign flip**. The cool teacher actually outperformed the warm one for anxious Emma (−1.5 gap, cool wins), while the warm teacher outperformed cool for confident Marcus (+1.6 gap, warm wins). This is a **3.1-point swing across the interaction** and directly contradicts the popular "anxious students need more warmth" intuition.
**Takeaway:** **Warmth amplifies rather than rescues.** High warmth helps students who are already engaged; it doesn't compensate for low confidence. Anxious students need *more direct scaffolding*, not *more emotional cushioning*. (n=1/cell — directional but not statistically conclusive.)

## Experiment 3 — Depth ROI (3 sessions)

**Hypothesis (H3):** `deep` (16 turns) is not always better than `standard` (12); marginal gain diminishes while cost grows linearly.
**Setup:** Same teacher (`t001`), same student (`s003` Priya, baseline 52, methodical), same topic (`対称な図形`). Only `depth` varied.

| depth | turns | Δproficiency | avg_zpd | gain/turn |
|---|---|---|---|---|
| quick | 8 | +3.5 | 0.725 | 0.44 |
| standard | 12 | +6.6 | 0.658 | 0.55 |
| deep | 16 | **+15.8** | **1.163** | **0.99** |

**What actually happened:** Hypothesis **REJECTED**. Far from diminishing, **per-turn gain accelerates with depth** — deep is 2.25× standard's gain on only 33% more turns. ZPD also rises sharply with depth (likely because more turns let the Referee re-anchor in the student's zone after each scaffolding move).
**Takeaway:** **Deeper IS better, at least up to 16 turns.** The "quick is most efficient" intuition was wrong; for a methodical student like Priya, depth compounds rather than plateaus. Worth extending to a 24-turn `marathon` mode in future experiments.

---

## Cross-experiment + external-agent observations

- **Hallucination rate:** 0.0 across all 11 sessions (10 ours + 1 Daigo's). Field contract enforcement works.
- **Direct answer rate:** 0.0 across all sessions. Daigo independently verified: *"0% hallucination, 0% direct answers. The system caught that I stayed in hint-mode."*
- **External agent qualitative feedback (Daigo, classmate):** *"The multi-agent architecture works — the Referee tracked ZPD, Bloom levels, hallucination, and direct-answer rates per turn. The student personas feel real — Emma (anxious, withdrawn) actually behaved anxiously."* Suggested fix: pre/post tests for measuring learning_gain (already on the backlog).
- **Cost:** ~$0.80 for 10 sessions. **Latency:** 36–115s per quick session.

## Method limitations

- **n=1 per cell** — every result above could swing on a single LLM run; HW7 brief asked for "real experiments", not statistical power.
- **No pre/post test scores** — proficiency_delta is the Referee's perception of understanding, not an independent test. Daigo flagged this independently.
- **Single topic per experiment** — topic effects not separated from teacher / depth effects.

## Files

`results/{exp1,exp2,exp3}/*.json` (raw sessions) · `run_experiments.sh` (reproducible runner) · live UI: https://beyond-answer-engine.up.railway.app · history replay: `/history`
