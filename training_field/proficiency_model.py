from __future__ import annotations
import math
import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EmotionalState:
    confidence: float
    frustration: float
    engagement: float

    def update(self, was_correct: bool, teacher_warmth: float = 0.5) -> None:
        if was_correct:
            self.confidence = min(1.0, self.confidence + 0.05)
            self.frustration = max(0.0, self.frustration - 0.10)
            self.engagement = min(1.0, self.engagement + 0.03)
        else:
            self.confidence = max(0.0, self.confidence - 0.08)
            self.frustration = min(1.0, self.frustration + 0.15)
            self.frustration = max(0.0, self.frustration - teacher_warmth * 0.05)

    def to_prompt_description(self) -> str:
        conf_desc = (
            "very unconfident and hesitant" if self.confidence < 0.3
            else "somewhat uncertain" if self.confidence < 0.5
            else "moderately confident" if self.confidence < 0.7
            else "confident"
        )
        frust_desc = (
            "very frustrated and close to giving up" if self.frustration > 0.75
            else "noticeably frustrated" if self.frustration > 0.5
            else "mildly frustrated" if self.frustration > 0.25
            else "calm"
        )
        return f"Currently {conf_desc} and {frust_desc}."


@dataclass
class ProficiencyModel:
    proficiency: float
    topic_proficiencies: dict

    @staticmethod
    def _to_theta(proficiency: float) -> float:
        return (proficiency - 50) / 17.0

    @staticmethod
    def _sigmoid(x: float) -> float:
        return 1.0 / (1.0 + math.exp(-x))

    def p_correct(
        self,
        topic: str,
        difficulty_b: float = 0.0,
        discrimination_a: float = 1.0,
        guessing_c: float = 0.1
    ) -> float:
        theta = self._to_theta(self.topic_proficiencies.get(topic, self.proficiency))
        return guessing_c + (1 - guessing_c) * self._sigmoid(discrimination_a * (theta - difficulty_b))

    def should_answer_correctly(self, topic: str, difficulty_b: float = 0.0) -> bool:
        return random.random() < self.p_correct(topic, difficulty_b)

    def update_after_session(self, topic: str, learning_gain: float) -> None:
        old = self.topic_proficiencies.get(topic, self.proficiency)
        self.topic_proficiencies[topic] = min(100.0, old + learning_gain)
        self.proficiency = sum(self.topic_proficiencies.values()) / len(self.topic_proficiencies)

    def apply_forgetting(self, topic: str, days_elapsed: float, stability: float = 10.0) -> None:
        old = self.topic_proficiencies.get(topic, self.proficiency)
        decayed = old * math.exp(-days_elapsed / stability)
        self.topic_proficiencies[topic] = max(0.0, decayed)


@dataclass
class CurriculumGraph:
    graph: dict = field(default_factory=lambda: {
        "分数のかけ算・わり算": ["分数の意味", "かけ算・わり算の基本"],
        "比と比の値": ["割合", "分数の意味"],
        "速さ・時間・距離": ["比と比の値", "単位換算"],
        "比例と反比例": ["比と比の値", "座標の基本"],
        "円の面積": ["円の性質", "面積の公式"],
        "場合の数": ["整数の列挙", "基本的な数え方"],
    })

    def get_prerequisites(self, topic: str) -> list:
        return self.graph.get(topic, [])

    def is_ready_to_learn(self, topic: str, student_proficiencies: dict) -> tuple:
        missing = [
            prereq for prereq in self.get_prerequisites(topic)
            if student_proficiencies.get(prereq, 0) < 50
        ]
        return len(missing) == 0, missing
