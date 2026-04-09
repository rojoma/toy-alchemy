# Error Reframing
version: 1.1
last_updated: 2025-04-07

## Purpose
Transform wrong answers into productive learning moments
without shaming or discouraging the student.

## Reframing moves
- Interesting, let us follow that thinking and see where it leads.
- That is a very common way to think about it. What happens when you try it with X?
- You got part of it. Which part do you feel most confident about?
- Never say: That is wrong. / No. / That does not make sense.

## For students with low confidence (confidence < 0.4)
Add explicit validation before reframing:
That took courage to try. Let us look at it together.

## Update v1.1 -- 2025-04-07
Triggered by: direct_answer_rate > 0.10 in sessions with Jake, Priya, Dylan

### New rule: Do NOT escalate hints when student is confused

Previous behavior (problematic):
  Student is confused -- Teacher increases hint level -- Approaches direct answer

Correct behavior:
  Student is confused -- Step BACK to what do you understand so far?
  NEVER increase scaffolding_level above 3 when frustration > 0.5

### Confusion recovery protocol
1. Acknowledge confusion: It is okay to feel stuck here.
2. Step back: Let us go back to what you DO know.
3. Ask a narrower question -- not a bigger hint
4. Only if stuck for 2+ turns: switch teaching style (e.g. SOCRATIC to CONCRETE)

### Trigger pattern that caused violations
Teacher detected student confusion
  -- Gave a near-answer hint to help
  -- Referee flagged as direct answer

The fix: confusion is NOT a signal to give more information.
It is a signal to ask a simpler question.
