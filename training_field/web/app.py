from __future__ import annotations
import json, asyncio, uuid, datetime, os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Header, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from training_field.student_agent import StudentAgentFactory
from training_field.teacher_agent import TeacherAgent
from training_field.teacher_registry import list_teachers, load_teacher
from training_field.referee_agent import PrincipalAgent
from training_field.evaluator import Evaluator, CostTracker
from training_field.experiment_registry import ExperimentRegistry, ExperimentRecord
from training_field.question_bank.question_bank import QuestionBank
from training_field.proficiency_model import CurriculumGraph
from training_field.session_runner import PHASE_CONFIG, SessionConfig

app = FastAPI(title="Agent Training Field")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
_static_dir = Path(__file__).parent / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# ── Agent API auth ─────────────────────────────────────────────
# External agents must include `X-Field-Key: <token>` header.
# Set FIELD_API_KEY in the environment (Railway env vars). If unset, the
# agent endpoints are disabled (returns 503) so the app never accidentally
# runs unprotected in production.
def require_field_key(x_field_key: str | None = Header(default=None)):
    expected = os.environ.get("FIELD_API_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="FIELD_API_KEY not configured on server")
    if not x_field_key or x_field_key != expected:
        raise HTTPException(status_code=401, detail="invalid or missing X-Field-Key header")
    return True

@app.get("/health")
async def health():
    return {"status": "ok", "service": "training-field", "agent_api": bool(os.environ.get("FIELD_API_KEY"))}

@app.get("/skill.md")
async def serve_skill_md(request: Request):
    """Serve SKILL.md so external agents can fetch it directly via the deploy URL.
    Substitutes {{FIELD_BASE_URL}} with the actual host. {{FIELD_API_KEY}} is left
    intact — the operator distributes the key out-of-band."""
    skill_path = Path(__file__).parent.parent / "SKILL.md"
    if not skill_path.exists():
        return JSONResponse({"error": "SKILL.md not found"}, status_code=404)
    body = skill_path.read_text(encoding="utf-8")
    base_url = str(request.base_url).rstrip("/")
    body = body.replace("{{FIELD_BASE_URL}}", base_url)
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(body, media_type="text/markdown; charset=utf-8")

STUDENTS = {
    "s001": {"name":"Emma","nickname":"エマ","prof_baseline":32,"personality":"Anxious, withdrawn","color":"#3b82f6"},
    "s002": {"name":"Jake","nickname":"ジェイク","prof_baseline":40,"personality":"Impulsive, trial-and-error","color":"#f59e0b"},
    "s003": {"name":"Priya","nickname":"プリヤ","prof_baseline":52,"personality":"Methodical, patient","color":"#10b981"},
    "s004": {"name":"Dylan","nickname":"ディラン","prof_baseline":51,"personality":"Moody, topic-sensitive","color":"#8b5cf6"},
    "s005": {"name":"Chloe","nickname":"クロエ","prof_baseline":70,"personality":"Perfectionist, cautious","color":"#ec4899"},
    "s006": {"name":"Marcus","nickname":"マーカス","prof_baseline":74,"personality":"Confident, fast-moving","color":"#06b6d4"},
}

TOPICS = ["分数のかけ算・わり算","比と比の値","速さ・時間・距離","比例と反比例","円の面積","場合の数"]

# Curriculum: (grade_code, subject) -> topics. grade_code: 小1=1..小6=6, 中1=7..中3=9, 高1=10..高3=12
CURRICULUM = {
    (1, "算数"): ["10までのかず","いくつといくつ","たしざん","ひきざん","20までのかず","とけい"],
    (1, "国語"): ["ひらがな","カタカナ","かんじ","おおきなかぶ","くちばし","ものの名まえ"],
    (1, "理科"): ["がっこうたんけん","はるをさがそう","あさがおをそだてよう","むしとなかよし","あきとあそぼう","ふゆをたのしもう"],
    (1, "社会"): ["がっこうだいすき","つうがくろたんけん","こうえんであそぼう","やさいをそだてよう","まちのひとびと","かぞくとわたし"],
    (1, "英語"): ["あいさつ","アルファベット","かず","いろ","くだもの","どうぶつ"],
    (2, "算数"): ["ひょうとグラフ","たし算とひき算の筆算","長さのたんい","かけ算九九","三角形と四角形","分数のはじめ"],
    (2, "国語"): ["ふきのとう","スイミー","お手紙","漢字の読み書き","主語と述語","かん字の組み立て"],
    (2, "理科"): ["やさいをそだてよう","生きものをさがそう","まちたんけん","おもちゃランド","きせつとあそぼう","大きくなったわたし"],
    (2, "社会"): ["まちたんけん","お店のしごと","公共しせつ","はたらく人びと","むかしのくらし","わたしの成長"],
    (2, "英語"): ["あいさつ","すきなもの","かぞく","たべもの","スポーツ","天気"],
    (3, "算数"): ["かけ算","わり算","大きい数","長さと重さ","分数","三角形と角"],
    (3, "国語"): ["ちいちゃんのかげおくり","すがたをかえる大豆","ローマ字","こそあど言葉","国語辞典の使い方","ことわざ"],
    (3, "理科"): ["植物のつくり","こん虫のかんさつ","太陽とかげ","光とかがみ","じしゃくのふしぎ","電気の通り道"],
    (3, "社会"): ["わたしたちのまち","お店ではたらく人","農家のしごと","工場のしごと","火事をふせぐ","市のうつりかわり"],
    (3, "英語"): ["あいさつと自己紹介","数字1-20","色と形","好きなもの","アルファベット","動物"],
    (4, "算数"): ["大きな数","わり算の筆算","垂直と平行","がい数","小数のかけ算とわり算","分数のたし算とひき算"],
    (4, "国語"): ["ごんぎつね","白いぼうし","慣用句","漢字辞典の使い方","段落と要約","新聞をつくろう"],
    (4, "理科"): ["季節と生き物","天気と気温","月と星","電気のはたらき","水のすがた","もののあたたまり方"],
    (4, "社会"): ["わたしたちの県","水はどこから","ごみのしょり","自然災害","きょう土の伝統","県内の特色ある地いき"],
    (4, "英語"): ["曜日と月","天気","文房具","時刻","身の回りのもの","一日の生活"],
    (5, "算数"): ["整数と小数","体積","合同な図形","倍数と約数","分数のたし算とひき算","割合と百分率"],
    (5, "国語"): ["大造じいさんとガン","注文の多い料理店","敬語","古文に親しむ","意見文を書く","和語・漢語・外来語"],
    (5, "理科"): ["天気の変化","植物の発芽と成長","メダカのたんじょう","流れる水のはたらき","もののとけ方","ふりこのきまり"],
    (5, "社会"): ["日本の国土","日本の気候","農業と米づくり","水産業","工業生産","情報産業とくらし"],
    (5, "英語"): ["自己紹介","時間割","誕生日","行きたい国","道案内","一日の生活"],
    (6, "算数"): ["対称な図形","分数のかけ算とわり算","円の面積","比と比の値","速さ","比例と反比例"],
    (6, "国語"): ["やまなし","海の命","漢字の成り立ち","敬語の使い方","討論をしよう","古典を読もう"],
    (6, "理科"): ["ものの燃え方","人の体のつくり","植物の養分と水","月と太陽","土地のつくり","てこのはたらき"],
    (6, "社会"): ["日本の歴史","縄文~弥生","平安~鎌倉","江戸時代","明治維新","日本国憲法と政治"],
    (6, "英語"): ["自己紹介","夏休みの思い出","行きたい国","将来の夢","小学校の思い出","中学校生活"],
    (7, "算数"): ["正負の数","文字と式","一次方程式","比例と反比例","平面図形","空間図形"],
    (7, "国語"): ["少年の日の思い出","竹取物語","故事成語","文法（自立語）","漢字の部首","詩の鑑賞"],
    (7, "理科"): ["身近な生物の観察","植物のつくり","物質の性質","気体の性質","光と音","火山と地震"],
    (7, "社会"): ["世界の姿","世界の気候","アジア州","ヨーロッパ州","古代文明","飛鳥~平安時代"],
    (7, "英語"): ["be動詞","一般動詞","疑問詞","複数形","canの文","現在進行形"],
    (8, "算数"): ["式の計算","連立方程式","一次関数","図形の合同","三角形と四角形","確率"],
    (8, "国語"): ["走れメロス","枕草子","平家物語","文法（用言の活用）","敬語","論説文の読解"],
    (8, "理科"): ["化学変化と原子・分子","生物の体のつくり","動物の分類","電流とその利用","天気とその変化","気象観測"],
    (8, "社会"): ["日本の地域的特色","日本の諸地域","鎌倉時代","室町時代","安土桃山時代","江戸時代"],
    (8, "英語"): ["過去形","未来形（will/be going to）","助動詞","不定詞","動名詞","比較級・最上級"],
    (9, "算数"): ["式の展開と因数分解","平方根","二次方程式","関数 y=ax²","相似な図形","三平方の定理"],
    (9, "国語"): ["故郷","おくのほそ道","論語","文法のまとめ","俳句と短歌","評論文の読解"],
    (9, "理科"): ["イオンと電池","酸・アルカリと中和","遺伝の規則性","生物のふえ方","運動とエネルギー","天体の動き"],
    (9, "社会"): ["明治維新","大正デモクラシー","第二次世界大戦","現代社会","日本国憲法","国会と内閣"],
    (9, "英語"): ["受動態","現在完了","関係代名詞","間接疑問文","分詞の形容詞的用法","仮定法"],
    (10, "算数"): ["数と式","二次関数","図形と計量","データの分析","場合の数と確率","集合と命題"],
    (10, "国語"): ["評論文読解","小説読解","古文入門","漢文入門","現代文の語彙","敬語と表現"],
    (10, "理科"): ["物理基礎：運動","物理基礎：エネルギー","化学基礎：物質の構成","化学基礎：化学反応","生物基礎：細胞","地学基礎：地球"],
    (10, "社会"): ["地理総合：地図","地理総合：気候","歴史総合：近代化","歴史総合：国際秩序","公共：青年期","公共：民主政治"],
    (10, "英語"): ["5文型","時制","助動詞","受動態","不定詞・動名詞","関係詞"],
    (11, "算数"): ["三角関数","指数・対数関数","微分法","積分法","数列","ベクトル"],
    (11, "国語"): ["近代評論","近代小説","古文（源氏物語）","漢文（史記）","和歌・俳句","論述表現"],
    (11, "理科"): ["物理：力学","物理：波動","化学：理論化学","化学：無機化学","生物：代謝","地学：宇宙"],
    (11, "社会"): ["世界史：中世","世界史：近世","日本史：古代","日本史：中世","地理：産業","倫理：西洋思想"],
    (11, "英語"): ["仮定法","分詞構文","関係副詞","比較表現","話法","長文読解"],
    (12, "算数"): ["複素数平面","式と曲線","極限","微分法の応用","積分法の応用","確率分布と統計"],
    (12, "国語"): ["評論文演習","小説演習","古文演習","漢文演習","記述対策","小論文"],
    (12, "理科"): ["物理：電磁気","物理：原子","化学：有機化学","化学：高分子","生物：遺伝子","生物：生態系"],
    (12, "社会"): ["世界史：現代","日本史：近代","日本史：現代","地理：地誌","政治経済","倫理：現代思想"],
    (12, "英語"): ["長文総合読解","英作文","リスニング","語彙・イディオム","文法総合","自由英作文"],
}
GRADE_CODES = {"小1":1,"小2":2,"小3":3,"小4":4,"小5":5,"小6":6,"中1":7,"中2":8,"中3":9,"高1":10,"高2":11,"高3":12}

def topics_for(grade_code: int, subject: str) -> list[str]:
    return CURRICULUM.get((grade_code, subject)) or [f"{subject} - 単元1", f"{subject} - 単元2", f"{subject} - 単元3"]

# English translations parallel to CURRICULUM (same key order, same list order).
CURRICULUM_EN = {
    (1, "算数"): ["Numbers to 10","Number Composition","Addition","Subtraction","Numbers to 20","Telling Time"],
    (1, "国語"): ["Hiragana","Katakana","Basic Kanji","The Giant Turnip","Beaks","Names of Things"],
    (1, "理科"): ["School Exploration","Finding Spring","Growing Morning Glories","Friends with Bugs","Playing in Autumn","Enjoying Winter"],
    (1, "社会"): ["I Love School","School Route Exploration","Playing at the Park","Growing Vegetables","People in Town","Family and Me"],
    (1, "英語"): ["Greetings","Alphabet","Numbers","Colors","Fruits","Animals"],
    (2, "算数"): ["Tables and Graphs","Written Addition and Subtraction","Units of Length","Multiplication Tables","Triangles and Quadrilaterals","Introduction to Fractions"],
    (2, "国語"): ["Fukinotou","Swimmy","The Letter","Reading and Writing Kanji","Subject and Predicate","Kanji Structure"],
    (2, "理科"): ["Growing Vegetables","Searching for Living Things","Town Exploration","Toy Land","Playing with Seasons","How I Have Grown"],
    (2, "社会"): ["Town Exploration","Shop Work","Public Facilities","Working People","Life Long Ago","My Growth"],
    (2, "英語"): ["Greetings","Favorite Things","Family","Food","Sports","Weather"],
    (3, "算数"): ["Multiplication","Division","Large Numbers","Length and Weight","Fractions","Triangles and Angles"],
    (3, "国語"): ["Chiichan's Shadow Play","Soybean Transformations","Romaji","Demonstratives","Using a Dictionary","Proverbs"],
    (3, "理科"): ["Plant Structure","Observing Insects","Sun and Shadows","Light and Mirrors","Magnet Mysteries","Electric Circuits"],
    (3, "社会"): ["Our Town","Shop Workers","Farming Work","Factory Work","Fire Prevention","Changes in the City"],
    (3, "英語"): ["Greetings and Self-Introduction","Numbers 1-20","Colors and Shapes","Favorite Things","Alphabet","Animals"],
    (4, "算数"): ["Large Numbers","Long Division","Perpendicular and Parallel","Approximate Numbers","Decimal Multiplication and Division","Adding and Subtracting Fractions"],
    (4, "国語"): ["Gon the Fox","The White Cap","Idioms","Using Kanji Dictionaries","Paragraphs and Summaries","Making a Newspaper"],
    (4, "理科"): ["Seasons and Living Things","Weather and Temperature","Moon and Stars","How Electricity Works","States of Water","How Things Heat Up"],
    (4, "社会"): ["Our Prefecture","Where Water Comes From","Garbage Disposal","Natural Disasters","Local Traditions","Distinctive Areas in the Prefecture"],
    (4, "英語"): ["Days and Months","Weather","Stationery","Telling Time","Everyday Objects","Daily Life"],
    (5, "算数"): ["Integers and Decimals","Volume","Congruent Figures","Multiples and Divisors","Adding and Subtracting Fractions","Ratio and Percentage"],
    (5, "国語"): ["Old Man Ozo and the Geese","The Restaurant of Many Orders","Honorifics","Introduction to Classical Japanese","Writing Opinion Essays","Native, Sino, and Loan Words"],
    (5, "理科"): ["Weather Changes","Plant Germination and Growth","Birth of Medaka Fish","How Water Flows","How Things Dissolve","Pendulum Rules"],
    (5, "社会"): ["Japan's Land","Japan's Climate","Agriculture and Rice Farming","Fisheries","Industrial Production","Information Industry and Life"],
    (5, "英語"): ["Self-Introduction","Class Schedule","Birthdays","Countries to Visit","Giving Directions","Daily Life"],
    (6, "算数"): ["Symmetric Figures","Multiplying and Dividing Fractions","Area of Circles","Ratios","Speed","Proportion and Inverse Proportion"],
    (6, "国語"): ["Yamanashi","Life of the Sea","Origins of Kanji","Using Honorifics","Holding Debates","Reading Classics"],
    (6, "理科"): ["How Things Burn","Human Body Structure","Plant Nutrients and Water","Moon and Sun","Land Formation","How Levers Work"],
    (6, "社会"): ["Japanese History","Jomon to Yayoi","Heian to Kamakura","Edo Period","Meiji Restoration","Constitution and Politics"],
    (6, "英語"): ["Self-Introduction","Summer Memories","Countries to Visit","Future Dreams","Elementary School Memories","Junior High Life"],
    (7, "算数"): ["Positive and Negative Numbers","Letters and Expressions","Linear Equations","Proportion and Inverse Proportion","Plane Figures","Solid Figures"],
    (7, "国語"): ["Memories of Boyhood","The Tale of the Bamboo Cutter","Chinese Idioms","Grammar (Independent Words)","Kanji Radicals","Appreciating Poetry"],
    (7, "理科"): ["Observing Familiar Organisms","Plant Structure","Properties of Matter","Properties of Gases","Light and Sound","Volcanoes and Earthquakes"],
    (7, "社会"): ["The World","World Climates","Asia","Europe","Ancient Civilizations","Asuka to Heian Period"],
    (7, "英語"): ["Be Verbs","General Verbs","Question Words","Plural Forms","Can","Present Progressive"],
    (8, "算数"): ["Algebraic Expressions","Simultaneous Equations","Linear Functions","Congruence of Figures","Triangles and Quadrilaterals","Probability"],
    (8, "国語"): ["Run, Melos","The Pillow Book","The Tale of the Heike","Grammar (Conjugation)","Honorifics","Reading Argumentative Texts"],
    (8, "理科"): ["Chemical Changes and Atoms","Body Structure of Organisms","Animal Classification","Electric Currents","Weather Changes","Weather Observation"],
    (8, "社会"): ["Regional Features of Japan","Regions of Japan","Kamakura Period","Muromachi Period","Azuchi-Momoyama Period","Edo Period"],
    (8, "英語"): ["Past Tense","Future Tense","Modal Verbs","Infinitives","Gerunds","Comparatives and Superlatives"],
    (9, "算数"): ["Expansion and Factoring","Square Roots","Quadratic Equations","Function y=ax²","Similar Figures","Pythagorean Theorem"],
    (9, "国語"): ["My Old Home","The Narrow Road to the Deep North","The Analects","Grammar Review","Haiku and Tanka","Reading Critical Essays"],
    (9, "理科"): ["Ions and Batteries","Acids, Bases, and Neutralization","Laws of Heredity","Reproduction of Organisms","Motion and Energy","Movement of Celestial Bodies"],
    (9, "社会"): ["Meiji Restoration","Taisho Democracy","World War II","Modern Society","Constitution of Japan","Diet and Cabinet"],
    (9, "英語"): ["Passive Voice","Present Perfect","Relative Pronouns","Indirect Questions","Participles as Adjectives","Subjunctive Mood"],
    (10, "算数"): ["Numbers and Expressions","Quadratic Functions","Geometry and Measurement","Data Analysis","Counting and Probability","Sets and Propositions"],
    (10, "国語"): ["Reading Critical Essays","Reading Novels","Introduction to Classical Japanese","Introduction to Classical Chinese","Modern Vocabulary","Honorifics and Expression"],
    (10, "理科"): ["Physics: Motion","Physics: Energy","Chemistry: Composition of Matter","Chemistry: Chemical Reactions","Biology: Cells","Earth Science: The Earth"],
    (10, "社会"): ["Geography: Maps","Geography: Climate","History: Modernization","History: International Order","Civics: Adolescence","Civics: Democracy"],
    (10, "英語"): ["Five Sentence Patterns","Tenses","Modal Verbs","Passive Voice","Infinitives and Gerunds","Relatives"],
    (11, "算数"): ["Trigonometric Functions","Exponential and Logarithmic Functions","Differentiation","Integration","Sequences","Vectors"],
    (11, "国語"): ["Modern Critical Essays","Modern Novels","Tale of Genji","Records of the Grand Historian","Waka and Haiku","Argumentative Writing"],
    (11, "理科"): ["Physics: Mechanics","Physics: Waves","Chemistry: Theoretical","Chemistry: Inorganic","Biology: Metabolism","Earth Science: Universe"],
    (11, "社会"): ["World History: Medieval","World History: Early Modern","Japanese History: Ancient","Japanese History: Medieval","Geography: Industry","Ethics: Western Thought"],
    (11, "英語"): ["Subjunctive Mood","Participial Constructions","Relative Adverbs","Comparative Expressions","Reported Speech","Reading Long Passages"],
    (12, "算数"): ["Complex Plane","Equations and Curves","Limits","Applications of Differentiation","Applications of Integration","Probability Distributions and Statistics"],
    (12, "国語"): ["Critical Essay Practice","Novel Practice","Classical Japanese Practice","Classical Chinese Practice","Descriptive Writing","Short Essays"],
    (12, "理科"): ["Physics: Electromagnetism","Physics: Atomic","Chemistry: Organic","Chemistry: Polymers","Biology: Genes","Biology: Ecosystems"],
    (12, "社会"): ["World History: Modern","Japanese History: Modern","Japanese History: Contemporary","Geography: Regional","Politics and Economics","Ethics: Modern Thought"],
    (12, "英語"): ["Comprehensive Reading","English Composition","Listening","Vocabulary and Idioms","Comprehensive Grammar","Free Composition"],
}

# Flat ja→en topic map, generated by zipping parallel lists. Robust to colon-style mismatches.
TOPIC_TX_EN: dict[str, str] = {}
for _k, _ja_list in CURRICULUM.items():
    _en_list = CURRICULUM_EN.get(_k, [])
    for _ja, _en in zip(_ja_list, _en_list):
        TOPIC_TX_EN[_ja] = _en

# Legacy / alternate topic strings present in older registry records that don't
# match the current CURRICULUM keys. Extend this dict whenever an untranslated
# Japanese topic appears in the UI history table.
LEGACY_TOPIC_ALIASES: dict[str, str] = {
    "速さ時間距離": "Speed, Time, Distance",
    "速さ・時間・距離": "Speed, Time, Distance",
    "分数のかけ算・わり算": "Multiplication & Division of Fractions",
    "比と比の値": "Ratios and Ratio Values",
    "比例と反比例": "Proportion & Inverse Proportion",
    "場合の数": "Combinatorics",
}
for _ja, _en in LEGACY_TOPIC_ALIASES.items():
    TOPIC_TX_EN.setdefault(_ja, _en)

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    reg = ExperimentRegistry()
    summary = reg.summary()
    student_data = []
    for sid, info in STUDENTS.items():
        results = reg.query(filter_by={"student_id": sid})
        last_gain = results[0]["learning_gain"] if results else None
        student_data.append({**info, "id": sid, "sessions": len(results), "last_gain": last_gain})
    return templates.TemplateResponse(request, "dashboard.html", {
        "students": student_data,
        "summary": summary, "recent": reg.query(limit=5),
        "topic_tx_en": TOPIC_TX_EN,
    })

@app.get("/session/{student_id}", response_class=HTMLResponse)
async def session_page(request: Request, student_id: str, grade: str = "小6", subject: str = "算数"):
    info = STUDENTS.get(student_id, {})
    reg = ExperimentRegistry()
    history = reg.query(filter_by={"student_id": student_id}, limit=10)
    gcode = GRADE_CODES.get(grade, 6)
    topics = topics_for(gcode, subject)
    return templates.TemplateResponse(request, "session.html", {
        "student_id": student_id,
        "student": info, "topics": topics, "history": history,
        "grade": grade, "subject": subject, "grade_code": gcode,
        "topic_tx_en": TOPIC_TX_EN,
        "teachers": list_teachers(),
    })

@app.get("/api/teachers")
async def api_teachers():
    return {"teachers": list_teachers()}

@app.get("/api/history")
async def api_history(limit: int = 100, student_id: str | None = None):
    reg = ExperimentRegistry()
    filt = {"student_id": student_id} if student_id else None
    return {"sessions": reg.query(filter_by=filt, limit=limit)}

@app.get("/api/session/{session_id}/transcript")
async def api_transcript(session_id: str):
    path = Path(__file__).parent.parent / "reports" / f"{session_id}_transcript.json"
    if not path.exists():
        return JSONResponse({"error": "transcript not found", "session_id": session_id}, status_code=404)
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

# ── Agent API (X-Field-Key required) ─────────────────────────
# These endpoints let external "claw" agents register a teacher persona,
# run a session against a chosen student, and read the leaderboard.
# Auth: every request must include `X-Field-Key: <token>` matching FIELD_API_KEY env var.
EXTERNAL_TEACHERS_DIR = Path(__file__).parent.parent / "field" / "external_teachers"

@app.post("/api/agent/teacher/register")
async def agent_register_teacher(payload: dict, _auth: bool = Depends(require_field_key)):
    """Register a Teacher persona by submitting its declaration JSON.
    Required: teacher_id, name, origin, selected_skills.
    Returns: {teacher_id, status, summary}."""
    EXTERNAL_TEACHERS_DIR.mkdir(parents=True, exist_ok=True)
    tid = payload.get("teacher_id")
    if not tid or not isinstance(tid, str) or not tid.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="teacher_id must be alphanumeric (with _ or -)")
    if not tid.startswith("ext_"):
        raise HTTPException(status_code=400, detail="external teacher_id must start with 'ext_'")
    out_path = EXTERNAL_TEACHERS_DIR / f"{tid}.json"
    # Write then validate via the existing TeacherAgent.from_json checks
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        agent = TeacherAgent.from_json(out_path)
    except Exception as e:
        out_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"validation failed: {e}")
    summary = {
        "teacher_id": agent.config.teacher_id,
        "name": agent.config.name,
        "origin": agent.config.origin,
        "selected_skills": list(agent.config.selected_skills),
        "warmth": agent.config.warmth,
        "patience_threshold": agent.config.patience_threshold,
    }
    return {"status": "registered", "teacher": summary}

