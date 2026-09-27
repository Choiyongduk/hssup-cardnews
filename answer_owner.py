"""사용법: python answer_owner.py

원장이 AI 오피스에서 리포트에 남긴 피드백을 읽고, 담당 직원이 답합니다.
"이건 15초로 줄여줘" 같은 요청이면 고친 안을 답변에 담습니다.

자동화가 주기적으로 돌면서 아직 답하지 않은 메시지만 처리합니다.
"""
from __future__ import annotations

import os
import sys

from anthropic import Anthropic

from engine import trends_sync
from engine.config import ROOT  # noqa: F401  (.env 를 읽어 환경변수를 채웁니다)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_MODEL = "claude-sonnet-5"

ROLE_BY_KIND = {
    "plan": "콘텐츠 기획자",
    "feed": "피드 분석가",
    "staff": "직원 관리 담당",
}

SYSTEM = """당신은 히썹 반영구 아카데미의 {role}입니다.
당신이 올린 아래 결과물을 보고 원장님이 피드백을 남겼습니다. 그 피드백에 답하세요.

원칙:
- 원장님이 고쳐달라고 하면 **고친 결과물을 답변 안에 직접 담으세요.** "수정하겠습니다"라고만 하지 마세요.
- 원래 결과물에 쓴 근거를 유지하세요. 새 숫자를 지어내지 마세요.
- 원장님 의견이 데이터와 어긋나면, 따르되 무엇이 우려되는지 한 줄로 알려주세요. 반박하지는 마세요.
- 짧게 쓰세요. 고친 부분만 보여주면 되고, 안 바뀐 부분을 통째로 다시 쓰지 마세요.
- 질문이면 아는 범위에서 답하고, 자료가 없으면 없다고 하세요.
- 명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요. 한자를 쓰지 마세요.

[당신이 올린 결과물]
{report}"""


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
            {"role": "assistant" if t["role"] == "staff" else "user", "content": t["body"]}
            for t in thread
        ]
        if not messages or messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": msg["body"]})

        try:
            resp = client.messages.create(
                model=model,
                max_tokens=4000,
                system=SYSTEM.format(role=role, report=report.get("body", "")),
                messages=messages,
            )
            answer = "".join(b.text for b in resp.content if b.type == "text").strip()
            if not answer:
                raise RuntimeError(f"답변이 비어 있습니다 (stop_reason={resp.stop_reason})")
        except Exception as e:
            print(f"  ! 답변 생성 실패(report {report_id}): {e}")
            continue

        trends_sync.create_message(report_id, "staff", answer)
        trends_sync.mark_answered(msg["id"])
        print(f"  - {role}가 답변함 (report {report_id})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
