"""사진 + 사용자가 보낸 설명을 바탕으로 인스타그램 캡션을 작성합니다 (Claude Vision 사용)."""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path

from anthropic import Anthropic
from PIL import Image

DEFAULT_MODEL = "claude-sonnet-5"
MAX_EDGE = 1568  # Claude 권장 최대 변 길이 (그 이상은 어차피 다운스케일됨)


def _normalize_image(image_path: Path) -> tuple[bytes, str]:
    """색상 프로파일(CMYK 등)·포맷 문제로 API가 거부하는 걸 막기 위해
    표준 sRGB JPEG로 다시 인코딩합니다. (image_bytes, media_type) 반환."""
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        if max(im.size) > MAX_EDGE:
            im.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=90)
        return buf.getvalue(), "image/jpeg"

SYSTEM_TEMPLATE = """당신은 {topic} 인스타그램 계정의 캡션·이미지 헤드라인 작가입니다. 아래 원칙을 반드시 지키세요.
- 사진을 직접 보고, 사용자가 함께 보낸 설명을 참고해서 자연스러운 인스타그램 캡션과 이미지용 헤드라인을 작성하세요.
- 사용자가 보낸 설명에 없는 사실을 지어내지 마세요.
- 효과를 보장하거나 과장하는 표현, 의료 효과를 단정하는 표현은 쓰지 마세요.
- 한자를 쓰지 마세요. 가운뎃점(·)으로 단어를 나열하는 상투적인 문구도 쓰지 마세요.
- 캡션은 존댓말, 친근하면서도 전문적인 톤으로 작성하세요. 이모지는 과하지 않게 1~3개만 사용하세요.
- 캡션에 해시태그는 쓰지 마세요. 채널 고정 해시태그가 캡션 뒤에 자동으로 붙습니다.
- 헤드라인은 사진 위에 큰 글씨로 얹을 짧은 문구입니다. 2~6단어(한글 기준 12자 내외), 시술명·상품명·핵심 포인트를 화보 캡션처럼 임팩트 있게 뽑으세요 (예: "4H 리커버브로우", "탠저린 컬러 팝"). 완전한 문장이나 존댓말체로 쓰지 마세요."""


def write_post(
    image_path: Path,
    user_text: str,
    topic: str,
    hashtags: list[str] | None = None,
    model: str | None = None,
) -> dict:
    """이미지 1장을 보고 {"headline": ..., "caption": ...}을 작성합니다."""
    client = Anthropic()
    image_bytes, media_type = _normalize_image(image_path)
    image_b64 = base64.standard_b64encode(image_bytes).decode()

    user_content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
        {
            "type": "text",
            "text": f"사용자가 보낸 설명: {user_text or '(없음)'}\n\n이 사진에 어울리는 헤드라인과 인스타그램 캡션을 작성해주세요.",
        },
    ]

    resp = client.messages.create(
        model=model or os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
        max_tokens=1024,
        system=SYSTEM_TEMPLATE.format(topic=topic),
        tools=[
            {
                "name": "write_post",
                "description": "이미지 헤드라인과 인스타그램 캡션을 제출합니다.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "headline": {"type": "string", "description": "사진 위에 올릴 짧은 헤드라인 (2~6단어)"},
                        "caption": {"type": "string", "description": "인스타그램 게시글 본문 캡션 (해시태그 제외)"},
                    },
                    "required": ["headline", "caption"],
                },
            }
        ],
        tool_choice={"type": "tool", "name": "write_post"},
        messages=[{"role": "user", "content": user_content}],
    )
    tool_use = next(b for b in resp.content if b.type == "tool_use")
    headline = tool_use.input["headline"].strip()
    caption = tool_use.input["caption"].strip()

    if hashtags:
        caption += "\n\n" + " ".join(f"#{h.lstrip('#')}" for h in hashtags)
    return {"headline": headline, "caption": caption}
