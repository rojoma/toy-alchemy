"""
Toy Alchemy - 画像認識モジュール（Vision API）

子供がLINEで送った宿題の写真をGPT-4o Visionで解析し、
問題文・手書きの回答・図をテキスト化する。
"""

import base64
import logging
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger("toy-alchemy")

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

VISION_SYSTEM_PROMPT = """\
あなたは小学生の宿題を読み取る専門家です。
子供がスマホで撮影した宿題の写真から、以下の情報をテキストとして抽出してください。

【抽出ルール】
1. 問題文をそのまま書き起こす
2. 数式は平文で書く（例: 3×3×3.14 = 28.26）
3. 子供が手書きで書いた回答があれば「子供の回答:」として記載する
4. 図がある場合は「図の説明:」として何が描かれているか自然言語で説明する
5. 読み取れない文字は「（読み取り不可）」と記載する
6. 小学生の手書きなので、多少崩れた文字でも推測して読み取る

【出力形式】
問題: （読み取った問題文）
子供の回答: （あれば。なければ省略）
図の説明: （あれば。なければ省略）
備考: （特記事項があれば）
"""


def analyze_homework_image(image_bytes: bytes) -> str:
    """
    宿題の画像をGPT-4o Visionで解析し、問題文をテキスト化する。

    Args:
        image_bytes: 画像のバイナリデータ

    Returns:
        解析結果のテキスト
    """
    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    logger.info("Vision API に画像を送信中...")

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": VISION_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "この宿題の写真を読み取ってください。",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
        max_tokens=1000,
    )

    result = response.choices[0].message.content
    logger.info(f"Vision API 解析結果: {result[:100]}...")
    return result
