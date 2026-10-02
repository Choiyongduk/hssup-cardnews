"""사용법: python daily_ideas.py [--count 5]

매일 아침 콘텐츠 아이디어를 내는 일. 기획 담당(박서준)이 씁니다.

주간 기획(plan_content.py)은 월요일에 근거를 깊게 따져 3개를 냅니다.
이건 "오늘 뭘 올리지?" 에 바로 답하는 가벼운 목록입니다. 원장님이 앱에서 하나를 골라
누르면 바로 만들 수 있게, 아이디어마다 디자인 담당에게 넘길 요청문까지 붙입니다.

- 지난 7일 동안 낸 아이디어는 다시 내지 않습니다
- 최근 올린 게시물, 사업 상황 메모, 계절과 요일, 아직 안 끝난 요청을 읽습니다
- 사진이 없어도 만들 수 있는 것(카드, 일러스트)과 찍어야 하는 것을 구분합니다

본문은 앱이 읽을 수 있게 정해진 모양의 마크다운으로 직접 씁니다(## 번호. 제목 / - **항목**: 값).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from engine import brand, feed, llm, trends_sync
from engine.config import ROOT, load_channel  # noqa: F401  (.env 를 읽어 환경변수를 채웁니다)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_MODEL = "claude-sonnet-5"
WEEKDAYS = "월화수목금토일"

SYSTEM = """당신은 히썹 반영구 아카데미 인스타그램의 기획 담당 박서준 팀장입니다.
오늘 올리면 좋을 콘텐츠 아이디어 {count}개를 내세요. 원장님(민희님)이 아침에 훑어보고
하나를 골라 바로 만들 수 있어야 합니다.

계정은 둘입니다.
- academy (@hssup_academy): 반영구 교육. 수강, 수업, 수료, 원장님을 위한 실전 팁
- artmake (@h_ssup_artmake): 반영구 시술. 시술 전후, 기법, 고객 안내

원칙:
- 아이디어마다 왜 지금인지 한 줄로. 계절, 요일, 최근 성과, 사업 상황 메모 같은 근거에서 가져오세요.
- 지난 7일에 낸 아이디어와 겹치지 마세요. 최근에 이미 올린 주제도 피하세요(후속편은 괜찮음).
- {count}개 중 최소 2개는 **새로 찍지 않아도** 만들 수 있게 하세요.
  (글자 카드, 일러스트, 체크리스트, 이벤트 안내처럼 디자인 담당이 혼자 만들 수 있는 것)
- 찍어야 하는 아이디어는 무엇을 어떻게 찍을지 한 줄로. 폰으로 5분 안에 찍을 수 있는 것만.
- 숫자를 지어내지 마세요. 모르면 근거에 숫자를 쓰지 마세요.
- **먼저 후보를 {count}+3 개 떠올리세요.** 그다음 반대 의견 담당의 눈으로 보고, 근거가 약하거나 뻔하거나
  최근에 안 통한 형식인 것 세 개를 버리세요. 남은 {count} 개만 `ideas` 에, 버린 것과 이유는 `dropped` 에.
- 명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요. 한자를 쓰지 마세요.

`request` 는 디자인 담당에게 그대로 넘길 요청문입니다. 이미지에 들어갈 한글 문구(제목, 짧은 설명)와
분위기, 색, 필요하면 배경 그림까지 구체적으로 적으세요. 카드에 박히는 글자는 존댓말로 끝내지 말고
명사나 단정형으로 끊으세요. 찍어야 하는 아이디어도, 찍은 사진에 어떤 글을 얹을지 적어 두세요.

[말투 — 파이팅 넘치게]
아침에 원장님이 이걸 열었을 때 "오늘도 해보자!" 하는 기운이 나야 합니다.
- `greeting`: 박서준 팀장의 아침 인사 두세 줄. 요일과 계절, 오늘의 분위기를 살려 힘차게.
  느낌표 여러 개와 이모지(🔥💪✨🧡 같은 것) 두세 개를 써도 좋습니다. 원장님을 응원하세요.