@app.post("/api/agent/session/run")
async def agent_run_session(payload: dict, _auth: bool = Depends(require_field_key)):
    """Run a session synchronously and return the result.
    Required: teacher_id, student_id (one of s001..s006), topic.
    Optional: depth (quick/standard/deep), grade ("小6" etc), subject ("算数" etc),
              run_pre_test, run_post_test, lang ("ja"/"en")."""
    required = ["teacher_id", "student_id", "topic"]
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(status_code=400, detail=f"missing: {missing}")
    if payload["student_id"] not in STUDENTS:
        raise HTTPException(status_code=400, detail=f"unknown student_id; must be one of {list(STUDENTS.keys())}")
    try:
        load_teacher(payload["teacher_id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Delegate to the existing batch handler (it already does everything)
    return await run_session(payload)

@app.get("/api/agent/leaderboard")
async def agent_leaderboard(_auth: bool = Depends(require_field_key), limit: int = 200):
    """Aggregate stats per teacher_id across all recorded sessions.
    Returns rows sorted by avg_learning_gain desc."""
    reg = ExperimentRegistry()
    rows = reg.query(limit=limit)
    by_teacher: dict[str, dict] = {}
    for r in rows:
        tid = r.get("teacher_id") or "unknown"
        slot = by_teacher.setdefault(tid, {"teacher_id": tid, "sessions": 0, "gains": [], "passes": 0, "total_zpd": 0.0})
        slot["sessions"] += 1
        if r.get("learning_gain") is not None:
            slot["gains"].append(r["learning_gain"])
        if r.get("session_grade") in ("◎", "○"):
            slot["passes"] += 1
        slot["total_zpd"] += r.get("avg_zpd_alignment") or 0
    out = []
    for tid, s in by_teacher.items():
        n = s["sessions"]
        avg_gain = round(sum(s["gains"]) / len(s["gains"]), 2) if s["gains"] else None
        pass_rate = round(s["passes"] / n, 2) if n else 0
        avg_zpd = round(s["total_zpd"] / n, 2) if n else 0
        out.append({
            "teacher_id": tid, "sessions": n,
            "avg_learning_gain": avg_gain, "pass_rate": pass_rate, "avg_zpd": avg_zpd,
        })
    out.sort(key=lambda r: (r["avg_learning_gain"] or -999), reverse=True)
    return {"leaderboard": out, "total_sessions": sum(r["sessions"] for r in out)}

@app.get("/api/agent/students")
async def agent_students(_auth: bool = Depends(require_field_key)):
    """List the platform's standard student personas (read-only)."""
    return {"students": [{"id": sid, **info} for sid, info in STUDENTS.items()]}

@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    reg = ExperimentRegistry()
    sessions = reg.query(limit=200)
    return templates.TemplateResponse(request, "history.html", {
        "sessions": sessions,
        "topic_tx_en": TOPIC_TX_EN,
    })

@app.get("/api/topics")
async def api_topics(grade: str = "小6", subject: str = "算数"):
    return {"topics": topics_for(GRADE_CODES.get(grade, 6), subject)}

@app.post("/api/run-session")
async def run_session(body: dict):
    gcode = GRADE_CODES.get(body.get("grade","小6"), 6)
    config = SessionConfig(
        student_id=body["student_id"], topic=body["topic"],
        depth=body.get("depth","quick"),
        grade=gcode, subject=body.get("subject","算数"),
        run_pre_test=body.get("run_pre_test",False),
        run_post_test=body.get("run_post_test",False),
    )
    session_id = f"sess_{uuid.uuid4().hex[:8]}"
    student = StudentAgentFactory.from_profile(config.student_id)
    teacher = load_teacher(body.get("teacher_id"))
    principal = PrincipalAgent()
    evaluator = Evaluator()
    registry = ExperimentRegistry()
    qbank = QuestionBank()
    cost_tracker = CostTracker()
    await qbank.init_db()

    initial_prof = student.proficiency_model.topic_proficiencies.get(
        config.topic, student.proficiency_model.proficiency)
    turn_evaluations = []
    turns_log = []
    pre_test_score = None
    post_test_score = None
    pre_ids = []

    if config.run_pre_test:
        qs = await qbank.get_test_questions(config.grade, config.subject, config.topic, 5)
        pre_ids = [q.id for q in qs]
        correct = sum(1 for q in qs if (await student.generate_test_answer(q.question_text, q.correct_answer, config.topic))["is_correct"])
        pre_test_score = round(correct / len(qs) * 100)

    phases = PHASE_CONFIG[config.depth]
    last_student_text = None
    for phase in phases:
        for turn_num in range(1, phase["turns"] + 1):
            current_prof = student.proficiency_model.topic_proficiencies.get(config.topic, student.proficiency_model.proficiency)
            tr = await teacher.get_response(topic=config.topic, phase=phase["name"], phase_goal=phase["goal"], student_name=student.name_ja(), student_proficiency=current_prof, student_emotional=student.emotional_state.__dict__, student_last_response=last_student_text, grade=config.grade, subject=config.subject, turn_number=turn_num)
            sr = await student.get_response(teacher_message=tr["text"], topic=config.topic, phase=phase["name"])
            ev = await principal.evaluate_turn(teacher_text=tr["text"], student_text=sr["text"], topic=config.topic, phase=phase["name"], student_proficiency=current_prof, grade=config.grade, subject=config.subject)
            turn_evaluations.append(ev)
            if ev.understanding_delta > 0:
                student.proficiency_model.update_after_session(config.topic, ev.understanding_delta * 0.3)
            last_student_text = sr["text"]
            turns_log.append({
                "phase": phase["name"], "phase_label": phase["label"], "turn": turn_num,
                "teacher": tr["text"], "student": sr["text"],
                "zpd": round(ev.zpd_alignment,2), "bloom": ev.bloom_level,
                "scaffolding": round(ev.scaffolding_quality,2),
                "halluc": ev.hallucination_detected, "direct": ev.answer_given_directly,
                "delta": round(ev.understanding_delta,1),
                "directive": ev.directive_to_teacher, "summary": ev.summary,
                "prof_after": round(student.proficiency_model.topic_proficiencies.get(config.topic,0),1),
            })

    if config.run_post_test:
        qs = await qbank.get_test_questions(config.grade, config.subject, config.topic, 5, exclude_ids=pre_ids)
        correct = sum(1 for q in qs if (await student.generate_test_answer(q.question_text, q.correct_answer, config.topic))["is_correct"])
        post_test_score = round(correct / len(qs) * 100)

    final_prof = student.proficiency_model.topic_proficiencies.get(config.topic, 0)
    update_check = principal.check_skills_update_trigger()
    proposal_path = None
    if update_check.get("trigger"):
        ctx = {"session_id": session_id, "student_id": config.student_id, "teacher_id": teacher.config.teacher_id,
               "topic": config.topic, "selected_skills": teacher.config.selected_skills}
        proposal = principal.generate_skills_proposal(update_check, ctx)
        proposal_path = str(principal.write_proposal(proposal, update_check, ctx))
    grade_result = principal.grade_session(post_test_score or 0)
    evaluation = evaluator.evaluate(session_id=session_id, turn_evaluations=turn_evaluations, pre_score=pre_test_score, post_score=post_test_score, student_id=config.student_id, teacher_id=teacher.config.teacher_id, topic=config.topic, grade=config.grade, subject=config.subject, depth=config.depth, initial_proficiency=initial_prof, final_proficiency=final_prof, cost_tracker=cost_tracker, principal_update_check=update_check)
    evaluator.generate_report(evaluation)
    record = ExperimentRecord(exp_id=session_id, hypothesis_id=None, timestamp=datetime.datetime.now().isoformat(), student_id=config.student_id, teacher_id=teacher.config.teacher_id, topic=config.topic, grade=config.grade, subject=config.subject, depth=config.depth, teaching_style="SOCRATIC", skills_used=teacher.config.selected_skills, pre_test_score=pre_test_score, post_test_score=post_test_score, learning_gain=evaluation.learning_gain, proficiency_delta=evaluation.proficiency_delta, hallucination_rate=evaluation.hallucination_rate, direct_answer_rate=evaluation.direct_answer_rate, avg_zpd_alignment=evaluation.avg_zpd_alignment, avg_bloom_level=evaluation.avg_bloom_level, frustration_events=evaluation.frustration_events, aha_moments=evaluation.aha_moments, teacher_compatibility_score=evaluation.teacher_compatibility_score, total_tokens=evaluation.total_tokens_used, cost_usd=evaluation.estimated_cost_usd, session_grade=grade_result["grade"])
    registry.register(record)
    transcript = {
        "session_id": session_id, "timestamp": record.timestamp,
        "student_id": config.student_id, "teacher_id": teacher.config.teacher_id,
        "teacher_name": teacher.config.name, "topic": config.topic,
        "grade": config.grade, "subject": config.subject, "depth": config.depth,
        "pre_test_score": pre_test_score, "post_test_score": post_test_score,
        "session_grade": grade_result, "turns": turns_log,
    }
    transcript_path = Path(__file__).parent.parent / "reports" / f"{session_id}_transcript.json"
    transcript_path.parent.mkdir(exist_ok=True)
    transcript_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")

    return JSONResponse({
        "session_id": session_id, "turns": turns_log,
        "pre_test_score": pre_test_score, "post_test_score": post_test_score,
        "learning_gain": evaluation.learning_gain,
        "initial_proficiency": round(initial_prof,1), "final_proficiency": round(final_prof,1),
        "avg_zpd": evaluation.avg_zpd_alignment, "avg_bloom": evaluation.avg_bloom_level,
        "hallucination_rate": evaluation.hallucination_rate,
        "direct_answer_rate": evaluation.direct_answer_rate,
        "skills_update_needed": evaluation.skills_update_needed,
        "session_grade": grade_result, "update_check": update_check,
        "skills_proposal_path": proposal_path,
    })

from fastapi.responses import StreamingResponse
import asyncio

@app.get("/api/run-session-stream")
async def run_session_stream(
    student_id: str, topic: str, depth: str = "quick",
    grade: str = "小6", subject: str = "算数",
    pre_test: bool = False, post_test: bool = False,
    teacher_id: str = "t001",
    lang: str = "ja",
):
    async def event_generator():
        import json
        session_id = f"sess_{uuid.uuid4().hex[:8]}"
        gcode = GRADE_CODES.get(grade, 6)
        config = SessionConfig(
            student_id=student_id, topic=topic, depth=depth,
            grade=gcode, subject=subject,
            run_pre_test=pre_test, run_post_test=post_test,
        )
        student = StudentAgentFactory.from_profile(config.student_id)
        teacher = load_teacher(teacher_id)
        principal = PrincipalAgent()
        evaluator = Evaluator()
        registry = ExperimentRegistry()
        cost_tracker = CostTracker()
        qbank = QuestionBank()
        await qbank.init_db()
        initial_prof = student.proficiency_model.topic_proficiencies.get(
            config.topic, student.proficiency_model.proficiency)
        turn_evaluations = []
        turns_log = []
        pre_test_score = None; post_test_score = None; pre_ids = []
        if pre_test:
            yield f"data: {json.dumps({'type':'test_phase','which':'pre'})}\n\n"
            await asyncio.sleep(0)
            qs = await qbank.get_test_questions(config.grade, config.subject, config.topic, 5)
            pre_ids = [q.id for q in qs]
            correct = 0
            for i,q in enumerate(qs,1):
                ans = await student.generate_test_answer(q.question_text, q.correct_answer, config.topic, lang=lang)
                if ans["is_correct"]: correct += 1
                yield f"data: {json.dumps({'type':'test_q','which':'pre','i':i,'n':len(qs),'correct':ans['is_correct']})}\n\n"
                await asyncio.sleep(0)
            pre_test_score = round(correct/len(qs)*100)
            yield f"data: {json.dumps({'type':'test_score','which':'pre','score':pre_test_score})}\n\n"
        phases = PHASE_CONFIG[config.depth]
        last_student_text = None
        total = sum(p["turns"] for p in phases)
        done = 0
        for phase in phases:
            yield f"data: {json.dumps({'type':'phase','phase':phase['name'],'label':phase['label'],'goal':phase['goal']})}\n\n"
            await asyncio.sleep(0)
            for turn_num in range(1, phase["turns"] + 1):
                current_prof = student.proficiency_model.topic_proficiencies.get(
                    topic, student.proficiency_model.proficiency)
                tr = await teacher.get_response(
                    topic=topic, phase=phase["name"], phase_goal=phase["goal"],
                    student_name=student.name_ja(), student_proficiency=current_prof,
                    student_emotional=student.emotional_state.__dict__,
                    student_last_response=last_student_text,
                    grade=config.grade, subject=config.subject, turn_number=turn_num,
                    lang=lang,
                )
                yield f"data: {json.dumps({'type':'teacher','text':tr['text'],'turn':turn_num,'total':total})}\n\n"
                await asyncio.sleep(0.3)
                sr = await student.get_response(
                    teacher_message=tr["text"], topic=topic, phase=phase["name"], lang=lang,
                )
                yield f"data: {json.dumps({'type':'student','text':sr['text']})}\n\n"
                await asyncio.sleep(0.3)
                ev = await principal.evaluate_turn(
                    teacher_text=tr["text"], student_text=sr["text"],
                    topic=topic, phase=phase["name"],
                    student_proficiency=current_prof,
                    grade=config.grade, subject=config.subject,
                    lang=lang,
                )
                turn_evaluations.append(ev)
                turns_log.append({
                    "phase": phase["name"], "phase_label": phase["label"], "turn": turn_num,
                    "teacher": tr["text"], "student": sr["text"],
                    "zpd": round(ev.zpd_alignment, 2), "bloom": ev.bloom_level,
                    "scaffolding": round(ev.scaffolding_quality, 2),
                    "halluc": ev.hallucination_detected, "direct": ev.answer_given_directly,
                    "delta": round(ev.understanding_delta, 1),
                    "directive": ev.directive_to_teacher, "summary": ev.summary,
                    "prof_after": round(student.proficiency_model.topic_proficiencies.get(config.topic, 0), 1),
                })
                if ev.understanding_delta > 0:
                    student.proficiency_model.update_after_session(
                        topic, ev.understanding_delta * 0.3)
                last_student_text = sr["text"]
                done += 1
                yield f"data: {json.dumps({'type':'referee','zpd':round(ev.zpd_alignment,2),'bloom':ev.bloom_level,'scaffolding':round(ev.scaffolding_quality,2),'halluc':ev.hallucination_detected,'direct':ev.answer_given_directly,'delta':round(ev.understanding_delta,1),'directive':ev.directive_to_teacher,'summary':ev.summary,'progress':round(done/total*100)})}\n\n"
                await asyncio.sleep(0.2)
        if post_test:
            yield f"data: {json.dumps({'type':'test_phase','which':'post'})}\n\n"
            await asyncio.sleep(0)
            qs = await qbank.get_test_questions(config.grade, config.subject, config.topic, 5, exclude_ids=pre_ids)
            correct = 0
            for i,q in enumerate(qs,1):
                ans = await student.generate_test_answer(q.question_text, q.correct_answer, config.topic, lang=lang)
                if ans["is_correct"]: correct += 1
                yield f"data: {json.dumps({'type':'test_q','which':'post','i':i,'n':len(qs),'correct':ans['is_correct']})}\n\n"
                await asyncio.sleep(0)
            post_test_score = round(correct/len(qs)*100)
            yield f"data: {json.dumps({'type':'test_score','which':'post','score':post_test_score})}\n\n"
        final_prof = student.proficiency_model.topic_proficiencies.get(topic, 0)
        grade_result = principal.grade_session(post_test_score or 0) if post_test else None
        # Skills semi-auto: generate proposal if trigger fires
        update_check = principal.check_skills_update_trigger()
        proposal_path = None
        if update_check.get("trigger"):
            ctx = {"session_id": session_id, "student_id": student_id, "teacher_id": teacher.config.teacher_id,
                   "topic": topic, "selected_skills": teacher.config.selected_skills}
            prop = principal.generate_skills_proposal(update_check, ctx)
            proposal_path = str(principal.write_proposal(prop, update_check, ctx))
            yield f"data: {json.dumps({'type':'proposal','severity':prop.get('severity'),'target_skill':prop.get('target_skill'),'rationale':prop.get('rationale'),'path':proposal_path})}\n\n"
            await asyncio.sleep(0)

        # ── Persist session (mirror batch path) ────────────────────
        try:
            evaluation = evaluator.evaluate(
                session_id=session_id, turn_evaluations=turn_evaluations,
                pre_score=pre_test_score, post_score=post_test_score,
                student_id=config.student_id, teacher_id=teacher.config.teacher_id,
                topic=config.topic, grade=config.grade, subject=config.subject,
                depth=config.depth, initial_proficiency=initial_prof,
                final_proficiency=final_prof, cost_tracker=cost_tracker,
                principal_update_check=update_check,
            )
            evaluator.generate_report(evaluation)
            record = ExperimentRecord(
                exp_id=session_id, hypothesis_id=None,
                timestamp=datetime.datetime.now().isoformat(),
                student_id=config.student_id, teacher_id=teacher.config.teacher_id,
                topic=config.topic, grade=config.grade, subject=config.subject,
                depth=config.depth, teaching_style="SOCRATIC",
                skills_used=teacher.config.selected_skills,
                pre_test_score=pre_test_score, post_test_score=post_test_score,
                learning_gain=evaluation.learning_gain,
                proficiency_delta=evaluation.proficiency_delta,
                hallucination_rate=evaluation.hallucination_rate,
                direct_answer_rate=evaluation.direct_answer_rate,
                avg_zpd_alignment=evaluation.avg_zpd_alignment,
                avg_bloom_level=evaluation.avg_bloom_level,
                frustration_events=evaluation.frustration_events,
                aha_moments=evaluation.aha_moments,
                teacher_compatibility_score=evaluation.teacher_compatibility_score,
                total_tokens=evaluation.total_tokens_used,
                cost_usd=evaluation.estimated_cost_usd,
                session_grade=(grade_result or {}).get("grade", "—"),
            )
            registry.register(record)
            # Save full transcript for the history viewer (turn-by-turn replay)
            transcript = {
                "session_id": session_id,
                "timestamp": record.timestamp,
                "student_id": config.student_id,
                "teacher_id": teacher.config.teacher_id,
                "teacher_name": teacher.config.name,
                "topic": config.topic, "grade": grade, "subject": config.subject,
                "depth": config.depth, "lang": lang,
                "pre_test_score": pre_test_score, "post_test_score": post_test_score,
                "session_grade": grade_result,
                "turns": turns_log,
            }
            transcript_path = Path(__file__).parent.parent / "reports" / f"{session_id}_transcript.json"
            transcript_path.parent.mkdir(exist_ok=True)
            transcript_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[stream-persist] failed to save session {session_id}: {e}")

        yield f"data: {json.dumps({'type':'done','session_id':session_id,'final_proficiency':round(final_prof,1),'pre_test_score':pre_test_score,'post_test_score':post_test_score,'session_grade':grade_result,'skills_proposal_path':proposal_path})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )