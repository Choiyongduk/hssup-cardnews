"""사진 + 사용자가 보낸 설명을 바탕으로 인스타그램 캡션을 작성합니다 (Claude Vision 사용)."""
from __future__ import annotations

import base64
import os
from pathlib import Path

from anthropic import Anthropic

DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM_TEMPLATE = """당신은 {topic} 인스타그램 계정의 캡션 작가입니다. 아래 원칙을 반드시 지키세요.
- 사진을 직접 보고, 사용자가 함께 보낸 설명을 참고해서 자연스러운 인스타그램 캡션을 작성하세요.
- 사용자가 보낸 설명에 없는 사실을 지어내지 마세요.
- 효과를 보장하거나 과장하는 표현, 의료 효과를 단정하는 표현은 쓰지 마세요.
- 한자를 쓰지 마세요. 가운뎃점(·)으로 단어를 나열하는 상투적인 문구도 쓰지 마세요.
- 존댓말, 친근하면서도 전문적인 톤으로 작성하세요.
- 이모지는 과하지 않게 1~3개만 사용하세요."""


def write_caption(
    image_path: Path,
    user_text: str,
    topic: str,
    hashtags: list[str] | None = None,
    model: str | None = None,
) -> str:
    """이미지 1장을 보고 인스타그램 캡션을 작성합니다."""
    client = Anthropic()
    media_type = "image/jpeg" if image_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    image_b64 = base64.standard_b64encode(image_path.read_bytes()).decode()

    user_content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
        {
            "type": "text",
            "text": f"사용자가 보낸 설명: {user_text or '(없음)'}\n\n이 사진에 어울리는 인스타그램 캡션을 작성해주세요.",
        },
    ]

    resp = client.messages.create(
        model=model or os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
        max_tokens=1024,
        system=SYSTEM_TEMPLATE.format(topic=topic),
        messages=[{"role": "user", "content": user_content}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text").strip()

    if hashtags:
        text += "\n\n" + " ".join(f"#{h.lstrip('#')}" for h in hashtags)
    return text
