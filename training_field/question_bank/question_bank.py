from __future__ import annotations
import json
import hashlib
import asyncio
import aiosqlite
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from training_field.llm import chat_complete


@dataclass
class Question:
    id: str
    source_style: str
    grade: int
    subject: str
    unit: str
    question_text: str
    correct_answer: str
    explanation: str
    difficulty_b: float
    discrimination_a: float
    question_type: str
    cognitive_level: int
    nakatsu_style: bool
    pisa_style: bool
    times_used: int = 0

    @classmethod
    def make_id(cls, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]


class QuestionBank:
    DB_PATH = Path(__file__).parent / "generated" / "questions.db"
    SOURCES_PATH = Path(__file__).parent / "sources"
    COPYRIGHT_SAFE_MODE = True

    def __init__(self):
        self._nakatsu = self._load_json("nakatsu_index.json")
        self._pisa = self._load_json("pisa_index.json")

    def _load_json(self, filename: str) -> dict:
        p = self.SOURCES_PATH / filename
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        return {}

    async def init_db(self):
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    id TEXT PRIMARY KEY,
                    source_style TEXT,
                    grade INTEGER,
                    subject TEXT,
                    unit TEXT,
                    question_text TEXT,
                    correct_answer TEXT,
                    explanation TEXT,
                    difficulty_b REAL,
                    discrimination_a REAL,
                    question_type TEXT,
                    cognitive_level INTEGER,
                    nakatsu_style INTEGER,
                    pisa_style INTEGER,
                    times_used INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()

    async def generate_question(
        self,
        grade: int,
        subject: str,
        unit: str,
        difficulty: str,
        style: str = "nakatsu",
    ) -> Question:
        difficulty_b_map = {"基本": -1.0, "応用": 0.0, "発展": 1.2}
        bloom_map = {"基本": 2, "応用": 3, "発展": 5}

        # Subject lock: tells the LLM exactly what content domain is acceptable.
        subject_lock = {
            "算数": "MUST be a mathematics problem (numbers, calculation, geometry, fractions, decimals, ratios, etc). The student must perform a mathematical operation. NEVER make a reading-comprehension, science-observation, or general-knowledge question.",
            "数学": "MUST be a mathematics problem. NEVER make a reading-comprehension or science question.",
            "国語": "MUST be a Japanese-language problem (reading comprehension, kanji, vocabulary, grammar). NEVER make a math or science question.",
            "理科": "MUST be a science problem (observation, experiment, natural phenomena). NEVER make a math or reading-comprehension question.",
            "社会": "MUST be a social-studies problem (geography, history, civics). NEVER make a math or science question.",
            "英語": "MUST be an English-language problem (vocabulary, grammar, reading). NEVER make a math or science question."
        }
        lock = subject_lock.get(subject, f"MUST be a {subject} problem.")

        # Style flavor (optional dressing — content domain is enforced by `lock`).
        style_flavor = {
            "nakatsu": "Format inspired by 全国学力・学習状況調査: combine knowledge with thinking/judgment, allow real-life context as the WRAPPER for the subject content, mix multiple-choice and short-answer forms.",
            "pisa": "Format inspired by PISA: brief real-world context (80-120 chars) wrapping the subject content, then a clear question."
        }

        system = f"""You generate ONE original test question for grade {grade}, subject "{subject}", unit "{unit}".

CRITICAL CONTENT RULE (do not violate, do not interpret loosely):
{lock}
The unit name "{unit}" is the specific content focus — every question must directly require the student to apply knowledge from this unit.

STYLE:
{style_flavor.get(style, style_flavor['nakatsu'])}
Real-world contexts are allowed ONLY as a wrapper for the subject content; the core question must still be solvable using "{unit}" knowledge.

ANTI-EXAMPLES (do NOT generate questions like these):
- A passage about studying methods or rice paddies, even framed as 全国学力 style — that violates the subject lock.
- A question that could be answered without using "{unit}" content.

Reply with ONE valid JSON object only (no code fence, no prose before/after):
{{"question_text":"the question (must require {unit} knowledge)","correct_answer":"correct answer","explanation":"why","question_type":"選択|記述|複合","estimated_cognitive_level":2}}"""

        # Default fallback question in case of API errors
        fallback_data = {
            "question_text": f"{unit}に関する{difficulty}問題: この単元の基本的な計算問題を解いてください。",
            "correct_answer": "解答例",
            "explanation": "解説: この問題は基本的な概念の理解を確認します。",
            "question_type": "記述",
            "estimated_cognitive_level": bloom_map.get(difficulty, 2)
        }

        try:
            raw = chat_complete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Generate one {difficulty}-level test question for subject \"{subject}\", unit \"{unit}\", grade {grade}. The question must be answerable only by using {unit} knowledge."},
                ],
                role="question_bank",
                max_tokens=2000,
                temperature=0.3,
            ).strip()
            print(f"[QuestionBank] raw response (first 300 chars): {raw[:300]!r}")

            # Strip code fences if present (```json ... ``` or just ``` ... ```)
            cleaned = raw
            if cleaned.startswith("```"):
                # Drop the first line (```json or ```) and any trailing ```
                lines = cleaned.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                cleaned = "\n".join(lines).strip()

            # Robust extraction: find the first {...} block. Helps when the model
            # adds a preamble like "Here's the question:" before the JSON.
            data = None
            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                # Find the largest balanced {...} substring
                import re
                start_idx = cleaned.find("{")
                if start_idx >= 0:
                    depth = 0
                    end_idx = -1
                    for i, ch in enumerate(cleaned[start_idx:], start=start_idx):
                        if ch == "{":
                            depth += 1
                        elif ch == "}":
                            depth -= 1
                            if depth == 0:
                                end_idx = i + 1
                                break
                    if end_idx > start_idx:
                        candidate = cleaned[start_idx:end_idx]
                        try:
                            data = json.loads(candidate)
                        except json.JSONDecodeError as e2:
                            print(f"[QuestionBank] JSON extract still failed: {e2}")
            if data is None:
                raise json.JSONDecodeError("no parseable JSON in response", cleaned, 0)

            # Validate required fields exist
            if not data.get("question_text") or not data.get("correct_answer"):
                print(f"[QuestionBank] Generated question missing required fields, using fallback")
                data = fallback_data

        except json.JSONDecodeError as e:
            print(f"[QuestionBank] JSON parse error: {e}, using fallback question")
            data = fallback_data
        except Exception as e:
            print(f"[QuestionBank] OpenAI API error: {e}, using fallback question")
            data = fallback_data

        q = Question(
            id=Question.make_id(data["question_text"]),
            source_style=style,
            grade=grade,
            subject=subject,
            unit=unit,
            question_text=data["question_text"],
            correct_answer=data["correct_answer"],
            explanation=data.get("explanation", "解説"),
            difficulty_b=difficulty_b_map.get(difficulty, 0.0),
            discrimination_a=1.0,
            question_type=data.get("question_type", "記述"),
            cognitive_level=data.get("estimated_cognitive_level", bloom_map.get(difficulty, 2)),
            nakatsu_style=(style == "nakatsu"),
            pisa_style=(style == "pisa"),
        )
        await self._save_question(q)
        return q

    async def _save_question(self, q: Question):
        async with aiosqlite.connect(self.DB_PATH) as db:
            await db.execute(
                """INSERT OR IGNORE INTO questions
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                (q.id, q.source_style, q.grade, q.subject, q.unit,
                 q.question_text, q.correct_answer, q.explanation,
                 q.difficulty_b, q.discrimination_a, q.question_type,
                 q.cognitive_level, int(q.nakatsu_style), int(q.pisa_style), q.times_used)
            )
            await db.commit()

    async def get_test_questions(
        self,
        grade: int,
        subject: str,
        unit: str,
        num_questions: int = 5,
        style: str = "nakatsu",
        exclude_ids: Optional[list] = None,
    ) -> list:
        try:
            await self.init_db()
        except Exception as e:
            print(f"[QuestionBank] Database init failed: {e}")
            # Return generated questions without DB caching
            return await self._generate_fallback_questions(grade, subject, unit, num_questions, style)
        
        exclude_ids = exclude_ids or []
        questions = []

        try:
            async with aiosqlite.connect(self.DB_PATH) as db:
                if exclude_ids:
                    placeholders = ",".join("?" * len(exclude_ids))
                    query = f"""SELECT * FROM questions
                        WHERE grade=? AND subject=? AND unit=?
                        AND id NOT IN ({placeholders})
                        ORDER BY times_used ASC, RANDOM() LIMIT ?"""
                    params = [grade, subject, unit] + exclude_ids + [num_questions]
                else:
                    query = """SELECT * FROM questions
                        WHERE grade=? AND subject=? AND unit=?
                        ORDER BY times_used ASC, RANDOM() LIMIT ?"""
                    params = [grade, subject, unit, num_questions]

                async with db.execute(query, params) as cursor:
                    rows = await cursor.fetchall()

            questions = [self._row_to_question(r) for r in rows]
        except Exception as e:
            print(f"[QuestionBank] Database query failed: {e}")
            # Continue with empty questions list, will generate below

        if len(questions) < num_questions:
            difficulty_cycle = ["基本", "応用", "発展", "基本", "応用"]
            for i in range(num_questions - len(questions)):
                diff = difficulty_cycle[i % len(difficulty_cycle)]
                try:
                    q = await self.generate_question(grade, subject, unit, diff, style)
                    questions.append(q)
                except Exception as e:
                    print(f"[QuestionBank] Question generation failed: {e}")
                    # Create a minimal fallback question
                    q = Question(
                        id=Question.make_id(f"{unit}_{i}_{diff}"),
                        source_style=style,
                        grade=grade,
                        subject=subject,
                        unit=unit,
                        question_text=f"{unit}の{diff}問題: 基本的な問題を解いてください。",
                        correct_answer="解答を確認してください",
                        explanation="この問題は基本概念の確認です。",
                        difficulty_b=0.0,
                        discrimination_a=1.0,
                        question_type="記述",
                        cognitive_level=2,
                        nakatsu_style=(style == "nakatsu"),
                        pisa_style=(style == "pisa"),
                    )
                    questions.append(q)

        # Update usage counts (best effort)
        try:
            async with aiosqlite.connect(self.DB_PATH) as db:
                for q in questions:
                    await db.execute(
                        "UPDATE questions SET times_used=times_used+1 WHERE id=?", (q.id,)
                    )
                await db.commit()
        except Exception as e:
            print(f"[QuestionBank] Failed to update usage counts: {e}")

        return questions[:num_questions]

    async def _generate_fallback_questions(
        self,
        grade: int,
        subject: str,
        unit: str,
        num_questions: int,
        style: str,
    ) -> list:
        """Generate questions without database caching (fallback mode)."""
        questions = []
        difficulty_cycle = ["基本", "応用", "発展", "基本", "応用"]
        for i in range(num_questions):
            diff = difficulty_cycle[i % len(difficulty_cycle)]
            try:
                q = await self.generate_question(grade, subject, unit, diff, style)
                questions.append(q)
            except Exception as e:
                print(f"[QuestionBank] Fallback generation failed: {e}")
                q = Question(
                    id=Question.make_id(f"fallback_{unit}_{i}"),
                    source_style=style,
                    grade=grade,
                    subject=subject,
                    unit=unit,
                    question_text=f"{unit}の問題: この単元の基本を確認しましょう。",
                    correct_answer="解答を確認",
                    explanation="基本概念の確認問題です。",
                    difficulty_b=0.0,
                    discrimination_a=1.0,
                    question_type="記述",
                    cognitive_level=2,
                    nakatsu_style=(style == "nakatsu"),
                    pisa_style=(style == "pisa"),
                )
                questions.append(q)
        return questions

    def _row_to_question(self, row) -> Question:
        return Question(
            id=row[0], source_style=row[1], grade=row[2], subject=row[3],
            unit=row[4], question_text=row[5], correct_answer=row[6],
            explanation=row[7], difficulty_b=row[8], discrimination_a=row[9],
            question_type=row[10], cognitive_level=row[11],
            nakatsu_style=bool(row[12]), pisa_style=bool(row[13]), times_used=row[14]
        )
