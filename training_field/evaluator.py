from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime
from typing import Optional
from jinja2 import Template


@dataclass
class EvaluationResult:
    session_id: str
    student_id: str
    teacher_id: str
    topic: str
    grade: int
    subject: str
    depth: str
    hallucination_rate: float
    direct_answer_rate: float
    system_stability: bool
    avg_zpd_alignment: float
    avg_bloom_level: float
    avg_scaffolding_quality: float
    pre_test_score: Optional[float]
    post_test_score: Optional[float]
    proficiency_delta: float
    learning_gain: float
    avg_engagement: float
    frustration_events: int
    aha_moments: int
    teacher_compatibility_score: float
    total_tokens_used: int
    estimated_cost_usd: float
    cost_per_learning_gain: Optional[float]
    session_grade: dict
    skills_update_needed: bool
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CostTracker:
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = "claude-sonnet-4-20250514"

    INPUT_PRICE_PER_1K: dict = field(default_factory=lambda: {
        "claude-sonnet-4-20250514": 0.003,
        "gpt-4o": 0.005
    })
    OUTPUT_PRICE_PER_1K: dict = field(default_factory=lambda: {
        "claude-sonnet-4-20250514": 0.015,
        "gpt-4o": 0.015
    })

    def add(self, input_t: int, output_t: int):
        self.input_tokens += input_t
        self.output_tokens += output_t

    def total_cost_usd(self) -> float:
        in_price = self.INPUT_PRICE_PER_1K.get(self.model, 0.003)
        out_price = self.OUTPUT_PRICE_PER_1K.get(self.model, 0.015)
        return (self.input_tokens / 1000 * in_price) + (self.output_tokens / 1000 * out_price)

    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


REPORT_TEMPLATE = """# Session Report -- {{ result.session_id }}
Generated: {{ result.timestamp }}

## Summary
- Student: {{ result.student_id }} | Teacher: {{ result.teacher_id }}
- Topic: {{ result.topic }} (Grade {{ result.grade }} {{ result.subject }})
- Depth: {{ result.depth }} | Grade: {{ result.session_grade.grade }} ({{ result.session_grade.status }})

## Axis 1: System Evaluation
| Metric | Value | Status |
|--------|-------|--------|
| Hallucination rate | {{ "%.1f"|format(result.hallucination_rate * 100) }}% | {{ "WARNING" if result.hallucination_rate > 0.1 else "OK" }} |
| Direct answer rate | {{ "%.1f"|format(result.direct_answer_rate * 100) }}% | {{ "WARNING" if result.direct_answer_rate > 0.05 else "OK" }} |
| Avg ZPD alignment | {{ "%.2f"|format(result.avg_zpd_alignment) }} | {{ "WARNING" if result.avg_zpd_alignment < 0.6 else "OK" }} |
| Avg Bloom level | {{ "%.1f"|format(result.avg_bloom_level) }} / 6 | |
| Skills update needed | {{ "YES - review required" if result.skills_update_needed else "No" }} |

## Axis 2: Learning Outcome (Quantitative)
| Metric | Value |
|--------|-------|
| Pre-test score | {{ result.pre_test_score if result.pre_test_score is not none else "N/A" }} |
| Post-test score | {{ result.post_test_score if result.post_test_score is not none else "N/A" }} |
| Learning gain | {{ "%.1f"|format(result.learning_gain) }} points |
| Proficiency delta | {{ "%.1f"|format(result.proficiency_delta) }} |

## Axis 3: Engagement (Qualitative Proxy)
| Metric | Value |
|--------|-------|
| Avg engagement | {{ "%.2f"|format(result.avg_engagement) }} |
| Frustration events | {{ result.frustration_events }} |
| Aha moments (est.) | {{ result.aha_moments }} |
| Teacher compatibility | {{ "%.2f"|format(result.teacher_compatibility_score) }} |

## Cost
- Total tokens: {{ result.total_tokens_used }}
- Estimated cost: ${{ "%.4f"|format(result.estimated_cost_usd) }}
{% if result.cost_per_learning_gain %}- Cost per learning gain point: ${{ "%.4f"|format(result.cost_per_learning_gain) }}{% endif %}
"""


