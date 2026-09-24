"""사용법: python render.py --channel ai-news [--date 2026-09-22] [--slot am|pm]
--slot을 쓰면 하루에 여러 번 발행해도 output/pending 레코드가 서로 안 덮어씁니다."""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from engine.caption import build_caption
from engine.config import ROOT, load_channel
from engine.renderer import Renderer
from engine.sources import get_source
from engine.validate import validate

WEEKDAYS = "월화수목금토일"


def main() -> int:
    ap = argparse.ArgumentParser(description="카드뉴스 PNG 생성")
    ap.add_argument("--channel", required=True, help="channels/<이름>.yaml")
    ap.add_argument("--date", help="표시 날짜 (기본: 데이터의 date 또는 오늘)")
    ap.add_argument("--slot", help="하루 여러 번 발행할 때 구분용 태그 (예: am, pm)")
    args = ap.parse_args()

    cfg = load_channel(args.channel)
    source_cfg = {
        **cfg["source"],
        "slug": cfg["slug"],
        "cards": cfg.get("cards", 4),
        "topic": cfg.get("topic", cfg["name"]),
    }
    data = get_source(source_cfg).load()

    date = dt.date.fromisoformat(args.date or data.get("date") or dt.date.today().isoformat())
    data["date"] = date.isoformat()
    data["date_label"] = f"{date.year}.{date.month:02d}.{date.day:02d} ({WEEKDAYS[date.weekday()]})"
    key = f"{data['date']}-{args.slot}" if args.slot else data["date"]

    try:
        warnings = validate(data, cfg)
    except ValueError as e:
        print(e)
        return 1
    for w in warnings:
        print(f"  ! 길이 경고: {w}")

    items = data["items"][: cfg["cards"]]
    out_dir = ROOT / "output" / cfg["slug"] / key
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{cfg['name']}] 렌더링 중 → {out_dir}")
    pngs = Renderer(cfg).render(data, items, out_dir)
    caption = build_caption(data, cfg, items)
    (out_dir / "caption.txt").write_text(caption, encoding="utf-8")

    for p in pngs:
        print(f"  - {p.relative_to(ROOT)}")
    print(f"  - {(out_dir / 'caption.txt').relative_to(ROOT)}")

    try:
        from engine import assets
        from engine.telegram import create_pending

        image_urls = assets.upload_images(pngs, cfg["slug"], key)
        create_pending(
            cfg["slug"], key, image_urls, caption,
            headline=data.get("headline"), one_liner=data.get("one_liner"),
        )
        print("  이미지 공개 업로드 + 승인 대기 레코드 생성 완료")
    except ValueError as e:
        print(f"  ! 이미지 업로드 건너뜀: {e}")

    tg_cfg = cfg.get("telegram")
    if tg_cfg:
        import os

        token = os.environ.get(tg_cfg["bot_token_env"])
        if token:
            from engine.telegram import send_preview

            send_preview(token, str(tg_cfg["chat_id"]), pngs, caption, cfg["slug"], key)
            print("  텔레그램 미리보기 전송 완료")
        else:
            print(f"  ! 텔레그램 미리보기 건너뜀: {tg_cfg['bot_token_env']} 환경변수 없음")
    else:
        print("  ! 텔레그램 미리보기 건너뜀: channels/<slug>.yaml에 telegram 설정이 없습니다.")

    print("완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
