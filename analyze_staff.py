"""사용법: python analyze_staff.py [--days 28]

staff.yaml에 적힌 직원 계정들을 한 장에 비교 분석하고, 회의에서 다룰 안건까지 뽑아
텔레그램으로 보냅니다. 리포트는 output/analysis/staff/<날짜>.md 에도 남습니다.

직원 개인 계정이라 공개 데이터(좋아요, 댓글)만 봅니다. 도달과 저장은 볼 수 없습니다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

import yaml
from anthropic import Anthropic

from engine import feed, telegram
from engine.config import ROOT

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_MODEL = "claude-sonnet-5"
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

SYSTEM = """당신은 히썹 반영구 아카데미 원장을 돕는 참모입니다.
직원들의 인스타그램 계정 지표를 보고, 주간 회의에서 쓸 자료를 작성하세요.

전제:
- 이 계정들은 직원 개인 계정이고, 공개된 좋아요와 댓글만 볼 수 있습니다. 도달이나 저장은 알 수 없으니 그에 대해 추측하지 마세요.
- 팔로워 수가 비슷해도 사람마다 상황이 다릅니다. 순위를 매겨 우열을 가리는 말투는 피하세요.
- 주어진 숫자만 근거로 쓰고, 없는 수치를 지어내지 마세요. 표본이 적으면 적다고 쓰세요.
- 잘한 점을 먼저, 개선점은 구체적인 행동으로 쓰세요. 사람을 평가하지 말고 콘텐츠를 평가하세요.
- 일반론("꾸준히 올리세요")이 아니라 실제 게시물을 근거로 쓰세요.
- 명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요.
- 한자를 쓰지 마세요.

리포트 구성:
## 이번 기간 요약
## 계정별로 본 것 (각 계정마다 잘 된 점 하나와 시도해볼 것 하나)
## 같이 보면 좋은 점 (계정들 사이에서 공통으로 보이는 패턴이나, 한쪽이 잘하는 걸 다른 쪽이 가져갈 만한 것)
## 회의 안건 (3~4개, 각각 왜 이 이야기를 해야 하는지 한 줄)"""


def build_payload(entries: list[dict], days: int) -> str:
    out = []
    for e in entries:
        stats = e["stats"]
        by_weekday = {WEEKDAYS[k]: v for k, v in stats.get("by_weekday", {}).items()}
        out.append(
            {
                "이름": e["name"],
                "계정": e["account"].get("username"),
                "팔로워": stats.get("followers"),
                "기간내_게시물수": stats.get("post_count"),
                "주당_게시물": stats.get("posts_per_week"),
                "마지막_게시": stats.get("latest_post"),
                "마지막_게시_후_경과일": stats.get("days_since_last_post"),
                "게시물당_평균_참여": stats.get("avg_engagement"),
                "유형별": stats.get("by_type"),
                "요일별": by_weekday,
                "해시태그": stats.get("top_hashtags", [])[:8],
                "참여_높은_게시물": [
                    {
                        "날짜": m["_when"].astimezone(feed.KST).strftime("%Y-%m-%d"),
                        "유형": m.get("media_product_type"),
                        "좋아요": m.get("like_count"),
                        "댓글": m.get("comments_count"),
                        "캡션": (m.get("caption") or "").replace("\n", " ")[:300],
                    }
                    for m in stats.get("top_posts", [])[:3]
                ],
            }
        )
    return json.dumps({"분석기간_일": days, "직원": out}, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=28)
    args = parser.parse_args()

    cfg = yaml.safe_load((ROOT / "staff.yaml").read_text(encoding="utf-8"))
    observer_id = os.environ.get(cfg["observer"]["business_id_env"])
    token = os.environ.get(cfg["observer"]["token_env"])
    if not observer_id or not token:
        print("observer 환경변수가 없습니다.")
        return 1

    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)
    entries = []
    for item in cfg["accounts"]:
        try:
            account, media = feed.fetch_public(observer_id, token, item["username"], since)
        except Exception as e:
            print(f"  ! {item['username']}: {e}")
            continue
        stats = feed.summarize(account, media)
        entries.append({"name": item.get("name") or item["username"], "account": account, "stats": stats})
        print(f"  @{item['username']}: 최근 {args.days}일 게시물 {stats['post_count']}건")

    if not entries:
        print("분석할 계정이 없습니다.")
        return 1

    client = Anthropic()
    resp = client.messages.create(
        model=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
        max_tokens=8000,
        system=SYSTEM,
        messages=[{"role": "user", "content": build_payload(entries, args.days)}],
    )
    report = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not report:
        print(f"리포트가 비어 있습니다 (stop_reason={resp.stop_reason}).")
        return 1

    today = dt.datetime.now(feed.KST).strftime("%Y-%m-%d")
    out_path = ROOT / "output" / "analysis" / "staff" / f"{today}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"리포트 저장: {out_path}")

    tg_cfg = cfg.get("telegram")
    bot_token = os.environ.get(tg_cfg["bot_token_env"]) if tg_cfg else None
    if bot_token:
        text = f"👥 직원 계정 분석 ({today}, 최근 {args.days}일)\n\n" + report
        for i in range(0, len(text), 3900):
            telegram.notify(bot_token, str(tg_cfg["chat_id"]), text[i : i + 3900])
        print("텔레그램 전송 완료")

    return 0


if __name__ == "__main__":
    sys.exit(main())
