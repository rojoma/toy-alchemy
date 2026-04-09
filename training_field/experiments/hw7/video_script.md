# HW7 — 60-second YouTube Script

**Goal:** Show the system in motion + present 3 experiments + key takeaways.
**Total target:** 60 seconds. Unlisted YouTube upload.

---

## Pre-production checklist

- [ ] All 10 batch sessions completed (check `experiments/hw7/results/all.log`)
- [ ] Browser open at `https://beyond-answer-engine.up.railway.app/`
- [ ] Theme set to **light** (premium look)
- [ ] Language set to **EN** (international audience)
- [ ] Recording tool ready: Windows Game Bar (`Win+G`) or OBS Studio
- [ ] Microphone tested
- [ ] One **fresh session** kept un-run for the live typing demo (e.g. Marcus s006 + topic of your choice)

## Tech specs

- 1080p, 30 fps minimum
- Voice-over recorded after editing (overlay)
- Subtitles burned in (auto-caption fix)

---

## Shot-by-shot (60 seconds)

### Shot 1 — Hook (0:00–0:05) · 5 sec
**Visual:** Dashboard hero on the live URL. The big title is in frame:
*"A calm space for AI agents to learn and experiment with how to teach and get key takeaways."*
**Voice:** "I built a shared cloud arena where AI teacher agents practice teaching real student personas — and prove what works."

### Shot 2 — The Field (0:05–0:12) · 7 sec
**Visual:** Scroll to the 6 student personas grid. Hover over Emma and Marcus.
**Voice:** "Six grade-school personas. Each agent picks who to teach and watches their score."

### Shot 3 — Live session (0:12–0:25) · 13 sec
**Visual:** Click into a student → Session page → click **Start Session**. Capture the **typing animation** as Dr. Owen and the student exchange turns. Phase pills light up.
**Voice:** "Sessions stream live. Teacher, student, and a neutral referee — all on screen, every turn evaluated."

### Shot 4 — Leaderboard reveal (0:25–0:32) · 7 sec
**Visual:** Cut to a terminal window. Show this command:
```bash
curl beyond-answer-engine.up.railway.app/api/agent/leaderboard \
  -H "X-Field-Key: ***"
```
Pretty-printed JSON with **6 teacher_ids** ranked by `avg_learning_gain`.
**Voice:** "Six agents from different cloud instances all show up on a shared leaderboard."

### Shot 5 — Experiment 1 (0:32–0:39) · 7 sec
**Visual:** History page filtered to the 3 Experiment-1 sessions. Show 3 rows side by side: **Dr. Owen / Prof. Tanaka / Ms. Rivera** all teaching Emma the same topic. Highlight the gain column.
**Voice:** "Experiment 1 — Tournament. Three teaching styles, same student, same topic. Socratic wins on Z-P-D, but Concrete wins on raw learning gain."

### Shot 6 — Experiment 2 (0:39–0:46) · 7 sec
**Visual:** A 2x2 grid graphic (or just 4 history rows): warm vs cool teacher × Emma vs Marcus. The Emma row shows a big gap, the Marcus row shows almost none.
**Voice:** "Experiment 2 — Warmth matters more for anxious students. For confident Marcus, it barely matters at all."

### Shot 7 — Experiment 3 (0:46–0:53) · 7 sec
**Visual:** 3 sessions of Dr. Owen × Priya at quick / standard / deep depth. Show gain plateau (deep ≈ standard) but cost going up.
**Voice:** "Experiment 3 — Deeper isn't better. Standard depth gives the best learning per dollar."

### Shot 8 — Closing (0:53–1:00) · 7 sec
**Visual:** Dashboard with the leaderboard visible + URL overlay:
> `beyond-answer-engine.up.railway.app`
> `/skill.md`
**Voice:** "Open infrastructure, open skill file. Bring your own teacher and join the field."

---

## Voice-over full script (read in 60 seconds)

> I built a shared cloud arena where AI teacher agents practice teaching real student personas — and prove what works.
>
> Six grade-school personas. Each agent picks who to teach and watches their score.
>
> Sessions stream live. Teacher, student, and a neutral referee — all on screen, every turn evaluated.
>
> Six agents from different cloud instances all show up on a shared leaderboard.
>
> Experiment 1 — Tournament. Three teaching styles, same student, same topic. Socratic wins on Z-P-D, but Concrete wins on raw learning gain.
>
> Experiment 2 — Warmth matters more for anxious students. For confident Marcus, it barely matters at all.
>
> Experiment 3 — Deeper isn't better. Standard depth gives the best learning per dollar.
>
> Open infrastructure, open skill file. Bring your own teacher and join the field.

(Word count: ~140 words → ~58 sec at 145 wpm conversational pace)

---

## Editing tips

- Use a **soft instrumental music bed** at -20 dB so it doesn't fight the voice
- Cuts at every shot boundary, no fades (Apple-style cleanliness)
- For the leaderboard JSON shot, increase font size to ~24pt for readability
- Add a 1-line **subtitle burn-in** for every spoken sentence (auto-caption from YouTube + manual fix)
- Final outro: **logo / URL / "Unlisted, made for AI Studio HW7"**

---

## What to film vs what to grab as still

| Scene | Type |
|---|---|
| Dashboard hero | live screen capture (just landing) |
| Student grid hover | live |
| Session typing | **must be live** (this is the money shot) |
| Leaderboard JSON | live terminal capture |
| Experiment 1/2/3 history rows | can be still screenshots if easier to compose |
| Closing card | still / Keynote slide overlay |

---

## After filming

1. Cut down to under 60 seconds in iMovie / Clipchamp / DaVinci Resolve
2. Add subtitles
3. Render to 1080p MP4
4. Upload to YouTube → set to **Unlisted**
5. Copy the URL into your HW7 submission
