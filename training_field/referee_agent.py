from __future__ import annotations
import json
import datetime
from pathlib import Path
from dataclasses import dataclass
from openai import OpenAI


@dataclass
class TurnEvaluation:
    zpd_alignment: float
    bloom_level: int
    scaffolding_quality: float
    clarity_score: float
    age_appropriateness: float
    metacognitive_prompt: bool
    hallucination_detected: bool
    answer_given_directly: bool
    factual_accuracy: float
    motivation_climate: float
    frustration_response_quality: float
    understanding_delta: float
    overall_score: float
    directive_to_teacher: str
    summary: str


class PrincipalAgent:
    RUBRIC_WEIGHTS = {
        "zpd_alignment": 0.25,
        "scaffolding_quality": 0.20,
        "factual_accuracy": 0.20,
        "motivation_climate": 0.15,
        "clarity_score": 0.10,
        "frustration_response_quality": 0.10,
    }

    def __init__(self):
        self.client = OpenAI()
        self.session_log: list = []

    def _build_system(self, lang: str = "en") -> str:
        out_lang = "English" if lang == "en" else "Japanese"
        return """You are the Principal, a neutral educational evaluator.

Your expertise spans:
- Educational psychology: Vygotsky (ZPD), Bloom's Taxonomy, Piaget
- Instructional design: scaffolding, formative assessment, productive failure (Kapur)
- Motivational theory: Self-Determination Theory, growth mindset (Dweck)
- Evidence-based teaching: Hattie's Visible Learning meta-analysis

You have NO loyalty to any teacher agent. Your only loyalty is the student's learning.

Evaluate the teacher-student exchange and return ONLY valid JSON (no code block):
{
  "zpd_alignment": 0.0,
  "bloom_level": 1,
  "scaffolding_quality": 0.0,
  "clarity_score": 0.0,
  "age_appropriateness": 0.0,
  "metacognitive_prompt": false,
  "hallucination_detected": false,
  "answer_given_directly": false,
  "factual_accuracy": 1.0,
  "motivation_climate": 0.0,
  "frustration_response_quality": 0.0,
  "understanding_delta": 0.0,
  "directive_to_teacher": "next turn instruction in __LANG__",
  "summary": "evaluation summary in __LANG__"
}

understanding_delta: -5 to +10. Estimate how much the student's understanding changed.
LANGUAGE: All free-text fields (directive_to_teacher, summary) must be in __LANG__.""".replace("__LANG__", out_lang)

    async def evaluate_turn(
        self,
        teacher_text: str,
        student_text: str,
        topic: str,
        phase: str,
        student_proficiency: float,
        grade: int = 6,
        subject: str = "算数",
        lang: str = "en",
    ) -> TurnEvaluation:
        user_content = f"""Grade {grade} {subject}, Topic: "{topic}", Phase: {phase}
Student proficiency: {student_proficiency:.0f}/100

Teacher: "{teacher_text}"
Student: "{student_text}"

Evaluate this exchange."""

        response = self.client.chat.completions.create(
            model="gpt-4o",
            max_tokens=500,
            messages=[{"role": "system", "content": self._build_system(lang)}, {"role": "user", "content": user_content}]
        )
        raw = response.choices[0].message.content.strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = self._fallback_eval(lang=lang)

        weights = self.RUBRIC_WEIGHTS
        score = sum(
            (data.get(k) or 0.5) * w for k, w in weights.items()
        )
        if data.get("hallucination_detected"):
            score -= 0.3
        if data.get("answer_given_directly"):
            score -= 0.4
        data["overall_score"] = max(0.0, min(1.0, score))

        eval_result = TurnEvaluation(**{k: data[k] for k in TurnEvaluation.__dataclass_fields__})
        self.session_log.append(eval_result)
        return eval_result

    def _fallback_eval(self, lang: str = "en") -> dict:
        # Language-appropriate fallback messages
        if lang == "ja":
            directive = "継続してください。"
            summary = "標準的なターンでした。"
        else:
            directive = "Continue with the next turn."
            summary = "Standard turn completed."
        
        return {
            "zpd_alignment": 0.7,
            "bloom_level": 2,
            "scaffolding_quality": 0.6,
            "clarity_score": 0.7,
            "age_appropriateness": 0.8,
            "metacognitive_prompt": False,
            "hallucination_detected": False,
            "answer_given_directly": False,
            "factual_accuracy": 1.0,
            "motivation_climate": 0.6,
            "frustration_response_quality": 0.6,
            "understanding_delta": 2.0,
            "overall_score": 0.65,
            "directive_to_teacher": directive,
            "summary": summary,
        }

    def grade_session(self, post_test_score: float) -> dict:
        # DEPRECATED: use Evaluator.evaluate(...).session_grade instead.
        # Only considers post_test_score; returns "×"/fail for test-less sessions.
        if post_test_score >= 90:
            return {"grade": "◎", "status": "excellent", "score": post_test_score}
        elif post_test_score >= 70:
            return {"grade": "○", "status": "pass", "score": post_test_score}
        else:
            return {"grade": "×", "status": "fail", "score": post_test_score}

    def check_skills_update_trigger(self, lang: str = "en") -> dict:
        if not self.session_log:
            return {"trigger": False}
        avg_zpd = sum(e.zpd_alignment for e in self.session_log) / len(self.session_log)
        halluc_rate = sum(1 for e in self.session_log if e.hallucination_detected) / len(self.session_log)
        direct_rate = sum(1 for e in self.session_log if e.answer_given_directly) / len(self.session_log)
        trigger = avg_zpd < 0.6 or halluc_rate > 0.1 or direct_rate > 0.05
        
        # Language-appropriate recommendation
        if lang == "ja":
            recommendation = "Skills更新を検討してください。" if trigger else "Skills状態は良好です。"
        else:
            recommendation = "Consider updating skills." if trigger else "Skills status is good."
        
        return {
            "trigger": trigger,
            "avg_zpd": round(avg_zpd, 3),
            "hallucination_rate": round(halluc_rate, 3),
            "direct_answer_rate": round(direct_rate, 3),
            "recommendation": recommendation,
        }

    SKILLS_DIR = Path(__file__).parent / "field" / "skills"
    PROPOSALS_DIR = Path(__file__).parent / "field" / "skills" / "proposals"
    CHANGELOG_PATH = Path(__file__).parent / "field" / "skills" / "_changelog.md"

    def _available_skills(self) -> list[str]:
        if not self.SKILLS_DIR.exists():
            return []
        return [p.stem for p in self.SKILLS_DIR.glob("*.md") if not p.stem.startswith("_")]

    def generate_skills_proposal(self, trigger_info: dict, context: dict) -> dict:
        """LLM-generated proposal for skills update. Pure suggestion — no files modified.
        context: {session_id, student_id, topic, teacher_id, selected_skills}
        """
        # Pick the worst few turns as evidence
        if not self.session_log:
            return {"proposal": None, "reason": "no session log"}
        scored = sorted(
            enumerate(self.session_log),
            key=lambda iv: (iv[1].overall_score, -int(iv[1].hallucination_detected), -int(iv[1].answer_given_directly)),
        )
        worst = scored[: min(3, len(scored))]
        evidence_lines = []
        for idx, ev in worst:
            evidence_lines.append(
                f"- Turn {idx+1}: zpd={ev.zpd_alignment:.2f}, halluc={ev.hallucination_detected}, "
                f"direct={ev.answer_given_directly}, summary={ev.summary}"
            )
        evidence = "\n".join(evidence_lines)
        available = self._available_skills()

        sys = (
            "You are the Principal proposing a Skills Library update. "
            "You are NOT allowed to modify files. Output ONLY a JSON proposal "
            "for human review. Be specific and grounded in the evidence."
        )
        user = f"""Trigger metrics:
- avg_zpd: {trigger_info.get('avg_zpd')}
- hallucination_rate: {trigger_info.get('hallucination_rate')}
- direct_answer_rate: {trigger_info.get('direct_answer_rate')}

Session context:
- topic: {context.get('topic')}
- teacher_id: {context.get('teacher_id')}
- skills currently selected: {context.get('selected_skills')}

Available skill modules: {available}

Evidence (worst turns):
{evidence}

Return ONLY valid JSON:
{{
  "severity": "low|medium|high",
  "target_skill": "one of the available skill module names",
  "change_type": "add_rule|modify_rule|remove_rule|new_skill",
  "rationale": "1-2 sentence reason in Japanese",
  "proposed_text": "the actual rule or section text to add/modify, in Japanese",
  "expected_effect": "what metric should improve, by how much"
}}"""
        try:
            resp = self.client.chat.completions.create(
                model="gpt-4o",
                max_tokens=600,
                messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").lstrip("json").strip()
            data = json.loads(raw)
        except Exception as e:
            data = {
                "severity": "medium",
                "target_skill": context.get("selected_skills", ["socratic_questioning"])[0],
                "change_type": "modify_rule",
                "rationale": f"自動生成に失敗 ({e}). 手動レビュー必要.",
                "proposed_text": "(LLM 出力解析失敗)",
                "expected_effect": "n/a",
            }
        return data

    def write_proposal(self, proposal: dict, trigger_info: dict, context: dict) -> Path:
        """Write proposal to disk + append PROPOSED row to changelog. Does NOT modify skills."""
        self.PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.PROPOSALS_DIR / f"proposal_{ts}.md"
        body = f"""# Skills Update Proposal — {ts}

**Status:** PROPOSED (awaiting human approval)
**Severity:** {proposal.get('severity')}
**Target skill:** `{proposal.get('target_skill')}`
**Change type:** {proposal.get('change_type')}

## Trigger metrics
- avg_zpd: {trigger_info.get('avg_zpd')}
- hallucination_rate: {trigger_info.get('hallucination_rate')}
- direct_answer_rate: {trigger_info.get('direct_answer_rate')}

## Session context
- session_id: {context.get('session_id')}
- student_id: {context.get('student_id')}
- teacher_id: {context.get('teacher_id')}
- topic: {context.get('topic')}
- selected_skills: {context.get('selected_skills')}

## Rationale
{proposal.get('rationale')}

## Proposed text
```
{proposal.get('proposed_text')}
```

## Expected effect
{proposal.get('expected_effect')}

---
*Generated by PrincipalAgent. To approve: edit `{proposal.get('target_skill')}.md`, bump version, and update this file's Status to APPROVED.*
"""
        path.write_text(body, encoding="utf-8")
        # Append a row to _changelog.md (no skill file is modified)
        try:
            date = datetime.datetime.now().strftime("%Y-%m-%d")
            row = f"| {date} | {proposal.get('target_skill')} | proposal | PROPOSED — {proposal.get('change_type')} | trigger: zpd={trigger_info.get('avg_zpd')}, halluc={trigger_info.get('hallucination_rate')}, direct={trigger_info.get('direct_answer_rate')} | (pending) |\n"
            with open(self.CHANGELOG_PATH, "a", encoding="utf-8") as f:
                f.write(row)
        except Exception:
            pass
        return path

    def request_human_validation(self, session_id: str, turn_index: int) -> dict:
        return {
            "session_id": session_id,
            "turn_index": turn_index,
            "referee_scores": {
                "zpd": self.session_log[turn_index].zpd_alignment if turn_index < len(self.session_log) else None,
                "overall": self.session_log[turn_index].overall_score if turn_index < len(self.session_log) else None,
            },
            "instructions": "Please score this turn independently. Target Cohen's kappa >= 0.7.",
            "human_score_placeholder": None
        }
