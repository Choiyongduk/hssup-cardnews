"""사용법: python plan_content.py [--channel hssup-main] [--count 3]

기획 직원. 피드 분석가가 낸 리포트와 실제 게시물 성과를 읽고,
다음에 만들 콘텐츠 기획안을 써서 앱(AI 오피스)과 텔레그램으로 올립니다.

근거 없이 아이디어만 내면 어디서나 볼 수 있는 뻔한 소리가 나오므로,
반드시 실제 숫자와 실제 게시물을 읽고 쓰게 합니다.
한 번에 올리는 개수를 제한하는 것도 의도된 것입니다 — 검토할 사람이 한 명이기 때문입니다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from anthropic import Anthropic

from engine import feed, telegram, trends_sync
from engine.config import ROOT, load_channel
from engine.voice import HSSUP_VOICE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM = """당신은 {name} 인스타그램 계정의 콘텐츠 기획자입니다.
피드 분석 결과와 실제 게시물 성과를 보고, 다음에 만들 콘텐츠 기획안 {count}개를 작성하세요.

원칙:
- 모든 기획에는 **이 계정의 실제 데이터**에서 나온 근거가 있어야 합니다. 어떤 게시물이 어떤 숫자를 냈는지 인용하세요.
- "꾸준히 올리세요", "트렌드를 활용하세요" 같은 어디에나 해당하는 말은 쓰지 마세요.
- 저장과 공유는 도움이 됐다는 신호라 좋아요보다 무겁게 보세요. 도달은 알고리즘이 밀어준 정도입니다.
- 촬영이 현실적으로 가능한 것만 제안하세요. 이 계정은 반영구 시술과 교육을 하는 곳입니다.
- 이미 올린 것과 똑같은 걸 다시 제안하지 마세요. 이어지는 후속편은 괜찮습니다.
- 확신이 없으면 "실험"이라고 표시하고 무엇을 확인하려는 건지 쓰세요.
- 명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요.
- 한자를 쓰지 마세요.

각 기획안은 이 형식으로 쓰세요:

## 기획 N. (제목)
- **형식**: 릴스 / 피드 / 캐러셀 중 하나와 예상 길이
- **근거**: 어떤 데이터를 보고 이걸 제안하는지 (실제 숫자 인용)
- **촬영**: 무엇을 어떻게 찍을지 두세 줄
- **캡션 초안**: 그대로 올려도 되는 수준으로. 아래 말투를 그대로 따르세요
- **해시태그**: 성과가 확인된 태그 위주로 5~7개

마지막에 "## 이번 주 우선순위" 로 어떤 걸 먼저 하면 좋을지 한 문단 쓰세요.

말투 규칙은 **캡션 초안에만** 적용합니다. 근거와 촬영 설명은 지금처럼 차분한 보고체로 쓰세요.

{voice}"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="hssup-main")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--days", type=int, default=60)
    args = parser.parse_args()

    cfg = load_channel(args.channel)
    ig_cfg = cfg["instagram"]
    business_id = os.environ.get(ig_cfg["business_id_env"])
    token = os.environ.get(ig_cfg["token_env"])
    if not business_id or not token:
        print(f"{args.channel}: instagram 환경변수가 없습니다.")
        return 1

    # 1) 피드 분석가가 낸 최신 리포트를 읽습니다.
    analysis = None
    try:
        row = trends_sync.fetch_latest_report("feed")
        if row:
            analysis = row["body"]
            print(f"피드 분석 리포트 참고: {row['title']}")
    except Exception as e:
        print(f"  ! 피드 분석 리포트를 읽지 못했습니다: {e}")

    # 2) 실제 게시물 성과를 직접 봅니다.
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)
    account = feed.fetch_account(business_id, token)
    media = feed.fetch_media(business_id, token, since)
    stats = feed.summarize(account, media)
    print(f"[{args.channel}] @{account.get('username')} 최근 {args.days}일 게시물 {stats['post_count']}건")

    def brief(m: dict, cap: int = 300) -> dict:
        out = {
            "날짜": m["_when"].astimezone(feed.KST).strftime("%Y-%m-%d"),
            "형식": m.get("media_product_type"),
            "좋아요": m.get("like_count"),
            "댓글": m.get("comments_count"),
        }
        if m.get("reach") is not None:
            out |= {"도달": m["reach"], "저장": m.get("saved"), "공유": m.get("shares")}
        out["캡션"] = (m.get("caption") or "").replace("\n", " ")[:cap]
        return out

    payload = {
        "계정": account.get("username"),
        "팔로워": stats.get("followers"),
        "형식별_성과": stats.get("by_type"),
        "형식별_도달": stats.get("by_type_reach"),
        "평균_도달": stats.get("avg_reach"),
        "평균_저장": stats.get("avg_saved"),
        "해시태그_성과": stats.get("top_hashtags"),
        "잘된_게시물": [brief(m, 400) for m in stats.get("top_posts", [])],
        "안된_게시물": [brief(m) for m in stats.get("bottom_posts", [])],
        "최근_올린_것": [brief(m, 120) for m in media[:12]],
    }
    if analysis:
        payload["피드_분석가_리포트"] = analysis

    client = Anthropic()
    resp = client.messages.create(
        model=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
        max_tokens=8000,
        system=SYSTEM.format(name=cfg["name"], count=args.count, voice=HSSUP_VOICE),
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)}],
    )
    plan = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not plan:
        print(f"기획안이 비어 있습니다 (stop_reason={resp.stop_reason}).")
        return 1

    today = dt.datetime.now(feed.KST).strftime("%Y-%m-%d")
    out_path = ROOT / "output" / "analysis" / "plan" / f"{today}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(plan, encoding="utf-8")
    print(f"기획안 저장: {out_path}")

    try:
        trends_sync.create_report(
            kind="plan",
            target=args.channel,
            title=f"콘텐츠 기획안 {args.count}개 ({today})",
            body=plan,
            period_days=args.days,
        )
        print("앱에 기획안 등록 완료")
    except Exception as e:
        print(f"  ! 앱 등록 실패: {e}")

    tg_cfg = cfg.get("telegram")
    bot_token = os.environ.get(tg_cfg["bot_token_env"]) if tg_cfg else None
    if bot_token:
        text = f"💡 콘텐츠 기획안 ({today})\n\n" + plan
        for i in range(0, len(text), 3900):
            telegram.notify(bot_token, str(tg_cfg["chat_id"]), text[i : i + 3900])
        print("텔레그램 전송 완료")

    return 0


if __name__ == "__main__":
    sys.exit(main())
