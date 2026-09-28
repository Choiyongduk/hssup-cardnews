"""사용법: python revise_post.py

승인 대기 중인 게시물에 원장님이 남긴 수정 요청을 처리합니다.

- 캡션만 고치면 되는 요청은 글만 새로 씁니다.
- 헤드라인이나 로고처럼 그림을 건드려야 하는 요청은 오버레이를 다시 입힙니다.
  이때 앱에 올린 원본이 필요해서, 게시하거나 건너뛰기 전까지 원본을 지우지 않습니다.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import requests
from anthropic import Anthropic

from engine import assets, telegram, trends_sync
from engine.config import ROOT, load_channel
from engine.voice import HSSUP_VOICE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM = """당신은 히썹 인스타그램 계정의 콘텐츠 편집자입니다.
원장님이 올라온 게시물을 보고 수정을 요청했습니다.

판단할 것 — 요청이 **캡션 글만 고치면 되는 것**인지, **그림(헤드라인, 로고)까지 다시 만들어야 하는 것**인지.
- 캡션 표현, 길이, 말투, 해시태그 → `caption` 만 채우세요.
- 사진이나 영상 위에 얹힌 글씨를 바꿔달라는 것 → `headline` 도 함께 채우세요. 그림을 다시 만듭니다.
- 질문이거나 무엇을 원하는지 모르겠으면 둘 다 비우고 `reply` 로 되물으세요.

`caption` 작성 원칙:
- 요청한 부분만 고치고 나머지는 그대로 두세요.
- 원문에 없는 사실을 지어내지 마세요.
- 해시태그는 캡션 끝에 그대로 유지하세요.
- 아래 말투를 따르세요.

`headline` 은 사진 위에 큰 글씨로 얹는 짧은 문구입니다. 2~6단어(한글 12자 내외),
완전한 문장이나 존댓말체로 쓰지 마세요. 여기엔 아래 말투를 적용하지 않습니다.

`reply` 는 무엇을 바꿨는지 한두 줄로만 알리세요. 고친 내용을 통째로 다시 쓰지 마세요.
명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요. 한자를 쓰지 마세요.

{voice}

[지금 캡션]
{caption}"""

TOOL = {
    "name": "revise",
    "description": "수정 결과를 제출합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reply": {"type": "string", "description": "무엇을 바꿨는지 한두 줄"},
            "caption": {"type": "string", "description": "고친 캡션 전문. 캡션을 안 고치면 빈 문자열."},
            "headline": {"type": "string", "description": "그림 위 글씨를 바꿀 때만. 아니면 빈 문자열."},
        },
        "required": ["reply"],
    },
}


def _rerender(row: dict, headline: str) -> list[str] | None:
    """원본을 내려받아 오버레이를 다시 입히고 에셋 저장소에 올립니다."""
    payload = row.get("payload") or {}
    source_url = payload.get("source_url")
    if not source_url:
        print("  ! 원본 주소가 없어 그림을 다시 만들 수 없습니다")
        return None

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

        return assets.upload_images([out], row["channel"], f"revised/{row['ref_key']}")


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


def main() -> int:
    pending = trends_sync.fetch_unanswered_approval_messages()
    if not pending:
        print("처리할 수정 요청이 없습니다.")
        return 0

    client = Anthropic()
    model = os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL)

    for msg in pending:
        row = msg.get("ai_approvals") or {}
        approval_id = row.get("id")
        if not approval_id or row.get("status") != "awaiting":
            trends_sync.mark_approval_message_answered(msg["id"])
            continue

        thread = trends_sync.fetch_approval_thread(approval_id)
        messages = [
            {"role": "assistant" if t["role"] == "staff" else "user", "content": t["body"]}
            for t in thread
        ]
        if not messages or messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": msg["body"]})

        try:
            resp = client.messages.create(
                model=model,
                max_tokens=4000,
                system=SYSTEM.format(voice=HSSUP_VOICE, caption=row.get("body") or ""),
                tools=[TOOL],
                tool_choice={"type": "tool", "name": "revise"},
                messages=messages,
            )
            tool_use = next(b for b in resp.content if b.type == "tool_use")
            reply = (tool_use.input.get("reply") or "").strip()
            caption = (tool_use.input.get("caption") or "").strip()
            headline = (tool_use.input.get("headline") or "").strip()
        except Exception as e:
            print(f"  ! 수정안 작성 실패(approval {approval_id}): {e}")
            continue

        image_urls = None
        if headline:
            try:
                image_urls = _rerender(row, headline)
                if image_urls:
                    reply += f"\n\n(그림을 다시 만들었어요 — 헤드라인 「{headline}」)"
                else:
                    reply += "\n\n(그림은 다시 만들지 못했어요. 원본을 찾을 수 없습니다.)"
            except Exception as e:
                print(f"  ! 그림 다시 만들기 실패: {e}")
                reply += f"\n\n(그림을 다시 만들지 못했어요: {e})"

        try:
            trends_sync.update_approval_content(
                approval_id, body=caption or None, image_urls=image_urls
            )
            _sync_pending_file(row, caption or None, image_urls)
        except Exception as e:
            print(f"  ! 반영 실패(approval {approval_id}): {e}")

        trends_sync.create_approval_message(approval_id, "staff", reply)
        trends_sync.mark_approval_message_answered(msg["id"])
        _notify(row["channel"], f"✏️ 수정 반영했어요\n\n{reply}")
        print(f"  - 수정 처리 완료 (approval {approval_id})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
