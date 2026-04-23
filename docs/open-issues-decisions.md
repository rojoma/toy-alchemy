# Open issues — decisions pending

As of 2026-04-23, all implementation-track issues (#20, #21, #28, #29, #33, #34, #35, #8, #9) have been closed. The 5 issues below are open because each needs a human judgment call before engineering can move — legal, strategic, UX, or an outside-data dependency.

This memo lays out, per issue, **what question needs answering**, **who is the natural decision-maker**, and **the minimum decision needed to unblock the next step**. Work can proceed on any of them independently.

---

## #7 — Terms of Service & Privacy Policy (`legal`)

### The question
What legal framework does Toy Alchemy operate under, and what consents do we collect before a minor uses the service?

### Why this blocks engineering
We already collect per-student profile data (name, grade, subject, proficiency history, session transcripts, now end-of-session feedback from #29 and planned photo uploads in #32). Without a posted ToS + privacy policy, we cannot legally invite unknown families to the live app (#31 depends on this).

### Concrete open questions
1. **Target jurisdictions**
   - Japan only (個人情報保護法 + 子どもの個人情報ガイドライン)
   - US too (COPPA applies under 13)
   - Both?
2. **Data categories actually collected today** (we should list these verbatim in the policy):
   - Name (free text; could be nickname)
   - Grade / subject
   - Session transcripts (student inputs, which can include personal context if they mention it)
   - Proficiency scores (per topic)
   - Referee evaluations (hallucination flags, ZPD scores)
   - Turn-level feedback (from #13) and session-level feedback (from #29)
   - OpenAI API calls send the above to a third party (model provider) — must be disclosed
   - Railway is the hosting provider — also a data processor
3. **Consent model**
   - Parent pre-registers the student? Just-in-time banner on first visit? Nothing until we go public?
4. **Retention**
   - How long do we keep session logs? Can a family request deletion? Who handles that request?
5. **Document hosting**
   - Static pages under `/terms` and `/privacy` in the FastAPI app, or external (Notion page, etc.)?

### Smallest decision that unblocks the next step
**Pick target jurisdiction (Japan-only is simplest).** Once that's picked, engineering can scaffold the static `/terms` and `/privacy` pages with placeholder text, and a lawyer or teacher-sensei can fill in the clauses. The infrastructure doesn't need the final wording to be built.

### Decision owner
- Sho (project lead) + anyone on the team with legal contacts
- Do NOT draft the legal text yourself via LLM without human review

### Related
- #31 (landing page) — launch blocker
- #32 (photo upload) — adds image-data disclosure
- #30 (parent controls) — touches consent scope

---

## #10 — Teacher Picker Guide (`[Teacher]`)

### The question
How do we help a student (or parent) choose between Warm Coach, Prof. Tanaka, Ms. Rivera, and Cool Mentor when they all look like "teacher options" in a flat dropdown?

### Why this blocks engineering
The implementation is straightforward (sample-dialog previews, warmth/patience badges, a recommender). But the **content** that goes into those previews — what Dr. Owen actually sounds like in a hard moment, what Warm Coach does when a student is frustrated — is the part that makes the guide useful or just-more-noise. That's an authoring job, not a code job.

### Concrete open questions
1. **Sample dialogues — where do they come from?**
   - Hand-write them per teacher
   - Sample real transcripts from existing sessions (requires per-student consent)
   - Have each teacher agent self-describe via a prompt
2. **Recommender logic**
   - Based on student proficiency (already have)? Emotional state? Past sessions?
   - Or purely a matching quiz ("I like when the teacher …") mapping to teacher params?
3. **Teacher parameter visualization**
   - Raw numbers (warmth: 0.8)
   - Qualitative badges ("patient", "formal", "challenges you")
   - Comparison grid vs radar chart

### What we have that can help
- **#29 end-of-session feedback** now records tags like `clarity`, `pace`, `difficulty`, `tone`, `patience` per teacher. Once real sessions accumulate, we can derive "students who liked X tag tend to pick teacher Y" from data rather than guessing.
- **#14 Teacher Memory viz** (PR #19) already shows what the teacher has noticed about a student — useful material for the preview.

### Smallest decision that unblocks the next step
**Wait for 10-20 end-of-session feedback entries** before investing in #10. Otherwise any recommender we build is a guess, and any preview we write is marketing copy. Recheck this issue after a week of live use.

### Decision owner
- Sho (product)
- Optionally: Daigo / Mach for authoring sample previews

### Related
- #29 (data source)
- #30 (parents as a potential decision-maker for teacher choice)

---

## #30 — Parent Controls (`[Discussion]`)

### The question
Should parents be able to adjust teacher parameters (warmth, patience, difficulty, topics) based on their child's experience?

### Why this is still open
This is explicitly a **discussion issue**, not an implementation one. The team needs to decide whether the feature should exist at all before any engineering happens.

### The four tensions
1. **Who owns the teacher**
   - Student-owned: the student picks, adjusts as they learn their own preferences.
   - Parent-owned: parent sets up the teacher once, student consumes.
   - AI-owned: Teacher Memory + end-of-session feedback auto-adjust (#14 + #29 already collect the signal).
2. **Does parental visibility chill student feedback?**
   - If the student knows their #29 ratings are shown to the parent, will they still say "this teacher didn't help me"?
   - Possible mitigation: aggregate only (show parent "the student rated 4/5 this week" but not specific notes).
3. **What's actually tunable**
   - `warmth`, `patience_threshold`, `pacing_speed` — safe to expose
   - `metacognitive_prompting`, `selected_skills` — pedagogically consequential, probably not parent-facing
   - `motivation_style` — sensitive, changes tone significantly
4. **Vs simpler alternatives**
   - Parent can already switch teachers manually from `/learn`. Is a "swap" action enough? Do we actually need continuous tuning?

### Data that would make this concrete
Once #29 has produced a few weeks of feedback, we can answer empirically:
- Do parents *want* this? (ask them)
- Do students notice when the teacher changes? (session transcripts)
- Does the AI self-adjustment via Teacher Memory already produce good results?

### Smallest decision that unblocks the next step
**Defer. Revisit after 1 month of live use.** In the meantime, make sure #29 captures enough signal to inform this later. If the question comes up urgently (parent requests it), start with the cheapest version: a "swap teacher mid-semester" UI, not continuous tuning.

### Decision owner
- Team discussion on this issue thread
- Strong input from: anyone with kids in the target age, Daigo (education background)

### Related
- #29 (feedback data)
- #14 (Teacher Memory)
- #10 (teacher picker)

---

## #31 — Landing Page (`[Feature]`)

### The question
When a stranger hits https://beyond-answer-engine.up.railway.app, what do they see, and what one thing do we want them to do next?

### Why this blocks engineering
A landing page is about positioning and copy, not code. The team needs to agree on:

### Concrete open questions
1. **Primary audience in rank order**
   - Parent of a 小6 student
   - The student themselves
   - Educators / tutors looking for tools
   - Researchers / MIT evaluators
   - Each needs a different headline.
2. **Call to action**
   - "Try a session" (guest mode — needs #7 first)
   - "Sign up for a demo"
   - "See it in action" (demo video only, no interaction)
3. **Value proposition — pick one, not all**
   - "AI tutor that adapts to your child"
   - "See how your child is learning, in real time"
   - "MIT research on how AIs teach"
4. **Visual / demo assets**
   - Screenshot? Screen recording? Side-by-side teacher comparison?
   - Who produces these?
5. **Languages**
   - Japanese primary, English secondary? Both at launch?

### Technical prereqs
- #7 (ToS + privacy) must be live before a public CTA
- The LP itself is a template change only — small once the content is decided

### Smallest decision that unblocks the next step
**Pick primary audience (1 line) + 1 CTA.** With those two alone, engineering can stub out the landing page and iterate on copy.

### Decision owner
- Sho + marketing-minded teammate
- The README rewrite (PR #19's docs update) is a good template for the tone — re-use.

### Related
- #7 (prerequisite)
- Recent README rewrite shows our current positioning experiments

---

## #32 — Homework Photo Upload (`[Feature]`)

### The question
Do we build image upload + OCR / multimodal interpretation, and if so how do we handle the resulting cost, privacy, and failure-mode surface?

### Why this blocks engineering
Three things need to be decided before code:

### Concrete open questions
1. **Model choice**
   - OpenAI GPT-4o (already in use) — vision built in, ~$0.01/image, no new vendor.
   - Google Gemini — cheaper for images, but new vendor integration.
   - Azure OCR + then LLM interpretation — cheapest for volume, two-step pipeline.
2. **Privacy / storage**
   - Keep uploaded images? (future training data, but heavy liability.)
   - Send directly to OpenAI and discard after inference? (simpler, aligns with #7.)
   - Show re-upload prompts if OCR fails — don't silently retain.
3. **Cost control**
   - Per-student daily cap? Per-session cap? Freemium?
   - At ~$0.01 per image, 1000 students × 5 photos/day = ~$150/month. Is that OK or does it need a meter?
4. **UX failure modes**
   - OCR returns "I can't read this" — fall back to scope text (#28 is already wired)
   - OCR returns something subtly wrong (misread "3/4" as "34") — does the teacher catch this? Is there a "confirm what I see" step?
5. **Scope of first version**
   - Just problem text extraction (minimum)
   - Full interpretation + topic classification
   - Also work in-session (student uploads mid-conversation)?

### What's already done that helps
- **#28 delivered the `scope` parameter** all the way through `/api/live/start` and into the teacher's greeting. The upload feature can pipe OCR text → scope and reuse the whole existing flow. Huge cost savings on this integration.

### Smallest decision that unblocks the next step
**Decide model choice + privacy stance (retain vs discard) before writing any code.** Everything else can be iterated.

### Decision owner
- Sho (cost & privacy)
- Daigo (UX of whether students actually want this)

### Related
- #28 (scope input — the landing spot for OCR output)
- #7 (privacy policy must cover images)
- #32's scope is narrow enough that a minimum version — upload + send to GPT-4o vision + use extracted text as scope — is maybe 1-2 days of work **once** the decisions are made.

---

## Cross-cutting observations

- **#7 is the single biggest blocker for public launch.** #31 and #32 both wait on it. #30 partially waits on it too.
- **#10 and #30 both want data that #29 is about to produce.** Wait 2-4 weeks before spending time on either.
- **Nothing open blocks further feature work** — if the team wants to keep building, new issues on things like lesson streaks, celebrations after N-day streak, parent dashboard, etc. are all doable in parallel with these decisions.

## Decision checklist

If you want to unblock all five in one sitting:

- [ ] Pick ToS/Privacy target jurisdiction (#7)
- [ ] Pick LP primary audience + CTA (#31)
- [ ] Pick photo upload model + retention policy (#32)
- [ ] Defer #10 and #30 with a calendar reminder for 4 weeks out