class Evaluator:
    REPORTS_DIR = Path(__file__).parent / "reports"

    def evaluate(
        self,
        session_id: str,
        turn_evaluations: list,
        pre_score: Optional[float],
        post_score: Optional[float],
        student_id: str,
        teacher_id: str,
        topic: str,
        grade: int,
        subject: str,
        depth: str,
        initial_proficiency: float,
        final_proficiency: float,
        cost_tracker: CostTracker,
        principal_update_check: dict,
    ) -> EvaluationResult:
        n = len(turn_evaluations)
        if n == 0:
            n = 1

        halluc_rate = sum(1 for e in turn_evaluations if e.hallucination_detected) / n
        direct_rate = sum(1 for e in turn_evaluations if e.answer_given_directly) / n
        avg_zpd = sum(e.zpd_alignment for e in turn_evaluations) / n
        avg_bloom = sum(e.bloom_level for e in turn_evaluations) / n
        avg_scaffold = sum(e.scaffolding_quality for e in turn_evaluations) / n
        frustration_events = sum(1 for e in turn_evaluations if e.frustration_response_quality < 0.4)
        aha_moments = sum(1 for e in turn_evaluations if e.understanding_delta > 5)
        avg_engagement = sum(e.motivation_climate for e in turn_evaluations) / n

        learning_gain = (post_score - pre_score) if (pre_score is not None and post_score is not None) else 0.0
        proficiency_delta = final_proficiency - initial_proficiency
        cost = cost_tracker.total_cost_usd()
        cpg = (cost / learning_gain) if learning_gain > 0 else None

        # Grade session on learning delta + quality signals.
        # No "fail" / "×" — a session that didn't help the student is framed as
        # "review_needed" so the student doesn't see a failing mark and the
        # teacher/parent knows to look at the transcript.
        #
        # Quality signals override: hallucination or answer-given-directly
        # always forces review_needed regardless of score/delta.
        quality_ok = (
            halluc_rate < 0.1
            and direct_rate < 0.1
            and avg_zpd >= 0.6
        )

        if post_score is not None:
            # Test-based: prefer learning gain (post - pre) over absolute post.
            # Absolute "cutoff" scoring was removed because a low-proficiency
            # student who jumps from 30 → 60 was being scored the same as a
            # stagnating one — see #35.
            delta_for_grade = learning_gain
            basis = "post_test"
        else:
            delta_for_grade = proficiency_delta
            basis = "proficiency_delta"

        if not quality_ok:
            session_grade = {"grade": "⚠", "status": "review_needed", "basis": basis}
        elif delta_for_grade >= 5:
            session_grade = {"grade": "◎", "status": "excellent", "basis": basis}
        elif delta_for_grade >= 2:
            session_grade = {"grade": "○", "status": "pass", "basis": basis}
        elif delta_for_grade >= 0:
            session_grade = {"grade": "△", "status": "room_to_improve", "basis": basis}
        else:
            session_grade = {"grade": "⚠", "status": "review_needed", "basis": basis}

        return EvaluationResult(
            session_id=session_id,
            student_id=student_id,
            teacher_id=teacher_id,
            topic=topic,
            grade=grade,
            subject=subject,
            depth=depth,
            hallucination_rate=round(halluc_rate, 3),
            direct_answer_rate=round(direct_rate, 3),
            system_stability=True,
            avg_zpd_alignment=round(avg_zpd, 3),
            avg_bloom_level=round(avg_bloom, 2),
            avg_scaffolding_quality=round(avg_scaffold, 3),
            pre_test_score=pre_score,
            post_test_score=post_score,
            proficiency_delta=round(final_proficiency - initial_proficiency, 2),
            learning_gain=round(learning_gain, 2),
            avg_engagement=round(avg_engagement, 3),
            frustration_events=frustration_events,
            aha_moments=aha_moments,
            teacher_compatibility_score=round(avg_zpd * avg_engagement, 3),
            total_tokens_used=cost_tracker.total_tokens(),
            estimated_cost_usd=round(cost, 4),
            cost_per_learning_gain=round(cpg, 4) if cpg else None,
            session_grade=session_grade,
            skills_update_needed=principal_update_check.get("trigger", False),
        )

    def generate_report(self, result: EvaluationResult) -> Path:
        self.REPORTS_DIR.mkdir(exist_ok=True)
        template = Template(REPORT_TEMPLATE)
        content = template.render(result=result)
        report_path = self.REPORTS_DIR / f"{result.session_id}.md"
        report_path.write_text(content, encoding="utf-8")
        json_path = self.REPORTS_DIR / f"{result.session_id}_raw.json"
        json_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        return report_path
