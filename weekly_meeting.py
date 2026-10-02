"""사용법: python weekly_meeting.py

월요일 아침 팀 회의. 지난주 숫자를 놓고 이번 주에 뭘 할지 정합니다.

원장님이 처음에 "회의하고 결정한 내용 문서화하는 게 시간을 많이 잡아먹는다"
고 하셨습니다. 그 자리를 채웁니다.

회의록에는 결정과 맡은 사람이 남습니다. 다음 주 회의에서 지난주에 정한 걸
지켰는지 확인합니다. 정하기만 하고 아무도 안 하는 회의가 되지 않게요.

예전에는 AI 한 번이 "팀 전체인 척" 회의록을 썼습니다. 이제 진짜로 차례대로 말합니다.
담당마다 자기 일 쪽에서 자료를 보고, 앞사람이 한 말을 듣고 받아서 말합니다.
마지막에 박서준 팀장(기획)이 사회자로 정리해 결정과 맡을 사람을 적습니다.
회의록에는 결정과 함께 누가 무슨 근거로 무슨 말을 했는지가 남습니다.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

from engine import llm

from engine import staff, telegram, trends_sync
from engine.config import load_channel
from engine.voice import HSSUP_VOICE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KST = dt.timezone(dt.timedelta(hours=9))
# 서로 말을 받아 결정을 내리는 자리라 정리만 하는 모델로는 부족하다. 구독으로 돌아 추가 비용은 없다.
DEFAULT_MODEL = "claude-sonnet-5"

# 말하는 차례. 숫자를 보는 사람부터, 마지막은 사회자(기획).
MEMBERS = [
    ("나나", "게시", "지난주 실제로 인스타에 올라간 것과 못 올라간 것. 승인을 기다리며 쌓인 시안"),
    ("변우석", "피드 분석", "메인 계정 성과에서 무엇이 통했고 무엇이 안 통했는지. 숫자로"),
    ("전정국", "직원 관리", "직원 계정과 운영 흐름에서 손이 비거나 막힌 곳"),
    ("김주훈", "콘텐츠 편집", "캡션과 사진 게시물을 만들며 원장님 수정 요청이 많았던 부분, 말투"),
    ("차은우", "디자인", "디자인과 카드뉴스, 새로 그리기 요청에서 반응과 개선할 점"),
    ("박서준", "콘텐츠 기획, 사회", "앞사람들 말을 받아 이번 주 무엇을 만들지 제안. 반대 의견이 있으면 조율"),
]

SPEAK = """당신은 히썹 인스타그램 팀의 {name} 팀장({role})입니다. 월요일 아침 회의에서 당신 차례입니다.

당신이 보는 쪽: {focus}

- 아래 자료 중 당신 일과 관련된 것을 근거로, 지난주 무엇이 있었는지와 이번 주 제안을 말하세요.
- 앞사람이 한 말이 있으면 그 말을 받아서 말하세요. 동의하면 덧붙이고, 생각이 다르면 근거를 대고 말하세요.
  남의 말을 되풀이만 하지는 마세요.
- **자료에 없는 숫자나 사실을 지어내지 마세요.** 자료가 없으면 "자료가 없어 판단하기 어렵다" 고 말하세요.
- 회의에서 말하듯 두세 문장. 존댓말. 한자를 쓰지 마세요. 명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요."""

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


def hold_meeting(client, model: str, material: str) -> list[tuple[str, str, str]]:
    """차례대로 말합니다. 각자 앞사람들이 한 말을 듣고 받아서 말합니다.

    돌려주는 값: [(이름, 맡은 일, 한 말)]
    """
    said: list[tuple[str, str, str]] = []
    for name, role, focus in MEMBERS:
        heard = "\n".join(f"{n} 팀장: {t}" for n, _, t in said) or "(아직 아무도 말하지 않았습니다. 당신이 처음입니다)"
        try:
            resp = client.messages.create(
                model=model, max_tokens=800,
                system=SPEAK.format(name=name, role=role, focus=focus),
                messages=[{"role": "user", "content": f"[회의 자료]\n{material}\n\n[지금까지 회의에서 나온 말]\n{heard}\n\n{name} 팀장님 차례입니다."}],
            )
            text = " ".join("".join(b.text for b in resp.content if b.type == "text").split())
        except Exception as e:
            print(f"  ! {name} 팀장 차례를 건너뜁니다: {e}")
            continue
        if text:
            said.append((name, role, text.replace("·", ", ")))
            print(f"  - {name}: {text[:80]}")
    return said


def main() -> int:
    material, _ = gather()

    client = llm.client()
    model = os.environ.get("MEETING_MODEL", DEFAULT_MODEL)
    said = hold_meeting(client, model, material)
    transcript = "\n".join(f"{n} 팀장({r}): {t}" for n, r, t in said)

    # 사회자가 정리한다. 회의에서 나온 말을 근거로 결정과 맡을 사람을 적는다.
    resp = client.messages.create(
        model=model,
        max_tokens=3000,
        system=SYSTEM.format(roster=staff.roster_text(), voice=HSSUP_VOICE)
        + "\n\n회의는 이미 끝났습니다. [회의에서 나온 말]을 근거로 정리하세요. 말에 없는 결정을 새로 만들지 마세요.",
        messages=[{"role": "user", "content": f"{material}\n\n[회의에서 나온 말]\n{transcript or '(기록 없음)'}"}],
    )
    body = "".join(b.text for b in resp.content if b.type == "text").strip()
    if said:
        body += "\n\n## 회의에서 오간 말\n" + "\n".join(f"- **{n} 팀장** ({r}) {t}" for n, r, t in said)

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
