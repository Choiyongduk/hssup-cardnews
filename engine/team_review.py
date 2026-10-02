"""시안이 원장님께 가기 전에 팀이 먼저 봅니다 (내부 검수).

각자 따로 일하고 끝내면, 원장님이 오타나 어긋난 데를 직접 찾아 고쳐 달라고 해야 합니다.
그래서 시안을 올리기 전에 두 사람이 봅니다.

  박서준(기획)  요청한 의도와 맞나, 메시지가 한눈에 들어오나, 제목이 잘 보이나
  김주훈(편집)  그림 속 글자와 캡션에 오타는 없나, 둘이 서로 맞나, 지어낸 사실은 없나

고칠 게 있으면 그 자리에서 고칩니다. 캡션은 김주훈이 바로 고치고, 그림은 차은우(디자인)가
한 번 다시 그립니다. **한 바퀴만** 돕니다. 서로 계속 고치다 끝나지 않으면 안 되니까요.

주고받은 말은 시안 대화창에 그대로 남아 원장님이 볼 수 있습니다.
"""
from __future__ import annotations

import os

from . import llm
from .voice import HSSUP_VOICE

DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM = """당신들은 히썹 인스타그램 팀입니다. 원장님께 시안을 올리기 직전, 두 사람이 먼저 봅니다.

[박서준 팀장 — 기획]
- 원장님이 요청한 의도와 맞는가, 보는 사람에게 메시지가 한눈에 들어오는가
- 제목이 잘 보이는가, 가장 중요한 말이 가장 크게 보이는가
- 고쳐야 할 게 있으면 `fix` 에 디자이너에게 넘길 지시를 구체적으로. 사진 위 글씨만 바꾸면 되면 `headline` 에 새 글씨.

[김주훈 팀장 — 편집]
- 그림 속 글자와 캡션에 맞춤법이나 오타가 없는가
- 그림과 캡션의 내용이 서로 맞는가 (숫자, 날짜, 이름이 다르면 안 됨)
- 자료에 없는 사실을 지어내지 않았는가
- 캡션을 고쳐야 하면 `caption` 에 고친 전문을. 말투는 아래 기준을 지키세요.

규칙:
- **진짜 문제만** 짚으세요. 취향 차이나 "더 좋아질 수도" 수준이면 `ok` 로 넘기세요.
  괜히 고치면 원장님 시간만 늦어집니다.
- `comment` 는 동료에게 말하듯 한두 줄. 문제가 없으면 짧게 "좋아요, 이대로 올려요" 같은 확인.
- 한자를 쓰지 마세요. 명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요.

[캡션 말투 기준]
{voice}"""

TOOL = {
    "name": "review",
    "description": "시안을 보고 두 사람의 판단을 냅니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "planner": {
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "comment": {"type": "string", "description": "박서준 팀장이 하는 말 한두 줄"},
                    "fix": {"type": "string", "description": "디자이너에게 넘길 고칠 점. 없으면 빈 문자열"},
                    "headline": {"type": "string", "description": "사진 위 글씨만 바꾸면 될 때 새 글씨. 아니면 빈 문자열"},
                },
                "required": ["ok", "comment"],
            },
            "editor": {
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "comment": {"type": "string", "description": "김주훈 팀장이 하는 말 한두 줄"},
                    "caption": {"type": "string", "description": "고친 캡션 전문. 안 고치면 빈 문자열"},
                },
                "required": ["ok", "comment"],
            },
        },
        "required": ["planner", "editor"],
    },
}


def review(images: list[dict], caption: str, request: str, kind: str, headline: str = "") -> dict:
    """시안 그림(images: 그림 조각들)과 캡션을 보고 두 사람의 판단을 돌려줍니다.

    돌려주는 값: {"planner": {...}, "editor": {...}}. 실패하면 예외 — 부른 쪽에서 건너뜁니다.
    """
    content = [
        {"type": "text", "text": f"[시안 종류] {kind}"},
        {"type": "text", "text": f"[원장님 요청 / 설명]\n{request or '(따로 없음)'}"},
    ]
    if headline:
        content.append({"type": "text", "text": f"[사진 위 글씨] {headline}"})
    content += [{"type": "text", "text": f"[시안 그림 {len(images)}장]"}, *images]
    content.append({"type": "text", "text": f"[캡션]\n{caption}"})
    content.append({"type": "text", "text": "`review` 도구로 두 사람의 판단을 내 주세요."})

    resp = llm.client().messages.create(
        model=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
        max_tokens=4000,
        system=SYSTEM.format(voice=HSSUP_VOICE),
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "review"},
        messages=[{"role": "user", "content": content}],
    )
    call = next((b for b in resp.content if b.type == "tool_use"), None)
    if not call:
        raise RuntimeError(f"검수 결과가 비어 있습니다 (stop_reason={resp.stop_reason})")
    out = call.input
    planner, editor = out.get("planner") or {}, out.get("editor") or {}
    # 가운뎃점 나열은 쓰지 않기로 했다. 그래도 섞여 나오면 쉼표로 바꾼다(말에만, 캡션은 그대로).
    for who in (planner, editor):
        if who.get("comment"):
            who["comment"] = who["comment"].replace("·", ", ")
    return {
        "planner": {
            "ok": bool(planner.get("ok", True)),
            "comment": (planner.get("comment") or "").strip(),
            "fix": (planner.get("fix") or "").strip(),
            "headline": (planner.get("headline") or "").strip(),
        },
        "editor": {
            "ok": bool(editor.get("ok", True)),
            "comment": (editor.get("comment") or "").strip(),
            "caption": (editor.get("caption") or "").strip(),
        },
    }
