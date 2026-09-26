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
- 함께 주는 '비교군'은 회사 메인 계정입니다. 팔로워 규모가 훨씬 크므로 참여 숫자를 직접 비교하지 마세요.
  작은 계정은 팔로워 대비 참여율이 원래 높게 나옵니다. 이걸 "직원이 더 잘한다"는 근거로 쓰면 안 됩니다.
  비교군에서 가져올 것은 **어떤 형식과 주제가 통했는지**이지 숫자의 크기가 아닙니다.
- 메인 계정에서 릴스 도달이 피드보다 몇 배 높게 나온 것은 같은 시장에서 검증된 사실입니다.
  직원 계정은 도달을 볼 수 없어 자체 증명이 안 되지만, 이 근거를 들어 제안해도 됩니다.
- 성장의 핵심은 기존 팔로워의 좋아요가 아니라 새로운 사람에게 닿는 것입니다. 이 관점으로 보세요.
- 팔로워 추이가 주어지면 그걸 성장의 근거로 쓰고, 기록이 없으면 "아직 판단할 수 없다"고 쓰세요.
- 주어진 숫자만 근거로 쓰고, 없는 수치를 지어내지 마세요. 표본이 적으면 적다고 쓰세요.
- 사람을 평가하지 말고 콘텐츠를 평가하세요. 순위를 매겨 우열을 가리는 말투는 피하세요.
- 게시량이 이미 충분한 사람에게 "더 올리세요"라고 하지 마세요. 같은 노력으로 결과를 바꿀 방법을 제안하세요.
- 일반론("꾸준히 올리세요")이 아니라 실제 게시물을 근거로 쓰세요.
- 명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요.
- 한자를 쓰지 마세요.

리포트 구성:
## 이번 기간 요약
## 메인 계정과 비교하면
## 계정별로 본 것 (각 계정마다 잘 된 점 하나와 시도해볼 것 하나)
## 이번 주 릴스 제안 (사람별로 2개씩. 각각 제목, 어떻게 찍을지 한두 줄, 왜 이게 통할지 근거)
## 회의 안건 (3~4개, 각각 왜 이 이야기를 해야 하는지 한 줄. 가능하면 숫자로 된 목표를 포함)"""


HISTORY_PATH = ROOT / "state" / "follower_history.json"


def _basic_engagement(m: dict) -> int:
    """직원 계정은 저장과 공유를 볼 수 없으므로, 비교는 좋아요와 댓글로만 통일합니다."""
    return (m.get("like_count") or 0) + (m.get("comments_count") or 0)


def build_benchmark(observer_id: str, token: str, since: dt.datetime, days: int) -> dict:
    """회사 메인 계정을 비교군으로 씁니다. 우리 계정이라 도달까지 볼 수 있습니다."""
    account = feed.fetch_account(observer_id, token)
    media = [m for m in feed.fetch_media(observer_id, token, since)]
    if not media:
        return {}

    reels = [m for m in media if m.get("media_product_type") == "REELS"]
    others = [m for m in media if m.get("media_product_type") != "REELS"]

    def avg_reach(items):
        vals = [m["reach"] for m in items if m.get("reach") is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    top_reels = sorted(reels, key=lambda m: m.get("reach") or 0, reverse=True)[:3]
    return {
        "계정": account.get("username"),
        "팔로워": account.get("followers_count"),
        "기간내_게시물수": len(media),
        "주당_게시물": round(len(media) / days * 7, 1),
        "릴스_건수": len(reels),
        "게시물당_평균_좋아요댓글": round(sum(_basic_engagement(m) for m in media) / len(media), 1),
        "릴스_평균_도달": avg_reach(reels),
        "피드_평균_도달": avg_reach(others),
        "도달_높았던_릴스": [
            {
                "날짜": m["_when"].astimezone(feed.KST).strftime("%Y-%m-%d"),
                "도달": m.get("reach"),
                "저장": m.get("saved"),
                "캡션": (m.get("caption") or "").replace("\n", " ")[:250],
            }
            for m in top_reels
        ],
    }


def track_followers(entries: list[dict], today: str) -> dict:
    """팔로워 수를 주마다 기록해 성장 추세를 볼 수 있게 합니다.
    인스타그램은 과거 팔로워 수를 알려주지 않으므로, 직접 쌓는 수밖에 없습니다."""
    history = {}
    if HISTORY_PATH.exists():
        history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))

    trends = {}
    for e in entries:
        uname = e["account"].get("username")
        followers = e["stats"].get("followers")
        points = history.setdefault(uname, [])
        if not any(p["date"] == today for p in points):
            points.append({"date": today, "followers": followers})
        points.sort(key=lambda p: p["date"])
        del points[:-52]  # 1년치만 보관

        if len(points) >= 2:
            first, last = points[0], points[-1]
            trends[uname] = {
                "기록시작": first["date"],
                "시작팔로워": first["followers"],
                "현재팔로워": last["followers"],
                "증감": last["followers"] - first["followers"],
                "직전기록대비": last["followers"] - points[-2]["followers"],
            }
        else:
            trends[uname] = {"기록": "이번이 첫 기록이라 추세를 아직 알 수 없습니다"}

    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return trends


def build_payload(entries: list[dict], days: int, benchmark: dict, trends: dict) -> str:
    out = []
    for e in entries:
        stats = e["stats"]
        by_weekday = {WEEKDAYS[k]: v for k, v in stats.get("by_weekday", {}).items()}
        uname = e["account"].get("username")
        out.append(
            {
                "이름": e["name"],
                "계정": uname,
                "팔로워": stats.get("followers"),
                "팔로워_추이": trends.get(uname),
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
    payload = {"분석기간_일": days, "직원": out}
    if benchmark:
        payload["비교군_회사_메인계정"] = benchmark
    return json.dumps(payload, ensure_ascii=False, indent=2)


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

    today = dt.datetime.now(feed.KST).strftime("%Y-%m-%d")
    trends = track_followers(entries, today)

    try:
        benchmark = build_benchmark(observer_id, token, since, args.days)
        print(f"  비교군 @{benchmark.get('계정')}: 릴스 평균 도달 {benchmark.get('릴스_평균_도달')}")
    except Exception as e:
        print(f"  ! 비교군 조회 실패, 비교 없이 진행합니다: {e}")
        benchmark = {}

    client = Anthropic()
    resp = client.messages.create(
        model=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
        max_tokens=8000,
        system=SYSTEM,
        messages=[{"role": "user", "content": build_payload(entries, args.days, benchmark, trends)}],
    )
    report = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not report:
        print(f"리포트가 비어 있습니다 (stop_reason={resp.stop_reason}).")
        return 1

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
