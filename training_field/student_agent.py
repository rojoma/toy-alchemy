from __future__ import annotations
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .llm import chat_complete
from .proficiency_model import ProficiencyModel, EmotionalState


@dataclass
class StudentAgent:
    student_id: str
    name: str
    nickname_ja: str
    grade: int
    subject: str
    personality: dict
    proficiency_model: ProficiencyModel
    emotional_state: EmotionalState
    error_patterns: list

    def name_ja(self) -> str:
        return self.nickname_ja or self.name

    async def get_response(
        self,
        teacher_message: str,
        topic: str,
        phase: str,
        is_correct_turn: Optional[bool] = None,
        lang: str = "en",
    ) -> dict:
        if is_correct_turn is None:
            difficulty_map = {
                "diagnosis": -0.5,
                "exploration": 0.0,
                "practice": 0.5,
                "reflection": -0.3
            }
            is_correct = self.proficiency_model.should_answer_correctly(
                topic, difficulty_b=difficulty_map.get(phase, 0.0)
            )
        else:
            is_correct = is_correct_turn

        prof = self.proficiency_model.topic_proficiencies.get(
            topic, self.proficiency_model.proficiency
        )
        if lang == "en":
            prof_desc = (
                "shaky on basic concepts" if prof < 40
                else "frequent calculation errors" if prof < 55
                else "struggles with applied problems" if prof < 70
                else "mostly understands"
            )
            display_name = self.name
            system = f"""You are {display_name}, a grade {self.grade} elementary school student.
Your proficiency on the unit "{topic}" is {prof:.0f}/100 ({prof_desc}).
Current phase: {phase}

Personality:
- curiosity: {self.personality['curiosity']:.1f}/1.0
- patience: {self.personality['patience']:.1f}/1.0
- confidence: {self.personality['confidence']:.1f}/1.0
- verbosity: {self.personality['verbosity']:.1f}/1.0
- traits: {self.personality['description']}

Emotional state: {self.emotional_state.to_prompt_description()}

For this question, {'answer correctly (but in a natural, kid-like way as if you figured it out yourself)' if is_correct else f'make a mistake (typical kid errors: {", ".join(self.error_patterns[:2])})'}.

{'Reply in 4-15 characters total. Use one short word, a single concrete noun, or refusals like "dunno", "no idea", "I told you I dont know!". Do NOT pad. Silence and curt refusals are realistic.' if self.personality.get('verbosity', 0.5) <= 0.1 else f'Reply in 2-4 sentences in English with realistic grade-{self.grade} language.'} Stay in character as {display_name}."""
            user_msg = f'The teacher said: "{teacher_message}"'
        else:
            prof_desc = (
                "基礎概念が不安定" if prof < 40
                else "計算ミスが多い" if prof < 55
                else "応用問題が苦手" if prof < 70
                else "ほぼ理解できている"
            )
            display_name = self.name_ja()
            system = f"""あなたは小学{self.grade}年生の{display_name}です。
単元「{topic}」の習熟度は{prof:.0f}/100（{prof_desc}）です。
現在のフェーズ: {phase}

性格:
- 好奇心: {self.personality['curiosity']:.1f}/1.0
- 忍耐力: {self.personality['patience']:.1f}/1.0
- 自信: {self.personality['confidence']:.1f}/1.0
- 話量: {self.personality['verbosity']:.1f}/1.0
- 特徴: {self.personality['description']}

感情状態: {self.emotional_state.to_prompt_description()}

この問いに対して{'正しく答えてください（ただし自分で考えたように自然に）' if is_correct else f'間違えてください（典型的な小学生のミス: {", ".join(self.error_patterns[:2])}）'}。

{'返答は4〜15文字で。短い一語、具体物の名前、または「知らない」「わからない」「だからわからないって！」のような短い拒絶のみ。文を埋めないこと。沈黙や苛立った短文も自然。' if self.personality.get('verbosity', 0.5) <= 0.1 else f'返答は2〜4文、日本語で。{self.grade}年生らしいリアルな言葉遣いで。'}"""
            user_msg = f'先生が言いました: "{teacher_message}"'

        text = chat_complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
            role="student",
            max_tokens=300,
        )

        self.emotional_state.update(
            was_correct=is_correct,
            teacher_warmth=self.personality.get("warmth_received", 0.5)
        )

        return {
            "text": text,
            "was_correct": is_correct,
            "proficiency_at_turn": prof,
            "emotional_state": {
                "confidence": round(self.emotional_state.confidence, 2),
                "frustration": round(self.emotional_state.frustration, 2),
                "engagement": round(self.emotional_state.engagement, 2),
            }
        }

    async def generate_test_answer(
        self, question_text: str, correct_answer: str, topic: str, lang: str = "en"
    ) -> dict:
        is_correct = self.proficiency_model.should_answer_correctly(topic, difficulty_b=0.3)
        prof = self.proficiency_model.topic_proficiencies.get(
            topic, self.proficiency_model.proficiency
        )

        if lang == "en":
            system = f"""You are {self.name}, a grade {self.grade} student taking a test.
Topic: "{topic}" — your proficiency: {prof:.0f}/100.
Personality: {self.personality['description']}

{'Answer correctly (but naturally, as if you figured it out).' if is_correct else f'Make a mistake (typical errors: {", ".join(self.error_patterns)}). Do NOT write the correct answer.'}
Write only your answer, briefly, in English."""
        else:
            system = f"""あなたは小学{self.grade}年生の{self.name_ja()}です。
テストを受けています。単元「{topic}」の習熟度: {prof:.0f}/100。
性格: {self.personality['description']}

この問題に{'正しく答えてください' if is_correct else f'間違えてください。典型的なミス: {", ".join(self.error_patterns)}。正解は絶対に書かないこと'}。
答えだけを短く日本語で書いてください。"""

        answer = chat_complete(
            [{"role": "system", "content": system}, {"role": "user", "content": question_text}],
            role="student",
            max_tokens=100,
        )
        return {
            "student_answer": answer.strip(),
            "is_correct": is_correct,
            "correct_answer": correct_answer,
        }

