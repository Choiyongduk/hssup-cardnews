"""사용법: python morning_brief.py

아침에 원장님께 한 통 보냅니다.

지금까지는 전부 원장님이 앱을 열어야 돌아갔습니다. 무엇이 기다리고 있는지
들어가서 찾아봐야 했습니다. 이 스크립트는 반대로 먼저 말을 겁니다.

  어제 무슨 일이 있었는지
  오늘 원장님이 결정할 것
  그냥 두면 곤란해질 것

숫자는 지어내지 않습니다. 전부 데이터베이스에서 세어 옵니다.
마지막 한 줄만 담당자가 씁니다.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

from anthropic import Anthropic

from engine import staff, telegram, trends_sync
from engine.config import ROOT, load_channel
from engine.voice import HSSUP_VOICE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KST = dt.timezone(dt.timedelta(hours=9))
DEFAULT_MODEL = "claude-sonnet-5"

CLOSER_SYSTEM = """당신은 히썹 인스타그램 계정을 맡은 팀의 {name} 팀장입니다.
아침 보고 맨 끝에 붙일 **한 줄**을 씁니다.

아래는 오늘 아침의 사실입니다. 여기 없는 숫자나 사실을 지어내지 마세요.
가장 급한 것 하나만 짚고, 원장님이 오늘 뭘 먼저 하면 되는지 말하세요.

두 문장을 넘기지 마세요. 인사말은 빼세요.
명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요. 한자를 쓰지 마세요.

{voice}"""


def _kst_day(value: str) -> str:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(KST).strftime("%Y-%m-%d")


def gather() -> dict:
    """오늘 아침의 사실을 모읍니다. 전부 세어 온 값입니다."""
    now = dt.datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - dt.timedelta(days=1)).strftime("%Y-%m-%d")

    approvals = trends_sync._get(
        "ai_approvals",
        {"select": "id,channel,status,created_at,decided_at,body", "order": "created_at.desc", "limit": "100"},
    )
    awaiting = [a for a in approvals if a["status"] == "awaiting"]
    published = [
        a for a in approvals
        if a["status"] == "approved" and a.get("decided_at") and _kst_day(a["decided_at"]) == yesterday
    ]
    skipped = [
        a for a in approvals
        if a["status"] == "skipped" and a.get("decided_at") and _kst_day(a["decided_at"]) == yesterday
    ]

    # 가장 오래 기다린 시안이 며칠째인지
    stale_days = 0
    if awaiting:
        oldest = min(_kst_day(a["created_at"]) for a in awaiting)
        stale_days = (dt.date.fromisoformat(today) - dt.date.fromisoformat(oldest)).days

    queue = trends_sync.fetch_media_queue()
    requests_open = trends_sync.fetch_requests()

    return {
        "today": today,
        "yesterday": yesterday,
        "published": published,
        "skipped": skipped,
        "awaiting": awaiting,
        "stale_days": stale_days,
        "queue": queue,
        "requests": requests_open,
    }


def _first_line(text: str) -> str:
    return (text or "").split("\n")[0].strip()[:40] or "내용 없음"


def compose(f: dict) -> str:
    """사실만으로 본문을 만듭니다. 여기서는 한 줄도 지어내지 않습니다."""
    lines = [f"## {f['today']} 아침 보고", ""]

    lines.append("**어제**")
    if f["published"]:
        for a in f["published"]:
            lines.append(f"- 게시: {_first_line(a['body'])} ({a['channel']})")
    if f["skipped"]:
        lines.append(f"- 건너뜀 {len(f['skipped'])}건")
    if not f["published"] and not f["skipped"]:
        lines.append("- 게시한 것 없습니다")
    lines.append("")

    lines.append("**오늘 결정하실 것**")
    if f["awaiting"]:
        lines.append(f"- 시안 {len(f['awaiting'])}건이 승인을 기다립니다")
        if f["stale_days"] >= 3:
            lines.append(f"- 그중 가장 오래된 건 {f['stale_days']}일째입니다")
    else:
        lines.append("- 없습니다")
    lines.append("")

    lines.append("**앞으로**")
    if f["queue"]:
        lines.append(f"- 올려주신 소재 {len(f['queue'])}건이 처리를 기다립니다")
    else:
        lines.append("- 대기 중인 소재가 없습니다. 사진을 올려주셔야 만들 수 있습니다")
    if f["requests"]:
        lines.append(f"- 콘텐츠 요청 {len(f['requests'])}건이 아직 안 끝났습니다")

    return "\n".join(lines)


def closing_line(facts_text: str) -> str:
    """담당자가 붙이는 마지막 한 줄. 사실에서만 끌어옵니다."""
    who = staff.get("planner")
    try:
        client = Anthropic()
        resp = client.messages.create(
            model=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
            max_tokens=300,
            system=CLOSER_SYSTEM.format(name=who["name"], voice=HSSUP_VOICE),
            messages=[{"role": "user", "content": facts_text}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception as e:
        print(f"  ! 마지막 줄을 쓰지 못했습니다: {e}")
        return ""


def main() -> int:
    facts = gather()
    body = compose(facts)

    closer = closing_line(body)
    if closer:
        who = staff.get("planner")
        body += f"\n\n---\n\n**{who['name']} 팀장** — {closer}"

    result = trends_sync.create_report(
        kind="brief",
        title=f"아침 보고 ({facts['today']})",
        body=body,
    )
    print(f"아침 보고 {result}")
    print(body)

    # 텔레그램으로도 한 통. 앱을 안 열어도 눈에 띄어야 합니다.
    try:
        cfg = load_channel("hssup-academy")
        tg = cfg.get("telegram") or {}
        token = os.environ.get(tg.get("bot_token_env", ""))
        if token:
            short = body.replace("**", "").replace("## ", "")
            telegram.notify(token, str(tg["chat_id"]), f"☀️ {short}"[:4000])
            print("텔레그램 전송 완료")
    except Exception as e:
        print(f"  ! 텔레그램 전송 실패: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
