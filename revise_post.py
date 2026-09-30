"""사용법: python revise_post.py [--plan-only | --apply-plan]

원장님이 승인 대기 게시물에 남긴 말을 담당자가 읽고 처리합니다.

단체 채팅방입니다. 원장님이 말을 던지면 성격에 맞는 담당이 나와서 답합니다.
자기 일이 아니면 맡을 사람에게 넘깁니다.

  편집(김주훈)   캡션 문구, 말투, 해시태그, 사진 위 헤드라인
  디자인(차은우)  카드뉴스의 글자 크기, 색, 여백, 배치
  기획(박서준)   카드에 담을 내용과 순서

처리 방식은 게시물 종류에 따라 다릅니다.
  사진 게시물  원본 사진에 글씨를 다시 얹습니다
  카드뉴스    원본 사진이 없으므로 글에서 처음부터 다시 그립니다

원장님이 기다리는 일이라 빠른 게 중요합니다. 그런데 그림을 다시 그리려면
Playwright 가 필요하고 그 설치에만 37초가 듭니다. 글만 고치는 요청에는
쓸 일이 없는 시간이라 두 단계로 나눴습니다.

  --plan-only   가벼운 도구만으로 판단합니다. 글만 고치면 되는 건 여기서 끝냅니다.
  --apply-plan  그림을 다시 그려야 하는 것만 처리합니다.

아무 것도 안 붙이면 예전처럼 한 번에 다 합니다(사람이 직접 돌릴 때).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import requests
from anthropic import Anthropic

from engine import assets, staff, telegram, trends_sync
from engine.config import ROOT, load_channel
from engine.voice import HSSUP_VOICE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM = """당신은 히썹 인스타그램 계정을 맡은 팀입니다.
원장님이 올라온 게시물을 보고 단체 채팅방에 말을 남겼습니다.

먼저 **누가 맡을 일인지** 고르세요.

{roster}

고른 담당이 되어 답하세요. 담당별 말투:
{voice_note}

이 게시물은 **{kind_label}** 입니다.
{kind_note}

무엇을 채울지:
- `staff`  : editor / designer / planner 중 하나
- `reply`  : 무엇을 어떻게 했는지 한두 줄. 고친 내용을 통째로 다시 쓰지 마세요.
- `caption`: 캡션을 고칠 때만 전문. 안 고치면 빈 문자열.
- `headline`: 사진 위에 얹는 글씨를 바꿀 때만. 카드뉴스에는 쓰지 않습니다.
- `css`    : 카드 디자인을 고칠 때만. 덧씌울 CSS 만 적으세요.
- `cards`  : 카드에 담긴 글을 고칠 때만. 고친 카드만 번호와 함께 적으세요.
- `headline_text`: 표지 제목을 바꿀 때만.

무엇을 원하는지 모르겠으면 전부 비우고 `reply` 로 되물으세요.
할 수 없는 일이면 왜 안 되는지 알려주세요. 다른 사람에게 미루지 마세요.

`reply` 에는 명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요. 한자를 쓰지 마세요.

{voice}

[지금 캡션]
{caption}"""

PHOTO_NOTE = """사진 위에 글씨를 얹은 게시물입니다.
- 캡션을 고치려면 `caption`
- 사진 위 글씨를 바꾸려면 `headline`
- 이 게시물은 찍은 사진이 바탕이라 글자 크기나 색은 바꿀 수 없습니다.
  그런 요청이 오면 왜 안 되는지 알려주세요."""

CARDS_NOTE = """글에서 그려낸 카드뉴스입니다. 원본 사진이 없어 처음부터 다시 그립니다.
- 캡션을 고치려면 `caption`
- 카드의 글자 크기, 색, 굵기, 여백을 바꾸려면 `css` 에 덧씌울 CSS 를 적으세요.
  기본 스타일 뒤에 덧붙습니다. 바꿀 수 있는 값: --accent(강조색), --orange, --ink, --paper
  주요 선택자: .headline(표지 제목) .title(카드 제목) .summary li(설명 줄)
  .why p(요점) .kicker .index li .hl(강조 단어) .card.cover .card.outro
  글자가 배경과 비슷해지거나 카드 밖으로 나가면 자동으로 되돌아갑니다. 과감하게 쓰세요.
