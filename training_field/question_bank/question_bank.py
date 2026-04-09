from __future__ import annotations
import json
import hashlib
import asyncio
import aiosqlite
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from openai import OpenAI


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
        self.client = OpenAI()
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

        style_instructions = {
            "nakatsu": """全国学力・学習状況調査のスタイルを参考に以下の原則で作成:
- 知識・技能と思考・判断・表現を一体的に問う
- 実生活場面への応用を含める
- 問題文はオリジナルで作成（既存問題の転載は絶対にしない）
- 選択肢問題か記述問題で構成""",
            "pisa": """OECDのPISA数学的リテラシー形式を参考に以下の原則で作成:
- 現実世界のコンテキスト設定（80〜120字）を冒頭に置く
- 定式化→数学的処理→解釈の3段階を意識する
- 問題文はオリジナルで作成（既存問題の転載は絶対にしない）"""
        }

        system = f"""あなたは小学{grade}年生・中学生向けの{subject}の問題作成の専門家です。

著作権に関する重要な指示:
- 既存の試験問題を転載・複製してはいけません
- 全国学力調査・PISAの出題スタイルを参考にしたオリジナル問題を作成してください

{style_instructions.get(style, style_instructions['nakatsu'])}

以下のJSON形式のみで返答（コードブロックなし）:
{{"question_text":"問題文","correct_answer":"正解","explanation":"解説","question_type":"選択|記述|複合","estimated_cognitive_level":2}}"""

        response = self.client.chat.completions.create(
            model="gpt-4o",
            max_tokens=600,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": f"単元「{unit}」の{difficulty}レベルの問題を1問作成してください。"}]
        )
        raw = response.choices[0].message.content.strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {
                "question_text": f"{unit}に関する{difficulty}問題",
                "correct_answer": "解答例",
                "explanation": "解説",
                "question_type": "記述",
                "estimated_cognitive_level": bloom_map[difficulty]
            }

        q = Question(
            id=Question.make_id(data["question_text"]),
            source_style=style,
            grade=grade,
            subject=subject,
            unit=unit,
            question_text=data["question_text"],
            correct_answer=data["correct_answer"],
            explanation=data["explanation"],
            difficulty_b=difficulty_b_map.get(difficulty, 0.0),
            discrimination_a=1.0,
            question_type=data["question_type"],
            cognitive_level=data.get("estimated_cognitive_level", bloom_map[difficulty]),
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
        await self.init_db()
        exclude_ids = exclude_ids or []

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

        if len(questions) < num_questions:
            difficulty_cycle = ["基本", "応用", "発展", "基本", "応用"]
            for i in range(num_questions - len(questions)):
                diff = difficulty_cycle[i % len(difficulty_cycle)]
                q = await self.generate_question(grade, subject, unit, diff, style)
                questions.append(q)

        async with aiosqlite.connect(self.DB_PATH) as db:
            for q in questions:
                await db.execute(
                    "UPDATE questions SET times_used=times_used+1 WHERE id=?", (q.id,)
                )
            await db.commit()

        return questions[:num_questions]

    def _row_to_question(self, row) -> Question:
        return Question(
            id=row[0], source_style=row[1], grade=row[2], subject=row[3],
            unit=row[4], question_text=row[5], correct_answer=row[6],
            explanation=row[7], difficulty_b=row[8], discrimination_a=row[9],
            question_type=row[10], cognitive_level=row[11],
            nakatsu_style=bool(row[12]), pisa_style=bool(row[13]), times_used=row[14]
        )
