from __future__ import annotations
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from datetime import datetime
from typing import Optional


@dataclass
class ExperimentHypothesis:
    hypothesis_id: str
    description: str
    independent_variable: str
    dependent_variable: str
    expected_direction: str
    confirmed: Optional[bool] = None
    evidence: Optional[str] = None


@dataclass
class ExperimentRecord:
    exp_id: str
    hypothesis_id: Optional[str]
    timestamp: str
    student_id: str
    teacher_id: str
    topic: str
    grade: int
    subject: str
    depth: str
    teaching_style: str
    skills_used: list
    pre_test_score: Optional[float]
    post_test_score: Optional[float]
    learning_gain: float
    proficiency_delta: float
    hallucination_rate: float
    direct_answer_rate: float
    avg_zpd_alignment: float
    avg_bloom_level: float
    frustration_events: int
    aha_moments: int
    teacher_compatibility_score: float
    total_tokens: int
    cost_usd: float
    session_grade: str
    status: str = "completed"


PREDEFINED_HYPOTHESES = [
    ExperimentHypothesis(
        hypothesis_id="H1",
        description="Socratic style yields higher retention after 2 weeks vs Stepwise",
        independent_variable="teaching_style (SOCRATIC vs STEPWISE)",
        dependent_variable="retention_score_2weeks",
        expected_direction="interaction"
    ),
    ExperimentHypothesis(
        hypothesis_id="H2",
        description="Low-confidence students learn better with high-warmth teachers",
        independent_variable="teacher_warmth x student_confidence",
        dependent_variable="learning_gain",
        expected_direction="interaction"
    ),
    ExperimentHypothesis(
        hypothesis_id="H3",
        description="Optimal turn count depends on student patience, Deep is not always best",
        independent_variable="depth (quick/standard/deep) x student_patience",
        dependent_variable="learning_gain",
        expected_direction="interaction"
    ),
]


class ExperimentRegistry:
    REGISTRY_PATH = Path(__file__).parent / "experiments" / "experiment_registry.json"

    def __init__(self):
        self.REGISTRY_PATH.parent.mkdir(exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        if self.REGISTRY_PATH.exists():
            with open(self.REGISTRY_PATH, encoding="utf-8") as f:
                return json.load(f)
        return {
            "version": "1.0",
            "hypotheses": [asdict(h) for h in PREDEFINED_HYPOTHESES],
            "weekly_schedule": {
                "wednesday": "agent_interaction_sessions",
                "thursday": "skill_branch_testing",
                "friday": "evaluation_and_report"
            },
            "experiments": []
        }

    def _save(self):
        with open(self.REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def register(self, record: ExperimentRecord):
        self._data["experiments"].append(asdict(record))
        self._save()

    def query(
        self,
        sort_by: str = "learning_gain",
        filter_by: Optional[dict] = None,
        limit: int = 20
    ) -> list:
        results = list(self._data["experiments"])
        if filter_by:
            for k, v in filter_by.items():
                results = [r for r in results if r.get(k) == v]
        results.sort(key=lambda r: r.get(sort_by, 0), reverse=True)
        return results[:limit]

    def get_best_teacher_student_pairs(self, topic: str) -> list:
        return self.query(
            sort_by="teacher_compatibility_score",
            filter_by={"topic": topic, "status": "completed"}
        )

    def summary(self) -> dict:
        experiments = self._data["experiments"]
        if not experiments:
            return {"total": 0}
        gains = [e["learning_gain"] for e in experiments if e["learning_gain"] is not None]
        return {
            "total_sessions": len(experiments),
            "avg_learning_gain": round(sum(gains) / len(gains), 2) if gains else 0,
            "total_cost_usd": round(sum(e.get("cost_usd", 0) for e in experiments), 4),
            "pass_rate": round(
                sum(1 for e in experiments if e.get("session_grade") in ["◎", "○"]) / len(experiments), 3
            ),
        }
