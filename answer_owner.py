"""사용법: python answer_owner.py

원장이 AI 오피스에서 리포트에 남긴 피드백을 읽고, 담당 직원이 답합니다.
고쳐달라는 요청이면 채팅으로 답만 하는 게 아니라 **리포트 본문을 다시 써서 올립니다.**
(제안만 하고 끝나면 소용이 없기 때문입니다.)

대화할 때 동료들이 최근에 낸 리포트도 함께 읽습니다. 자기 리포트 한 장만 보면
"지난주 대비 어때?" 같은 질문에 답할 수가 없습니다.

자동화가 주기적으로 돌면서 아직 답하지 않은 메시지만 처리합니다.
"""
from __future__ import annotations

import os
import sys

from anthropic import Anthropic

from engine import attachments, trends_sync
from engine.config import ROOT  # noqa: F401  (.env 를 읽어 환경변수를 채웁니다)
from engine.voice import HSSUP_VOICE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_MODEL = "claude-sonnet-5"

ROLE_BY_KIND = {
    "plan": "콘텐츠 기획자",
    "feed": "피드 분석가",
    "staff": "직원 관리 담당",
}

SYSTEM = """당신은 히썹 반영구 아카데미의 {role}입니다.
당신이 올린 결과물을 보고 원장님이 피드백을 남겼습니다.

판단할 것 — 원장님이 **결과물을 고쳐달라는 것인지**, 그냥 묻거나 의견을 말한 것인지.
- 고쳐달라는 것이면 `revised_report` 에 **고친 결과물 전문**을 담으세요. 일부만 보내지 말고 전체를 다시 쓰세요.
- 질문이나 잡담이면 `reply` 만 쓰고 `revised_report` 는 비워두세요.

`reply` 작성 원칙:
- 고쳤으면 무엇을 어떻게 바꿨는지 두세 줄로만 알리세요. 고친 내용 전체를 채팅에 또 쓰지 마세요.
- 원장님 의견이 데이터와 어긋나면 따르되, 우려되는 점을 한 줄로 알려주세요. 반박하지는 마세요.
- 자료가 없어 모르면 모른다고 하세요. 숫자를 지어내지 마세요.
- 짧게 쓰세요.

`revised_report` 작성 원칙:
- 원래 형식과 구조를 유지하세요. 원래 근거로 쓴 숫자를 바꾸거나 새로 지어내지 마세요.
- 원장님이 말한 부분만 고치고 나머지는 그대로 두세요.
- 캡션 초안이 들어가는 경우 아래 말투를 따르세요. 근거와 설명은 차분한 보고체로 씁니다.

원장님이 참고 사진을 보내면 직접 보고 무엇을 원하시는지 읽어내 반영하세요.

명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요. 한자를 쓰지 마세요.

{voice}

[당신이 올린 결과물]
{report}

[동료들이 최근에 낸 결과물 — 참고용]
{siblings}"""

TOOL = {
    "name": "respond",
    "description": "원장님 피드백에 대한 답변과, 필요하면 고쳐 쓴 결과물을 제출합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reply": {"type": "string", "description": "채팅으로 보낼 답변"},
            "revised_report": {
                "type": "string",
                "description": "고쳐 쓴 결과물 전문. 고칠 필요가 없으면 빈 문자열.",
            },
        },
        "required": ["reply"],
    },
}


def _siblings_text(report_id: int) -> str:
    try:
        rows = trends_sync.fetch_recent_reports(exclude_id=report_id, limit=6)
    except Exception as e:
        print(f"  ! 동료 리포트를 읽지 못했습니다: {e}")
        return "(없음)"
    if not rows:
        return "(없음)"
    return "\n\n".join(
        f"[{r['created_at'][:10]}] {r['title']}\n{(r.get('body') or '')[:1500]}" for r in rows
    )


def main() -> int:
    try:
        pending = trends_sync.fetch_unanswered_messages()
    except Exception as e:
        print(f"메시지 조회 실패: {e}")
        return 1

    if not pending:
        print("답할 메시지가 없습니다.")
        return 0

    client = Anthropic()
    model = os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL)

    for msg in pending:
        report = msg.get("ai_reports") or {}
        report_id = report.get("id")
        if not report_id:
            trends_sync.mark_answered(msg["id"])
            continue

        role = ROLE_BY_KIND.get(report.get("kind"), "담당자")
        thread = trends_sync.fetch_thread(report_id)

        messages = [
            {"role": "assistant", "content": t["body"]} if t["role"] == "staff"
            else {"role": "user", "content": attachments.owner_content(t["body"], t.get("attachments"))}
            for t in thread
        ]
        if not messages or messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": attachments.owner_content(msg["body"], msg.get("attachments"))})

        try:
            resp = client.messages.create(
                model=model,
                max_tokens=8000,
                system=SYSTEM.format(
                    role=role,
                    report=report.get("body", ""),
                    siblings=_siblings_text(report_id),
                    voice=HSSUP_VOICE,
                ),
                tools=[TOOL],
                tool_choice={"type": "tool", "name": "respond"},
                messages=messages,
            )
            tool_use = next(b for b in resp.content if b.type == "tool_use")
            answer = (tool_use.input.get("reply") or "").strip()
            revised = (tool_use.input.get("revised_report") or "").strip()
            if not answer:
                raise RuntimeError(f"답변이 비어 있습니다 (stop_reason={resp.stop_reason})")
        except Exception as e:
            print(f"  ! 답변 생성 실패(report {report_id}): {e}")
            continue

        if revised and revised != report.get("body"):
            try:
                trends_sync.update_report(report_id, revised)
                answer += "\n\n(위 내용을 반영해 결과물을 다시 올렸습니다)"
                print(f"  - {role}가 결과물을 고쳐 올림 (report {report_id})")
            except Exception as e:
                print(f"  ! 결과물 수정 실패(report {report_id}): {e}")

        trends_sync.create_message(report_id, "staff", answer)
        trends_sync.mark_answered(msg["id"])
        print(f"  - {role}가 답변함 (report {report_id})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
