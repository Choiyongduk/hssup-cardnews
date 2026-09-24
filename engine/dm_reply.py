"""받은 DM에 대한 답장 초안을 Claude로 작성합니다."""
from __future__ import annotations

import os

from anthropic import Anthropic

DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM_TEMPLATE = """당신은 {topic} 인스타그램 계정의 고객 응대 담당자입니다. 아래 원칙을 반드시 지키세요.
- 고객이 보낸 DM에 대한 답장을 작성하세요. 존댓말, 친절하고 전문적인 톤으로 작성하세요.
- 아래 참고 정보에 없는 가격·일정·효과를 지어내지 마세요. 모르는 내용은 "정확한 안내를 위해 확인 후 다시 연락드리겠습니다" 같은 문구로 대응하세요.
- 효과를 보장하거나 과장하는 표현, 의료 효과를 단정하는 표현은 쓰지 마세요.
- 한자를 쓰지 마세요.
- 너무 길지 않게 3~5문장 이내로 작성하세요. 이모지는 1개 이하로 사용하세요.

[참고 정보]
{context}"""


def write_reply(incoming_text: str, topic: str, context: str = "", model: str | None = None) -> str:
    """고객이 보낸 DM 원문을 보고 답장 초안을 작성합니다."""
    client = Anthropic()
    resp = client.messages.create(
        model=model or os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
        max_tokens=512,
        system=SYSTEM_TEMPLATE.format(topic=topic, context=context or "(별도 참고 정보 없음)"),
        messages=[{"role": "user", "content": f"고객이 보낸 DM: {incoming_text}"}],
    )
    return "".join(block.text for block in resp.content if block.type == "text").strip()
