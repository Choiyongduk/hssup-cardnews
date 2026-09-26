"""인스타그램 피드 수집과 지표 계산.

Claude에게 넘기기 전에 계산으로 낼 수 있는 건 전부 여기서 냅니다.
숫자 계산을 LLM에 맡기면 틀리기 때문입니다.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter

import requests

API = "https://graph.facebook.com/v21.0"

BASE_FIELDS = "id,caption,media_type,media_product_type,timestamp,like_count,comments_count,permalink"
# 도달·저장·공유는 instagram_manage_insights 권한이 있어야 나옵니다. 없으면 BASE_FIELDS로 물러납니다.
INSIGHT_METRICS = "reach,saved,shares"
MEDIA_FIELDS = f"{BASE_FIELDS},insights.metric({INSIGHT_METRICS})"
KST = dt.timezone(dt.timedelta(hours=9))


def fetch_account(business_id: str, token: str) -> dict:
    resp = requests.get(
        f"{API}/{business_id}",
        params={"fields": "username,followers_count,media_count", "access_token": token},
        timeout=30,
    )
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"계정 조회 실패: {body['error'].get('message')}")
    return body


def _flatten_insights(m: dict) -> None:
    """insights 응답을 게시물 딕셔너리에 평평하게 올려둡니다."""
    for item in (m.pop("insights", {}) or {}).get("data", []):
        values = item.get("values") or [{}]
        m[item["name"]] = values[0].get("value")


def fetch_media(business_id: str, token: str, since: dt.datetime, max_pages: int = 10) -> list[dict]:
    """since 이후 게시물을 최신순으로 가져옵니다.

    인사이트 권한이 없으면 기본 필드만으로 다시 시도합니다 (분석이 얕아질 뿐 동작은 합니다).
    """
    url = f"{API}/{business_id}/media"
    fields = MEDIA_FIELDS
    params = {"fields": fields, "limit": 100, "access_token": token}
    out: list[dict] = []

    for _ in range(max_pages):
        body = requests.get(url, params=params, timeout=30).json()
        params = None
        if "error" in body:
            if fields == MEDIA_FIELDS and not out:
                fields = BASE_FIELDS
                url = f"{API}/{business_id}/media"
                params = {"fields": fields, "limit": 100, "access_token": token}
                continue
            raise RuntimeError(f"게시물 조회 실패: {body['error'].get('message')}")

        for m in body.get("data", []):
            when = dt.datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00"))
            if when < since:
                return out
            m["_when"] = when
            _flatten_insights(m)
            out.append(m)

        url = body.get("paging", {}).get("next")
        if not url:
            break

    return out


def _hashtags(caption: str) -> list[str]:
    return re.findall(r"#([\w가-힣]+)", caption or "")


def _engagement(m: dict) -> int:
    """저장과 공유는 '도움이 됐다'는 신호라 좋아요보다 의미가 큽니다. 있으면 함께 셉니다."""
    return (
        (m.get("like_count") or 0)
        + (m.get("comments_count") or 0)
        + (m.get("saved") or 0)
        + (m.get("shares") or 0)
    )


def summarize(account: dict, media: list[dict]) -> dict:
    """게시물 목록에서 지표를 계산합니다. 해석은 하지 않습니다."""
    followers = account.get("followers_count") or 0
    if not media:
        return {"followers": followers, "post_count": 0}

    whens = [m["_when"] for m in media]
    # 게시 빈도의 분모는 "가장 오래된 게시물부터 지금까지"입니다.
    # 첫 게시물과 마지막 게시물 사이로 재면, 게시가 1건일 때 기간이 0이 되어 빈도가 폭주합니다.
    now = dt.datetime.now(dt.timezone.utc)
    span_days = max((now - min(whens)).days, 1)
    total_eng = sum(_engagement(m) for m in media)

    by_type: dict[str, list[int]] = {}
    by_type_reach: dict[str, list[int]] = {}
    by_weekday: dict[int, list[int]] = {}
    by_hour: dict[int, list[int]] = {}
    tag_counter: Counter[str] = Counter()
    tag_eng: dict[str, list[int]] = {}

    for m in media:
        eng = _engagement(m)
        kind = m.get("media_product_type") or "UNKNOWN"
        by_type.setdefault(kind, []).append(eng)
        if m.get("reach") is not None:
            by_type_reach.setdefault(kind, []).append(m["reach"])
        local = m["_when"].astimezone(KST)
        by_weekday.setdefault(local.weekday(), []).append(eng)
        by_hour.setdefault(local.hour, []).append(eng)
        for tag in set(_hashtags(m.get("caption") or "")):
            tag_counter[tag] += 1
            tag_eng.setdefault(tag, []).append(eng)

    def avg(values: list[int]) -> float:
        return round(sum(values) / len(values), 1) if values else 0.0

    ranked = sorted(media, key=_engagement, reverse=True)
    reaches = [m["reach"] for m in media if m.get("reach") is not None]
    saves = [m["saved"] for m in media if m.get("saved") is not None]
    shares = [m["shares"] for m in media if m.get("shares") is not None]
    total_reach = sum(reaches)

    stats = {
        "followers": followers,
        "post_count": len(media),
        "span_days": span_days,
        "posts_per_week": round(len(media) / span_days * 7, 1),
        "latest_post": max(whens).astimezone(KST).strftime("%Y-%m-%d"),
        "days_since_last_post": (now - max(whens)).days,
        "avg_engagement": avg([_engagement(m) for m in media]),
        "engagement_rate_pct": round(total_eng / len(media) / followers * 100, 2) if followers else 0.0,
        "by_type": {k: {"count": len(v), "avg": avg(v)} for k, v in by_type.items()},
        "by_weekday": {k: {"count": len(v), "avg": avg(v)} for k, v in sorted(by_weekday.items())},
        "by_hour": {k: {"count": len(v), "avg": avg(v)} for k, v in sorted(by_hour.items())},
        "top_hashtags": [
            {"tag": t, "count": c, "avg": avg(tag_eng[t])} for t, c in tag_counter.most_common(12)
        ],
        "top_posts": ranked[:5],
        "bottom_posts": ranked[-5:] if len(ranked) > 5 else [],
    }

    if reaches:
        # 도달 대비 참여율은 계정 규모와 무관하게 "이 콘텐츠가 통했나"를 보여줍니다.
        # 게시물별로 내면 도달이 작은 글이 과대평가되므로 전체 합으로 계산합니다.
        stats["avg_reach"] = avg(reaches)
        stats["avg_saved"] = avg(saves)
        stats["avg_shares"] = avg(shares)
        stats["engagement_per_reach_pct"] = round(total_eng / total_reach * 100, 2) if total_reach else 0.0
        stats["reach_vs_followers_pct"] = round(avg(reaches) / followers * 100, 1) if followers else 0.0
        stats["by_type_reach"] = {
            k: {"count": len(v), "avg_reach": avg(v)} for k, v in by_type_reach.items()
        }

    return stats