- `title`: 짧고 힘 있게. 보자마자 만들고 싶어지게.
- `why`: 근거는 그대로 사실만, 하지만 "이거 지금 올리면 딱이에요!" 처럼 신나게 한 줄로.
- 다만 `request` 는 디자이너에게 주는 지시라 차분하고 구체적으로 씁니다."""

TOOL = {
    "name": "ideas",
    "description": "오늘의 콘텐츠 아이디어",
    "input_schema": {
        "type": "object",
        "properties": {
            "greeting": {"type": "string", "description": "박서준 팀장의 파이팅 넘치는 아침 인사 두세 줄"},
            "dropped": {
                "type": "array",
                "description": "후보 중 반대 의견으로 버린 것 세 개와 이유 한 줄",
                "items": {"type": "object", "properties": {
                    "title": {"type": "string"}, "reason": {"type": "string"}}, "required": ["title", "reason"]},
            },
            "ideas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "아이디어 제목 (한 줄)"},
                        "channel": {"type": "string", "enum": ["academy", "artmake"]},
                        "format": {"type": "string", "description": "예: 카드 1장, 카드뉴스, 사진 + 글, 릴스"},
                        "why": {"type": "string", "description": "왜 지금인지 한 줄"},
                        "needs_photo": {"type": "boolean", "description": "새로 찍어야 하면 true"},
                        "shoot": {"type": "string", "description": "찍어야 하면 무엇을 어떻게. 아니면 빈 문자열"},
                        "request": {"type": "string", "description": "디자인 담당에게 넘길 요청문"},
                    },
                    "required": ["title", "channel", "format", "why", "needs_photo", "request"],
                },
            },
        },
        "required": ["greeting", "ideas", "dropped"],
    },
}

CHANNEL_KO = {"academy": "아카데미", "artmake": "아트메이크"}


def _one_line(s: str) -> str:
    return " ".join((s or "").split())


def _recent_ideas(days: int = 7) -> list[str]:
    """지난 며칠 동안 낸 아이디어 제목. 같은 걸 또 내지 않게."""
    # 오늘 것은 뺀다. 같은 날 다시 돌리면(덮어쓰기) 오늘 낸 걸 피하느라 엉뚱해지지 않게.
    today_start = dt.datetime.now(feed.KST).replace(hour=0, minute=0, second=0, microsecond=0)
    since = (today_start - dt.timedelta(days=days)).isoformat()
    try:
        rows = trends_sync._get("ai_reports", {
            "select": "body", "kind": "eq.ideas", "order": "created_at.desc",
            "and": f"(created_at.gte.{since},created_at.lt.{today_start.isoformat()})",
        })
    except Exception as e:
        print(f"  ! 지난 아이디어를 읽지 못했습니다: {e}")
        return []
    titles = []
    for r in rows:
        for line in (r.get("body") or "").splitlines():
            if line.startswith("## "):
                titles.append(line.split(". ", 1)[-1].strip())
    return titles


def _account_facts() -> dict:
    """메인 계정의 최근 성과. 못 읽어도 아이디어는 낸다(근거가 약해질 뿐)."""
    try:
        cfg = load_channel("hssup-main")
        ig = cfg["instagram"]
        business_id, token = os.environ.get(ig["business_id_env"]), os.environ.get(ig["token_env"])
        if not business_id or not token:
            return {}
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)
        account = feed.fetch_account(business_id, token)
        media = feed.fetch_media(business_id, token, since)
        stats = feed.summarize(account, media)

        def brief(m: dict) -> dict:
            out = {"날짜": m["_when"].astimezone(feed.KST).strftime("%m-%d"), "형식": m.get("media_product_type")}
            if m.get("reach") is not None:
                out |= {"도달": m["reach"], "저장": m.get("saved")}
            out["캡션"] = _one_line(m.get("caption"))[:120]
            return out

        return {
            "최근_올린_것": [brief(m) for m in media[:10]],
            "잘된_게시물": [brief(m) for m in stats.get("top_posts", [])[:5]],
            "형식별_도달": stats.get("by_type_reach"),
        }
    except Exception as e:
        print(f"  ! 계정 성과를 읽지 못했습니다(그래도 아이디어는 냅니다): {e}")
        return {}


def compose(ideas: list[dict], today: str, greeting: str = "", dropped: list[dict] | None = None) -> str:
    """앱이 아이디어마다 버튼을 붙일 수 있게 정해진 모양으로 씁니다. 값은 한 줄씩.

    첫 "## " 앞까지는 박서준 팀장의 아침 인사입니다. 앱이 맨 위에 보여줍니다.
    """
    opening = (greeting or "").strip() or f"오늘 올리면 좋을 콘텐츠 {len(ideas)}가지예요! 골라서 누르시면 바로 만들어요 💪"
    lines = [opening.replace("## ", ""), ""]
    for i, it in enumerate(ideas, 1):
        lines += [
            f"## {i}. {_one_line(it['title'])}",
            f"- **계정**: {CHANNEL_KO.get(it.get('channel'), '아카데미')}",
            f"- **형식**: {_one_line(it.get('format'))}",
            f"- **왜 지금**: {_one_line(it.get('why'))}",
            f"- **사진**: {'찍어야 함 — ' + _one_line(it.get('shoot')) if it.get('needs_photo') else '없이 만들 수 있음'}",
            f"- **요청문**: {_one_line(it.get('request'))}",
            "",
        ]
    if dropped:
        # "## " 로 시작하지 않게 둔다. 앱은 "## " 마다 아이디어 카드를 만든다.
        lines.append("**버린 후보** (반대 의견으로 걸러낸 것)")
        lines += [f"- {_one_line(d.get('title'))}: {_one_line(d.get('reason'))}" for d in dropped]
    return "\n".join(lines).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--dry", action="store_true", help="앱에 올리지 않고 보여주기만")
    args = parser.parse_args()

    now = dt.datetime.now(feed.KST)
    today = now.strftime("%Y-%m-%d")
    payload = {
        "오늘": f"{today} ({WEEKDAYS[now.weekday()]}요일)",
        "지난_7일_낸_아이디어": _recent_ideas() or "없음",
        **_account_facts(),
    }
    business = trends_sync.fetch_context("business")
    if business:
        payload["사업_상황"] = business
    requests_open = trends_sync.fetch_requests()
    if requests_open:
        payload["아직_안_끝난_요청"] = [r["body"] for r in requests_open]

    resp = llm.client().messages.create(
        model=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
        max_tokens=4000,
        system=SYSTEM.format(count=args.count) + brand.marketing_block(),
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "ideas"},
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)}],
    )
    call = next((b for b in resp.content if b.type == "tool_use"), None)
    ideas = (call.input.get("ideas") if call else None) or []
    if not ideas:
        print(f"아이디어가 비어 있습니다 (stop_reason={resp.stop_reason}).")
        return 1

    body = compose(ideas[: args.count], today, call.input.get("greeting", ""), call.input.get("dropped") or [])
    if args.dry:
        print(body)
        return 0
    result = trends_sync.create_report(kind="ideas", title=f"오늘의 콘텐츠 아이디어 ({today})", body=body)
    print(f"아이디어 {len(ideas[: args.count])}개 {result}")
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
