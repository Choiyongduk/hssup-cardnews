"""사용법: python weekly_meeting.py

월요일 아침 팀 회의. 지난주 숫자를 놓고 이번 주에 뭘 할지 정합니다.

원장님이 처음에 "회의하고 결정한 내용 문서화하는 게 시간을 많이 잡아먹는다"
고 하셨습니다. 그 자리를 채웁니다.

회의록에는 결정과 맡은 사람이 남습니다. 다음 주 회의에서 지난주에 정한 걸
지켰는지 확인합니다. 정하기만 하고 아무도 안 하는 회의가 되지 않게요.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

from anthropic import Anthropic

from engine import staff, telegram, trends_sync
from engine.config import load_channel
from engine.voice import HSSUP_VOICE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KST = dt.timezone(dt.timedelta(hours=9))
DEFAULT_MODEL = "claude-haiku-4-5"  # 정리하는 일이라 가벼운 모델로 충분하다. 값이 절반

SYSTEM = """당신은 히썹 인스타그램 계정을 맡은 팀입니다. 월요일 아침 회의를 합니다.

참석자:
{roster}

아래 자료를 보고 회의록을 씁니다. **자료에 없는 숫자나 사실을 지어내지 마세요.**
자료가 부족하면 "자료 없음" 이라고 쓰고 넘어가세요.

회의록 형식(이 순서 그대로):

## 지난주
- 숫자로 3줄 이내. 무엇을 몇 건 했고 성과가 어땠는지.

## 지난주에 정한 것은 어떻게 됐나
- 지난 회의록이 있으면 그때 정한 걸 하나씩 지켰는지 적으세요.
- 지난 회의록이 없으면 이 칸은 통째로 빼세요.

## 이번 주에 할 일
- 3~4개. 각 줄 끝에 맡을 사람을 괄호로 적으세요. 예: (박서준)
- 누가 무엇을 언제까지 하는지가 보여야 합니다.
- 원장님이 해주셔야 하는 일이 있으면 (원장님) 으로 적으세요.

## 막힌 것
- 사람이 풀어줘야 넘어가는 것만. 없으면 "없습니다".

짧게 쓰세요. 한 화면에 들어와야 합니다.
명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요. 한자를 쓰지 마세요.
회의록은 기록이므로 말투 규칙을 적용하지 말고 건조하게 쓰세요.

{voice}"""


def _kst_day(value: str) -> dt.date:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(KST).date()


def gather() -> tuple[str, dict]:
    """지난주 자료를 모읍니다. 세어 온 값과 최근 리포트들입니다."""
    today = dt.datetime.now(KST).date()
    week_ago = today - dt.timedelta(days=7)

    approvals = trends_sync._get(
        "ai_approvals",
        {"select": "id,channel,status,created_at,decided_at,body", "order": "created_at.desc", "limit": "200"},
    )
    made = [a for a in approvals if _kst_day(a["created_at"]) >= week_ago]
    published = [a for a in approvals
                 if a["status"] == "approved" and a.get("decided_at") and _kst_day(a["decided_at"]) >= week_ago]
    skipped = [a for a in approvals
               if a["status"] == "skipped" and a.get("decided_at") and _kst_day(a["decided_at"]) >= week_ago]
    awaiting = [a for a in approvals if a["status"] == "awaiting"]

    counted = [
        f"- 지난 7일 동안 만든 게시물 {len(made)}건",
        f"- 그중 게시 {len(published)}건, 건너뜀 {len(skipped)}건",
        f"- 지금 승인 기다리는 것 {len(awaiting)}건",
        f"- 대기 중인 소재 {len(trends_sync.fetch_media_queue())}건",
        f"- 안 끝난 콘텐츠 요청 {len(trends_sync.fetch_requests())}건",
    ]

    parts = ["[세어 온 숫자]", *counted, ""]

    feed = trends_sync.fetch_latest_report("feed")
    if feed:
        parts += ["[가장 최근 피드 분석]", feed["body"][:2500], ""]

    plan = trends_sync.fetch_latest_report("plan")
    if plan:
        parts += ["[가장 최근 콘텐츠 기획]", plan["body"][:1500], ""]

    last_meeting = trends_sync.fetch_latest_report("meeting")
    if last_meeting:
        parts += ["[지난 회의록]", last_meeting["body"][:1500], ""]

    memo = trends_sync.fetch_context("business")
    if memo:
        parts += ["[원장님이 적어둔 사업 상황]", memo, ""]

    return "\n".join(parts), {"awaiting": awaiting, "published": published}


def main() -> int:
    material, _ = gather()

    client = Anthropic()
    resp = client.messages.create(
        model=os.environ.get("LIGHT_MODEL", DEFAULT_MODEL),
        max_tokens=3000,
        system=SYSTEM.format(roster=staff.roster_text(), voice=HSSUP_VOICE),
        messages=[{"role": "user", "content": material}],
    )
    body = "".join(b.text for b in resp.content if b.type == "text").strip()

    today = dt.datetime.now(KST)
    week_no = (today.day - 1) // 7 + 1
    title = f"{today.month}월 {week_no}주차 회의록"

    result = trends_sync.create_report(kind="meeting", title=title, body=body, period_days=7)
    print(f"{title} {result}")
    print(body)

    try:
        cfg = load_channel("hssup-academy")
        tg = cfg.get("telegram") or {}
        token = os.environ.get(tg.get("bot_token_env", ""))
        if token:
            telegram.notify(token, str(tg["chat_id"]), f"🗂 {title}\n\n{body}"[:4000])
            print("텔레그램 전송 완료")
    except Exception as e:
        print(f"  ! 텔레그램 전송 실패: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
