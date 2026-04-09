from __future__ import annotations
import json
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

CACHE_PATH = Path(__file__).parent / "translation_cache.json"

def load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}

def save_cache(cache: dict):
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

def translate_texts(texts: list[str]) -> dict[str, str]:
    """未翻訳のテキストをOpenAIで一括翻訳してキャッシュに追加"""
    cache = load_cache()
    missing = [t for t in texts if t not in cache and t.strip()]
    if not missing:
        return cache

    client = OpenAI()
    prompt = """以下の日本語テキストを英語に翻訳してください。
UIラベルとして使用します。簡潔に翻訳してください。
JSON形式で返してください。キーは元の日本語、値は英訳です。

テキスト:
""" + "\n".join(f"- {t}" for t in missing)

    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=1000,
        messages=[
            {"role": "system", "content": "You are a translator. Return only valid JSON, no markdown."},
            {"role": "user", "content": prompt}
        ]
    )
    raw = response.choices[0].message.content.strip()
    try:
        new_translations = json.loads(raw)
        cache.update(new_translations)
        save_cache(cache)
        print(f"Translated {len(new_translations)} new texts")
    except json.JSONDecodeError:
        print("Translation parse error:", raw[:200])

    return cache

def get_all_translations() -> dict:
    return load_cache()