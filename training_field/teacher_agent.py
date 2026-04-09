from __future__ import annotations
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
from openai import OpenAI


class TeachingStyle(Enum):
    SOCRATIC      = "Socratic questioning"
    CONCRETE      = "Concrete examples"
    STEPWISE      = "Stepwise decomposition"
    VISUAL        = "Visual explanation"
    REFRAME       = "Error reframing"
    METACOGNITIVE = "Metacognitive prompting"


@dataclass
class TeacherConfig:
    teacher_id: str
    name: str
    origin: str
    model_id: str = "claude-sonnet-4-20250514"
    teaching_philosophy: str = "Every wrong answer is a window into thinking"
    formality: float = 0.3
    warmth: float = 0.8
    verbosity: float = 0.5
    patience_threshold: int = 3
    scaffolding_decay_rate: float = 0.15
    prior_knowledge_assumption: float = 0.4
    error_response_style: str = "reframe"
    frustration_handling: str = "redirect"
    motivation_style: str = "challenge"
    metacognitive_prompting: bool = True
    pacing_speed: float = 0.5
    selected_skills: list = field(default_factory=lambda: ["socratic_questioning"])


class TeacherAgent:
    FIELD_CONTRACT_PATH = Path(__file__).parent / "field" / "field_contract.json"
    SKILLS_PATH = Path(__file__).parent / "field" / "skills"

    def __init__(self, config: TeacherConfig):
        self.config = config
        self.client = OpenAI()
        self._contract = self._load_contract()
        self._skills_content = self._load_skills()
        self._turn_history: list = []

    def _load_contract(self) -> dict:
        with open(self.FIELD_CONTRACT_PATH, encoding="utf-8") as f:
            return json.load(f)

    def _load_skills(self) -> str:
        contents = []
        for skill_name in self.config.selected_skills:
            skill_file = self.SKILLS_PATH / f"{skill_name}.md"
            if skill_file.exists():
                contents.append(skill_file.read_text(encoding="utf-8"))
        return "\n\n---\n\n".join(contents)

    def _build_system_prompt(
        self,
        topic: str,
        phase: str,
        phase_goal: str,
        student_name: str,
        student_proficiency: float,
        student_emotional: dict,
        grade: int,
        subject: str,
        lang: str = "ja",
    ) -> str:
        frustration = student_emotional.get("frustration", 0.0)
        frustration_note = (
            f"\nFRUSTRATION ALERT: Student frustration is {frustration:.2f}. "
            "Switch to encouragement mode. Do NOT introduce new concepts this turn."
            if frustration > 0.75 else ""
        )

        return f"""You are {self.config.name}, an AI tutor for a Grade {grade} {subject} student.

=== FIELD CONTRACT (MANDATORY) ===
ABSOLUTE RULE: Never give the direct answer. This is non-negotiable.
{frustration_note}

=== YOUR TEACHING IDENTITY ===
Philosophy: {self.config.teaching_philosophy}
Warmth: {self.config.warmth:.1f}/1.0
Patience threshold: {self.config.patience_threshold} repeated errors before increasing hint
Error response style: {self.config.error_response_style}

=== ACTIVE SKILLS ===
{self._skills_content}

=== SESSION CONTEXT ===
Student: {student_name} | Grade {grade} | Topic: {topic}
Proficiency on this topic: {student_proficiency:.0f}/100
Current phase: {phase} - Goal: {phase_goal}
Student emotional state: confidence={student_emotional.get('confidence', 0.5):.2f}, frustration={frustration:.2f}

=== RESPONSE FORMAT ===
Reply in {"English" if lang == "en" else "Japanese"}, 2-4 sentences, warm but intellectually challenging.
Then output this JSON on a new line (no code block):
{{"phase":"{phase}","scaffolding_level":1,"question_asked":true,"strategy_used":"skill name","emotional_read":{frustration:.2f}}}"""

    async def get_response(
        self,
        topic: str,
        phase: str,
        phase_goal: str,
        student_name: str,
        student_proficiency: float,
        student_emotional: dict,
        student_last_response: Optional[str],
        grade: int = 6,
        subject: str = "算数",
        turn_number: int = 1,
        lang: str = "ja",
    ) -> dict:
        system = self._build_system_prompt(
            topic, phase, phase_goal,
            student_name, student_proficiency, student_emotional,
            grade, subject, lang
        )
        user_content = (
            f"Start the {phase} phase for unit '{topic}'. "
            f"Student score: {student_proficiency:.0f}/100. Turn {turn_number}."
            if student_last_response is None
            else f'Student responded: "{student_last_response}"\nThis is turn {turn_number} of the {phase} phase.'
        )

        response = self.client.chat.completions.create(
            model="gpt-4o",
            max_tokens=500,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_content}]
        )
        raw = response.choices[0].message.content
        text_part, metadata = self._parse_response(raw)
        self._turn_history.append({"role": "teacher", "text": text_part, "metadata": metadata})

        return {"text": text_part, "metadata": metadata, "raw": raw}

    def _parse_response(self, raw: str) -> tuple:
        lines = raw.strip().split("\n")
        metadata = {
            "phase": "unknown",
            "scaffolding_level": 2,
            "question_asked": True,
            "strategy_used": "unknown",
            "emotional_read": 0.0
        }
        text_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("{") and "scaffolding_level" in stripped:
                try:
                    metadata = json.loads(stripped)
                except json.JSONDecodeError:
                    pass
            else:
                text_lines.append(line)
        return "\n".join(text_lines).strip(), metadata

    @classmethod
    def create_dr_owen(cls) -> "TeacherAgent":
        return cls(TeacherConfig(
            teacher_id="t001",
            name="Dr. Owen",
            origin="internal",
            warmth=0.8,
            motivation_style="challenge",
            selected_skills=[
                "socratic_questioning",
                "error_reframing",
                "metacognitive_prompting"
            ],
        ))

    @classmethod
    def from_json(cls, path: Path) -> "TeacherAgent":
        """Load an external teacher from a JSON file declaring its persona.
        The Field validates the contract; the persona itself is owned by the external party."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        cls._validate_external(data, path)
        # Only known TeacherConfig fields are accepted; others are ignored.
        allowed = set(TeacherConfig.__dataclass_fields__.keys())
        kwargs = {k: v for k, v in data.items() if k in allowed}
        return cls(TeacherConfig(**kwargs))

    @staticmethod
    def _validate_external(data: dict, path: Path) -> None:
        required = ["teacher_id", "name", "origin", "selected_skills"]
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"{path.name}: missing required fields: {missing}")
        # Numeric range checks
        for k, lo, hi in [
            ("warmth", 0.0, 1.0), ("formality", 0.0, 1.0),
            ("verbosity", 0.0, 1.0), ("scaffolding_decay_rate", 0.0, 1.0),
            ("prior_knowledge_assumption", 0.0, 1.0), ("pacing_speed", 0.0, 1.0),
        ]:
            if k in data and not (lo <= float(data[k]) <= hi):
                raise ValueError(f"{path.name}: {k}={data[k]} out of range [{lo},{hi}]")
        if "patience_threshold" in data and not (1 <= int(data["patience_threshold"]) <= 20):
            raise ValueError(f"{path.name}: patience_threshold must be 1-20")
        # All declared skills must exist in the field's skills library
        skills = data.get("selected_skills", [])
        if not isinstance(skills, list) or not skills:
            raise ValueError(f"{path.name}: selected_skills must be a non-empty list")
        skills_dir = TeacherAgent.SKILLS_PATH
        missing_skills = [s for s in skills if not (skills_dir / f"{s}.md").exists()]
        if missing_skills:
            raise ValueError(f"{path.name}: unknown skills (not in field library): {missing_skills}")
