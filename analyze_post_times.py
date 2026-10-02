"""사용법: python analyze_post_times.py [--days 365] [--dry]

언제 올려야 잘 보이는지, 우리 계정(@hssup 메인) 숫자로 봅니다. AI 를 쓰지 않는 계산입니다.

남들이 말하는 "인스타 황금 시간" 이 아니라 우리 팔로워가 실제로 반응한 시간을 찾습니다.
공정하게 비교하려고 두 가지를 보정합니다.
- 팔로워가 늘면 도달도 같이 는다. 그래서 도달을 **같은 달, 같은 형식(릴스/피드)** 게시물의 가운데 값과 비교한
  배수로 바꿔서 본다. 1.3 이면 그 달 비슷한 게시물보다 30% 더 보였다는 뜻.
- 올린 지 7일 안 된 게시물은 아직 숫자가 오르는 중이라 뺀다.

결과는 앱 AI 오피스 기록에 "올리기 좋은 시간" 리포트로 올라갑니다(kind=timing).
실제 게시 시간은 cron-job.org 에서 바꿉니다(운영.md). 이 리포트는 바꿀지 판단할 근거입니다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import statistics as st
import sys
from collections import defaultdict

from engine import feed, trends_sync
from engine.config import load_channel

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WEEKDAYS = "월화수목금토일"
# 세 시간씩 묶는다. 한 시간 단위는 칸마다 게시물이 너무 적어 우연에 휘둘린다.
SLOTS = [(0, 3, "밤 0~3시"), (6, 9, "아침 6~9시"), (9, 12, "오전 9~12시"), (12, 15, "점심 12~3시"),
         (15, 18, "오후 3~6시"), (18, 21, "저녁 6~9시"), (21, 24, "밤 9~12시")]
MIN_POSTS = 8   # 이보다 적은 칸은 판단하지 않는다


def _slot(hour: int) -> str | None:
    return next((name for a, b, name in SLOTS if a <= hour < b), None)


def relative_reach(media: list[dict]) -> list[dict]:
    """도달을 같은 달, 같은 형식의 가운데 값 대비 배수로 바꿉니다."""
    groups: dict[tuple, list[int]] = defaultdict(list)
    for m in media:
        groups[(m["_when"].strftime("%Y-%m"), m.get("media_product_type"))].append(m["reach"])
    out = []
    for m in media:
        peers = groups[(m["_when"].strftime("%Y-%m"), m.get("media_product_type"))]
        if len(peers) < 3:
            continue   # 비교할 게시물이 너무 적은 달은 뺀다
        base = st.median(peers) or 1
        out.append({**m, "_rel": m["reach"] / base})
    return out


def table(rows: list[dict], key) -> list[tuple[str, int, float]]:
    """칸마다 (이름, 게시물 수, 도달 배수 가운데 값). 배수 높은 순."""
    cells: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        k = key(r)
        if k:
            cells[k].append(r["_rel"])
    return sorted(((k, len(v), st.median(v)) for k, v in cells.items()), key=lambda x: -x[2])


def compose(rows: list[dict], days: int) -> str:
    local = lambda r: r["_when"].astimezone(feed.KST)  # noqa: E731
    by_slot = table(rows, lambda r: _slot(local(r).hour))
    by_day = table(rows, lambda r: WEEKDAYS[local(r).weekday()] + "요일")
    by_kind = {}
    for kind in ("REELS", "FEED"):
        sub = [r for r in rows if r.get("media_product_type") == kind]
        if len(sub) >= MIN_POSTS * 2:
            by_kind[kind] = table(sub, lambda r: _slot(local(r).hour))

    def lines(cells):
        out = []
        for name, n, rel in cells:
            if n < MIN_POSTS:
                out.append(f"- {name}: 게시물 {n}개라 판단 보류")
            else:
                out.append(f"- **{name}**: 평소의 {rel:.2f}배 (게시물 {n}개)")
        return out

    good = [c for c in by_slot if c[1] >= MIN_POSTS]
    best, worst = (good[0], good[-1]) if len(good) >= 2 else (None, None)
    gooddays = [c for c in by_day if c[1] >= MIN_POSTS]

    body = [f"지난 {days}일 메인 계정 게시물 {len(rows)}개를 봤어요. "
            "도달은 같은 달 비슷한 형식 게시물과 비교한 배수예요(1.00 = 평소만큼).", ""]
    body += ["## 한 줄 결론"]
    if best and worst:
        gap = best[2] / max(worst[2], 0.01)
        if gap < 1.2:
            body.append("- 시간대에 따른 차이가 크지 않아요(20% 안쪽). 시간보다 내용이 더 중요해요. 지금 시간 그대로 두셔도 됩니다.")
        else:
            body.append(f"- **{best[0]}** 에 올린 게시물이 가장 잘 보였고, **{worst[0]}** 이 가장 덜 보였어요"
                        f"(약 {gap:.1f}배 차이).")
        if gooddays:
            body.append(f"- 요일로는 **{gooddays[0][0]}** 이 가장 좋고 **{gooddays[-1][0]}** 이 가장 약했어요.")
            top = gooddays[0]
            avg_n = sum(c[1] for c in by_day) / len(by_day)
            if top[2] >= 1.2 and top[1] < avg_n:
                # 잘되는데 덜 올리는 요일. 가장 손쉬운 개선이다.
                body.append(f"- {top[0]}은 평소보다 {top[2]:.1f}배 잘 보이는데 올린 횟수는 평균보다 적어요"
                            f"({top[1]}개, 평균 {avg_n:.0f}개). **{top[0]}에 하나씩 더 올려 보는 걸** 추천해요.")
    else:
        body.append("- 아직 게시물이 적어 판단하기 어려워요. 몇 달 더 쌓이면 다시 볼게요.")
    body += ["", "## 시간대별", *lines(by_slot), "", "## 요일별", *lines(by_day)]
    labels = {"REELS": "릴스", "FEED": "사진, 카드뉴스"}
    for kind, cells in by_kind.items():
        body += ["", f"## {labels[kind]}만 따로", *lines(cells)]
    body += ["", "## 읽는 법",
             "- 게시물이 적은 칸은 우연일 수 있어 판단을 보류했어요(8개 미만).",
             "- 그 시간에 올린 게 잘된 건지, 잘될 만한 내용을 그 시간에 올린 건지는 숫자만으로 가를 수 없어요.",
             "- 바꿔 보고 싶으시면 한 달 정도 새 시간에 올려 보고 다시 비교하는 게 가장 정확해요.",
             "- 실제 게시 시간은 cron-job.org 에서 바꿔요. 바꾸고 싶은 시간을 말씀해 주시면 알려드릴게요."]
    return "\n".join(body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--dry", action="store_true", help="앱에 올리지 않고 보여주기만")
    args = parser.parse_args()

    ig = load_channel("hssup-main")["instagram"]
    business_id, token = os.environ.get(ig["business_id_env"]), os.environ.get(ig["token_env"])
    if not business_id or not token:
        print("메인 계정 토큰이 없습니다")
        return 1
    now = dt.datetime.now(dt.timezone.utc)
    media = feed.fetch_media(business_id, token, now - dt.timedelta(days=args.days), max_pages=20)
    media = [m for m in media if m.get("reach") is not None and now - m["_when"] >= dt.timedelta(days=7)]
    rows = relative_reach(media)
    body = compose(rows, args.days)
    if args.dry:
        print(body)
        return 0
    result = trends_sync.create_report(kind="timing", title="올리기 좋은 시간", body=body, period_days=args.days)
    print(f"올리기 좋은 시간 리포트 {result}")
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