class StudentAgentFactory:

    @staticmethod
    def from_profile(student_id: str) -> StudentAgent:
        profiles_path = Path(__file__).parent / "profiles" / "student_profiles.json"
        with open(profiles_path, encoding="utf-8") as f:
            data = json.load(f)
        profile = next(s for s in data["students"] if s["student_id"] == student_id)

        prof_model = ProficiencyModel(
            proficiency=sum(profile["proficiency_baseline"].values()) / len(profile["proficiency_baseline"]),
            topic_proficiencies=dict(profile["proficiency_baseline"])
        )
        emotional = EmotionalState(**profile["emotional_state_init"])

        return StudentAgent(
            student_id=profile["student_id"],
            name=profile["name"],
            nickname_ja=profile["nickname_ja"],
            grade=profile["grade"],
            subject=profile["subject"],
            personality=profile["personality"],
            proficiency_model=prof_model,
            emotional_state=emotional,
            error_patterns=profile["error_patterns"],
        )

    @staticmethod
    def from_derived_profile(profile_path: Path, *, display_name: str | None = None) -> StudentAgent:
        """Build a StudentAgent from a real student's derived block (#63).

        `profile_path` is the JSON file at reports/students/{id}.json. The
        file must already have a `derived` block with the personality +
        signals fields produced by student_profile_deriver (#62).

        `display_name` overrides the student's real name in the agent
        (e.g. "Student #4") to avoid leaking PII when the agent is shown
        to other users.
        """
        with open(profile_path, encoding="utf-8") as f:
            profile = json.load(f)
        derived = profile.get("derived") or {}
        personality = dict(derived.get("personality") or {})
        # Fill defaults so the existing prompt builder doesn't KeyError.
        personality.setdefault("curiosity", 0.5)
        personality.setdefault("patience", 0.5)
        personality.setdefault("confidence", 0.5)
        personality.setdefault("verbosity", 0.3)
        personality.setdefault("description", "Auto-derived from real session data.")

        # Proficiency: prefer the per-topic map the user accumulated through
        # /api/student/{id}/update-proficiency. Fall back to a single 50.
        topic_profs = dict(profile.get("proficiency") or {})
        avg_prof = (
            sum(topic_profs.values()) / len(topic_profs)
            if topic_profs else 50.0
        )
        prof_model = ProficiencyModel(
            proficiency=avg_prof,
            topic_proficiencies=topic_profs,
        )

        signals = derived.get("signals") or {}
        emotional = EmotionalState(
            confidence=personality["confidence"],
            frustration=min(max(signals.get("frustration_rate", 0.1), 0.0), 1.0),
            engagement=personality["curiosity"],
        )

        # Misconception strings from #62 surface here as "error patterns" so
        # the existing on-mistake prompt branch can use them.
        miscon = list(derived.get("misconceptions") or [])
        if not miscon:
            miscon = ["typical kid errors"]

        name = display_name or profile.get("name") or "Student"
        return StudentAgent(
            student_id=f"der_{profile['student_id']}",
            name=name,
            nickname_ja=name,
            grade=int(profile.get("grade") or 6),
            subject=profile.get("subject", "math"),
            personality=personality,
            proficiency_model=prof_model,
            emotional_state=emotional,
            error_patterns=miscon[:3],
        )

    @staticmethod
    def create_custom(
        name: str,
        grade: int,
        proficiency_range: tuple,
        personality_preset: str,
        weak_topics: list
    ) -> StudentAgent:
        presets = {
            "anxious":    {"curiosity": 0.3, "patience": 0.6, "confidence": 0.2, "verbosity": 0.3},
            "impulsive":  {"curiosity": 0.8, "patience": 0.3, "confidence": 0.6, "verbosity": 0.8},
            "methodical": {"curiosity": 0.5, "patience": 0.8, "confidence": 0.5, "verbosity": 0.5},
            "confident":  {"curiosity": 0.7, "patience": 0.6, "confidence": 0.8, "verbosity": 0.7},
        }
        personality = presets.get(personality_preset, presets["methodical"])
        personality["description"] = f"Custom {personality_preset} student"

        base_prof = random.randint(*proficiency_range)
        topics = [
            "分数のかけ算・わり算", "比と比の値", "速さ・時間・距離",
            "比例と反比例", "円の面積", "場合の数"
        ]
        topic_profs = {}
        for t in topics:
            if t in weak_topics:
                topic_profs[t] = max(10, base_prof - random.randint(15, 30))
            else:
                topic_profs[t] = min(99, base_prof + random.randint(-10, 10))

        return StudentAgent(
            student_id=f"custom_{name.lower()}",
            name=name,
            nickname_ja=name,
            grade=grade,
            subject="math",
            personality=personality,
            proficiency_model=ProficiencyModel(
                proficiency=base_prof,
                topic_proficiencies=topic_profs
            ),
            emotional_state=EmotionalState(
                confidence=personality["confidence"],
                frustration=0.1,
                engagement=personality["curiosity"]
            ),
            error_patterns=["計算ミス", "問題文の読み間違い"],
        )
