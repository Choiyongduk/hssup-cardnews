"""사용법: python analyze_feed.py --channel hssup-academy [--days 90]

채널의 인스타그램 피드를 분석해서 다음 콘텐츠 방향과 마케팅 제안을 리포트로 만들고,
텔레그램으로 보냅니다. 리포트는 output/analysis/<slug>/<날짜>.md 에도 남깁니다.

숫자는 engine/feed.py가 계산하고, Claude는 해석과 제안만 맡습니다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from anthropic import Anthropic

from engine import feed, telegram
from engine.config import ROOT, load_channel

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_MODEL = "claude-sonnet-5"
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

SYSTEM = """당신은 {name} 인스타그램 계정을 담당하는 콘텐츠 전략가입니다.
아래 실제 지표를 보고 리포트를 작성하세요.

원칙:
- 주어진 숫자만 근거로 쓰세요. 없는 수치를 지어내지 마세요.
- 게시물이 적거나 참여가 거의 없어 판단할 수 없으면, 억지로 결론 내지 말고 "데이터가 부족하다"고 쓰고 무엇이 더 필요한지 적으세요.
- 일반론("꾸준히 올리세요", "해시태그를 활용하세요") 말고, 이 계정의 실제 게시물을 근거로 구체적으로 쓰세요.
- 제안은 바로 실행할 수 있는 형태로. 콘텐츠 주제는 실제 캡션으로 쓸 수 있을 만큼 구체적으로.
- 명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요.
- 한자를 쓰지 마세요.

리포트 구성:
## 한 줄 요약
## 지금 상태
## 무엇이 먹혔나
## 다음에 만들 콘텐츠 (5개, 각각 제목과 왜 이게 먹힐지)
## 마케팅 제안 (3개 이내, 우선순위 순)"""


def _fmt_post(m: dict, cap: int = 200) -> dict:
    caption = (m.get("caption") or "").replace("\n", " ")
    return {
        "날짜": m["_when"].astimezone(feed.KST).strftime("%Y-%m-%d"),
        "유형": m.get("media_product_type"),
        "좋아요": m.get("like_count"),
        "댓글": m.get("comments_count"),
        "캡션": caption[:cap],
    }


def build_prompt(account: dict, stats: dict, days: int) -> str:
    by_weekday = {
        WEEKDAYS[k]: v for k, v in stats.get("by_weekday", {}).items()
    }
    payload = {
        "계정": account.get("username"),
        "팔로워": stats["followers"],
        "분석기간_일": days,
        "게시물수": stats["post_count"],
        "주당_게시물": stats.get("posts_per_week"),
        "마지막_게시": stats.get("latest_post"),
        "마지막_게시_후_경과일": stats.get("days_since_last_post"),
        "게시물당_평균_참여": stats.get("avg_engagement"),
        "참여율_퍼센트": stats.get("engagement_rate_pct"),
        "유형별": stats.get("by_type"),
        "요일별": by_weekday,
        "시간대별": stats.get("by_hour"),
        "해시태그": stats.get("top_hashtags"),
        "참여_높은_게시물": [_fmt_post(m, 400) for m in stats.get("top_posts", [])],
        "참여_낮은_게시물": [_fmt_post(m) for m in stats.get("bottom_posts", [])],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", required=True)
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()

    cfg = load_channel(args.channel)
    ig_cfg = cfg.get("instagram")
    if not ig_cfg:
        print(f"{args.channel}: instagram 설정이 없습니다.")
        return 1

    business_id = os.environ.get(ig_cfg["business_id_env"])
    token = os.environ.get(ig_cfg["token_env"])
    if not business_id or not token:
        print(f"{args.channel}: instagram 환경변수가 없습니다.")
        return 1

    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)
    account = feed.fetch_account(business_id, token)
    media = feed.fetch_media(business_id, token, since)
    stats = feed.summarize(account, media)

    print(f"[{args.channel}] @{account.get('username')} 최근 {args.days}일 게시물 {stats['post_count']}건")

    client = Anthropic()
    resp = client.messages.create(
        model=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
        max_tokens=8000,
        system=SYSTEM.format(name=cfg["name"]),
        messages=[{"role": "user", "content": build_prompt(account, stats, args.days)}],
    )
    report = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not report:
        print(f"리포트가 비어 있습니다 (stop_reason={resp.stop_reason}). 저장하지 않습니다.")
        return 1

    today = dt.datetime.now(feed.KST).strftime("%Y-%m-%d")
    out_path = ROOT / "output" / "analysis" / args.channel / f"{today}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"리포트 저장: {out_path}")

    tg_cfg = cfg.get("telegram")
    if tg_cfg:
        bot_token = os.environ.get(tg_cfg["bot_token_env"])
        if bot_token:
            header = f"📊 [{cfg['name']}] 피드 분석 ({today}, 최근 {args.days}일)\n\n"
            # 텔레그램 메시지는 4096자 제한이라, 잘라내지 말고 나눠 보냅니다.
            text = header + report
            for i in range(0, len(text), 3900):
                telegram.notify(bot_token, str(tg_cfg["chat_id"]), text[i : i + 3900])
            print("텔레그램 전송 완료")

    return 0


if __name__ == "__main__":
    sys.exit(main())
