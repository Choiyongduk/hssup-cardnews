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


def _team_review(cfg, data, items, pngs, caption, out_dir):
    """박서준(기획)과 김주훈(편집)이 카드뉴스를 먼저 보고, 카드 글과 캡션을 한 바퀴만 고칩니다.

    카드 글을 고치면 차은우(디자인)가 다시 그립니다. 다시 그린 게 깨지면 처음 것을 씁니다.
    돌려주는 값: (캡션, 그림들, 카드 데이터, 카드 목록, 대화 기록 [(담당, 말)])
    """
    import copy

    log: list[tuple[str, str]] = []
    try:
        from engine import free_design, team_review

        images = [free_design._b64_block(p.read_bytes()) for p in pngs[:7]]
        rv = team_review.review(
            images, caption, f"주제: {cfg.get('topic', cfg['name'])}", f"카드뉴스 {len(pngs)}장",
            cards={"headline": data.get("headline"), "items": items},
        )
    except Exception as e:
        print(f"  ! 내부 검수를 건너뜁니다: {e}")
        return caption, pngs, data, items, log

    planner, editor = rv["planner"], rv["editor"]
    if planner["comment"]:
        log.append(("planner", planner["comment"]))
    if editor["comment"]:
        log.append(("editor", editor["comment"]))
    if not editor["ok"] and editor["caption"] and editor["caption"] != caption:
        caption = editor["caption"]
        print("  - 내부 검수: 캡션 고침")

    edits, cover = rv["cards"], rv["cover_title"]
    if not (edits or cover):
        return caption, pngs, data, items, log

    fixed = copy.deepcopy(data)
    if cover:
        fixed["headline"] = cover
    n = min(cfg["cards"], len(fixed["items"]))
    for edit in edits:
        i = int(edit.get("index", 0)) - 1
        if not 0 <= i < n:
            continue
        for k in ("title", "summary", "why"):
            if edit.get(k):
                fixed["items"][i][k] = edit[k]

    renderer = Renderer(cfg)
    fixed_pngs = renderer.render(fixed, fixed["items"][:n], out_dir / "review")
    if renderer.problems:
        print(f"  ! 내부 검수로 고친 카드가 깨져서 처음 것 그대로: {renderer.problems[0]}")
        log.append(("designer", "말씀하신 대로 고쳐 그려 봤는데 깨지는 데가 있어서 처음 것 그대로 둘게요."))
        return caption, pngs, data, items, log
    changed = len({e.get("index") for e in edits}) + (1 if cover else 0)
    log.append(("designer", f"말씀하신 카드 글 {changed}군데 고쳐서 다시 그렸어요."))
    print(f"  - 내부 검수: 카드 글 {changed}군데 고쳐 다시 그림")
    return caption, fixed_pngs, fixed, fixed["items"][:n], log


def _make_reel_draft(cfg, data, items, key, caption, out_dir) -> None:
    """카드뉴스와 같은 내용의 릴스를 만들어 따로 승인 대기에 올립니다(engine/reel.py).

    인스타에서 캐러셀과 릴스는 서로 다른 게시물이라 승인도 따로 받는다. ref_key 는 "<카드뉴스>-reel".
    릴스의 글을 바꾸려면 카드뉴스 시안에서 고치면 된다(revise_post 가 릴스도 다시 만든다).
    """
    try:
        from engine import assets, reel, trends_sync
        from engine.telegram import create_pending

        reel_key = f"{key}-reel"
        path = reel.make_reel(data, items, cfg.get("handle", "@hssup_academy"), out_dir / "reel.mp4")
        url = assets.upload_images([path], cfg["slug"], reel_key)[0]
        create_pending(cfg["slug"], reel_key, [url], caption, reel_of=key)
        trends_sync.create_approval(
            kind="post", channel=cfg["slug"], ref_key=reel_key,
            title=f"{cfg['name']} 릴스 승인", body=caption, image_urls=[url],
            payload={"media_type": "reel", "cards_ref": key},
        )
        print(f"  릴스도 만들어 승인 대기에 올림: {url}")
    except Exception as e:
        print(f"  ! 릴스를 만들지 못했습니다(카드뉴스는 그대로): {e}")


def _post_team_log(slug: str, key: str, log: list[tuple[str, str]]) -> None:
    """내부 검수에서 오간 말을 시안 대화창에 남깁니다."""
    if not log:
        return
    try:
        from engine import trends_sync

        rows = trends_sync._get("ai_approvals", {"select": "id", "channel": f"eq.{slug}", "ref_key": f"eq.{key}"})
        if rows:
            for staff_key, body in log:
                trends_sync.create_approval_message(rows[0]["id"], "staff", body, staff_key=staff_key)
    except Exception as e:
        print(f"  ! 내부 검수 대화를 남기지 못했습니다: {e}")


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
    # 원장님께 올리기 전에 팀이 먼저 본다(engine/team_review.py). 실패해도 카드뉴스는 올라간다.
    caption, pngs, data, items, team_log = _team_review(cfg, data, items, pngs, caption, out_dir)
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

        # 이 게시물의 카드 내용을 따로 떠둡니다. 나중에 고칠 때 이걸 보고 다시 그립니다.
        # 채널 파일 하나만 쓰면 카드뉴스가 여러 개 대기할 때 서로 섞입니다.
        try:
            from engine import cards as cards_mod

            if cards_mod.is_cards_channel(cfg):
                cards_mod.save_cards(cfg, data, ref_key=key)
                print(f"  카드 내용 따로 보관: data/posts/{cfg['slug']}-{key}.json")
        except Exception as e:
            print(f"  ! 카드 내용 보관 실패: {e}")

        # 앱에서도 보고 승인할 수 있게 같은 건을 올립니다.
        try:
            from engine import trends_sync

            trends_sync.create_approval(
                kind="post",
                channel=cfg["slug"],
                ref_key=key,
                title=f"{cfg['name']} 게시 승인",
                body=caption,
                image_urls=image_urls,
                payload={"media_type": "carousel", "cards": len(pngs)},
            )
            print("  앱 승인 목록 등록 완료")
            _post_team_log(cfg["slug"], key, team_log)
        except Exception as e:
            print(f"  ! 앱 승인 등록 실패: {e}")

        # 같은 내용으로 릴스도 하나. 실패해도 카드뉴스는 그대로 올라간다.
        if cfg.get("reel", True):
            _make_reel_draft(cfg, data, items, key, caption, out_dir)
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