- 카드에 담긴 글을 바꾸려면 `cards` 에 고칠 카드만 적으세요.
- 제목에 대괄호를 쓰면 그 부분이 강조색으로 칠해집니다. 한 장에 한 군데만."""

TOOL = {
    "name": "handle",
    "description": "원장님 요청을 처리합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "staff": {"type": "string", "enum": ["editor", "designer", "planner"],
                      "description": "이 요청을 맡을 담당"},
            "reply": {"type": "string", "description": "무엇을 했는지 한두 줄"},
            "caption": {"type": "string", "description": "고친 캡션 전문. 안 고치면 빈 문자열."},
            "headline": {"type": "string", "description": "사진 위 글씨. 카드뉴스에는 쓰지 않음."},
            "css": {"type": "string", "description": "카드 디자인에 덧씌울 CSS. 안 고치면 빈 문자열."},
            "headline_text": {"type": "string", "description": "표지 제목. 안 바꾸면 빈 문자열."},
            "cards": {
                "type": "array",
                "description": "고칠 카드만. 안 고치면 빈 배열.",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "몇 번째 카드인지 (1부터)"},
                        "title": {"type": "string"},
                        "summary": {"type": "array", "items": {"type": "string"}},
                        "why": {"type": "string"},
                    },
                    "required": ["index"],
                },
            },
        },
        "required": ["staff", "reply"],
    },
}


def _clean(text: str) -> str:
    """빈 값을 빈 값으로 받습니다.

    "안 고쳤다" 는 뜻으로 따옴표 두 개만 보내오는 경우가 있었고, 그게 그대로
    캡션으로 저장돼 글이 통째로 날아갔습니다. 따옴표만 남으면 비운 것으로 봅니다.
    """
    out = (text or "").strip()
    while len(out) >= 2 and out[0] == out[-1] and out[0] in "\"'":
        out = out[1:-1].strip()
    return out


def _plan_path() -> Path:
    """단계 사이에 할 일을 넘기는 파일. 같은 실행 안에서만 쓰고 지웁니다."""
    base = os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()
    return Path(base) / "revise_plan.json"


def _is_cards(row: dict) -> bool:
    return (row.get("payload") or {}).get("media_type") == "carousel"


def _rerender_photo(row: dict, headline: str) -> list[str] | None:
    """사진 게시물: 원본을 내려받아 글씨를 다시 얹습니다."""
    payload = row.get("payload") or {}
    source_urls = payload.get("source_urls") or ([payload["source_url"]] if payload.get("source_url") else [])
    if not source_urls:
        print("  ! 원본 주소가 없어 그림을 다시 만들 수 없습니다")
        return None
    source_url = source_urls[0]  # 글씨는 표지에만 얹혀 있다

    cfg = load_channel(row["channel"])
    overlay_cfg = cfg.get("overlay") or {}
    is_video = payload.get("media_type") == "video"

    resp = requests.get(source_url, timeout=120)
    if resp.status_code != 200:
        print(f"  ! 원본을 내려받지 못했습니다: {resp.status_code} (이미 지워졌을 수 있습니다)")
        return None

    ext = Path(urlparse(source_url).path).suffix or (".mp4" if is_video else ".jpg")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"source{ext}"
        src.write_bytes(resp.content)
        out = Path(tmp) / f"revised{'.mp4' if is_video else '.png'}"

        if is_video:
            from engine.video_overlay import render_video_overlay

            logo = overlay_cfg.get("logo_video") or overlay_cfg.get("logo")
            render_video_overlay(
                video_path=src, headline=headline, out_path=out,
                logo_path=(ROOT / logo) if logo else None,
                logo_text=overlay_cfg.get("logo_text"),
                brand_color=overlay_cfg.get("brand_color", "#fa5500"),
            )
        else:
            from engine.overlay import render_overlay

            logo = overlay_cfg.get("logo")
            render_overlay(
                photo_path=src, headline=headline, out_path=out,
                logo_path=(ROOT / logo) if logo else None,
                logo_text=overlay_cfg.get("logo_text"),
                brand_color=overlay_cfg.get("brand_color", "#fa5500"),
            )

        new_cover = assets.upload_images([out], row["channel"], f"revised/{row['ref_key']}")
        if not new_cover:
            return None
        rest = (row.get("image_urls") or [])[1:]
        return new_cover + rest


def _redraw_cards(row: dict, result: dict) -> tuple[list[str] | None, str]:
    """카드뉴스: 내용이나 디자인을 고쳐 처음부터 다시 그립니다.

    돌려주는 값은 (사진 주소들, 답에 덧붙일 말) 입니다.
    """
    from engine import cards as cards_mod
    from engine.design import design_path, read_design, write_design

    cfg = load_channel(row["channel"])
    css, card_edits, headline_text = result["css"], result["cards"], result["headline_text"]

    if card_edits or headline_text:
        data = cards_mod.load_cards(cfg)
        if headline_text:
            data["headline"] = headline_text
        for edit in card_edits:
            i = int(edit.get("index", 0)) - 1
            if not (0 <= i < len(data["items"])):
                continue
            for key in ("title", "summary", "why"):
                if edit.get(key):
                    data["items"][i][key] = edit[key]
        cards_mod.save_cards(cfg, data)

    before_css = read_design(cfg["slug"])
    if css:
        write_design(cfg["slug"], f"{before_css}\n\n{css}".strip() if before_css else css)

    urls, problems = cards_mod.redraw(cfg, row["ref_key"])
    if not problems:
        return urls, ""

    # 깨졌으면 디자인을 고치기 전으로 되돌리고 한 번 더 그립니다.
    if css:
        if before_css:
            write_design(cfg["slug"], before_css)
        elif design_path(cfg["slug"]).exists():
            design_path(cfg["slug"]).unlink()
        urls, problems = cards_mod.redraw(cfg, row["ref_key"])
        if not problems:
            return urls, "\n\n(그렇게 바꾸면 카드가 깨져서 되돌렸어요. 다르게 말씀해 주세요.)"

    return None, f"\n\n(카드를 다시 그리지 못했어요: {problems[0]})"


def _sync_pending_file(row: dict, caption: str | None, image_urls: list[str] | None) -> None:
    """게시는 pending 파일을 보고 하므로 거기에도 반영합니다."""
    path = ROOT / "pending" / row["channel"] / f"{row['ref_key']}.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    if caption:
        data["caption"] = caption
    if image_urls:
        data["image_urls"] = image_urls
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _notify(channel: str, text: str) -> None:
    try:
        cfg = load_channel(channel)
        tg = cfg.get("telegram") or {}
        token = os.environ.get(tg.get("bot_token_env", ""))
        if token:
            telegram.notify(token, str(tg["chat_id"]), text)
    except Exception as e:
        print(f"  ! 텔레그램 알림 실패: {e}")


def _ask(client, model: str, row: dict, msg: dict) -> dict:
    """단체 채팅방에 던져진 말을 누가 맡고 어떻게 할지 정합니다."""
    thread = trends_sync.fetch_approval_thread(row["id"])
    messages = [
        {"role": "assistant" if t["role"] == "staff" else "user", "content": t["body"]}
        for t in thread
    ]
    if not messages or messages[-1]["role"] != "user":
        messages.append({"role": "user", "content": msg["body"]})

    cards = _is_cards(row)
    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        system=SYSTEM.format(
            roster=staff.roster_text(),
            voice_note="\n".join(f"  {v['name']} 팀장: {v['voice']}" for v in staff.STAFF.values()),
            kind_label="카드뉴스" if cards else "사진 게시물",
            kind_note=CARDS_NOTE if cards else PHOTO_NOTE,
            voice=HSSUP_VOICE,
            caption=row.get("body") or "",
        ),
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "handle"},
        messages=messages,
    )
    out = next(b for b in resp.content if b.type == "tool_use").input
    return {
        "staff": out.get("staff") or staff.DEFAULT,
        "reply": (out.get("reply") or "").strip(),
        "caption": _clean(out.get("caption")),
        "headline": _clean(out.get("headline")),
        "css": (out.get("css") or "").strip(),
        "cards": out.get("cards") or [],
        "headline_text": _clean(out.get("headline_text")),
    }


def _needs_render(row: dict, result: dict) -> bool:
    """그림을 다시 그려야 하는 요청인지. 무거운 도구가 필요한 경우입니다."""
    if _is_cards(row):
        return bool(result["css"] or result["cards"] or result["headline_text"])
    return bool(result["headline"])


def _do_render(row: dict, result: dict) -> tuple[list[str] | None, str]:
    """그림을 다시 만듭니다. 게시물 종류에 따라 방식이 다릅니다."""
    if _is_cards(row):
        return _redraw_cards(row, result)

    urls = _rerender_photo(row, result["headline"])
    if urls:
        return urls, f"\n\n(사진 위 글씨를 「{result['headline']}」 로 바꿨어요)"
    return None, "\n\n(그림은 다시 만들지 못했어요. 원본을 찾을 수 없습니다.)"


def _handoff(approval_id: int, to_staff: str) -> None:
    """맡던 사람이 다른 담당에게 넘기는 말. 누가 왜 나오는지 보이게 합니다."""
    thread = trends_sync.fetch_approval_thread(approval_id)
    last = next((t for t in reversed(thread) if t["role"] == "staff" and t.get("staff")), None)
    if not last or last["staff"] == to_staff:
        return
    nxt = staff.get(to_staff)
    trends_sync.create_approval_message(
        approval_id, "staff",
        f"이건 {nxt['role']} 쪽이라 {nxt['name']} 팀장님께 넘길게요.",
        staff_key=last["staff"],
    )
    print(f"  - {staff.get(last['staff'])['name']} → {nxt['name']} 넘김")


def _finish(row: dict, msg_id: int, result: dict, image_urls: list[str] | None) -> None:
    """고친 내용을 반영하고 담당자 이름으로 답을 남깁니다."""
    approval_id = row["id"]
    caption = result["caption"]
    try:
        trends_sync.update_approval_content(approval_id, body=caption or None, image_urls=image_urls)
        _sync_pending_file(row, caption or None, image_urls)
    except Exception as e:
        print(f"  ! 반영 실패(approval {approval_id}): {e}")

    _handoff(approval_id, result["staff"])

    who = staff.get(result["staff"])
    trends_sync.create_approval_message(approval_id, "staff", result["reply"], staff_key=result["staff"])
    trends_sync.mark_approval_message_answered(msg_id)
    _notify(row["channel"], f"✏️ {who['name']} 팀장\n\n{result['reply']}")
    print(f"  - {who['name']} 팀장이 처리 완료 (approval {approval_id})")


def _set_output(name: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def _apply_plan() -> int:
    """적어둔 할 일(그림 다시 그리기)을 처리합니다."""
    path = _plan_path()
    if not path.exists():
        print("다시 그릴 그림이 없습니다.")
        return 0

    for e in json.loads(path.read_text(encoding="utf-8")):
        row, result = e["row"], e["result"]
        try:
            urls, note = _do_render(row, result)
        except Exception as ex:
            print(f"  ! 그림 다시 그리기 실패: {ex}")
            urls, note = None, f"\n\n(그림을 다시 만들지 못했어요: {ex})"
        result["reply"] += note
        _finish(row, e["message_id"], result, urls)

    path.unlink()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-only", action="store_true",
                        help="글만 고치는 건 처리하고, 그림 작업은 적어만 둔다")
    parser.add_argument("--apply-plan", action="store_true",
                        help="적어둔 그림 작업을 처리한다")
    args = parser.parse_args()

    if args.apply_plan:
        return _apply_plan()

    pending = trends_sync.fetch_unanswered_approval_messages()
    if not pending:
        print("처리할 요청이 없습니다.")
        _set_output("needs_render", "false")
        return 0

    client = Anthropic()
    model = os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL)
    deferred = []

    for msg in pending:
        row = msg.get("ai_approvals") or {}
        approval_id = row.get("id")
        if not approval_id or row.get("status") != "awaiting":
            trends_sync.mark_approval_message_answered(msg["id"])
            continue

        try:
            result = _ask(client, model, row, msg)
        except Exception as e:
            print(f"  ! 답을 만들지 못했습니다(approval {approval_id}): {e}")
            continue

        who = staff.get(result["staff"])
        print(f"  - {who['name']} 팀장이 맡음 (approval {approval_id})")

        if _needs_render(row, result) and args.plan_only:
            deferred.append({"row": row, "message_id": msg["id"], "result": result})
            print("    그림 작업으로 넘김")
            continue

        urls, note = (None, "")
        if _needs_render(row, result):
            try:
                urls, note = _do_render(row, result)
            except Exception as e:
                print(f"  ! 그림 다시 그리기 실패: {e}")
                note = f"\n\n(그림을 다시 만들지 못했어요: {e})"
        result["reply"] += note

        _finish(row, msg["id"], result, urls)

    if args.plan_only:
        if deferred:
            _plan_path().write_text(json.dumps(deferred, ensure_ascii=False), encoding="utf-8")
        _set_output("needs_render", "true" if deferred else "false")

    return 0


if __name__ == "__main__":
    sys.exit(main())
