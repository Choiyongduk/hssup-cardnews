"""사용법: python poll_telegram.py
channels/*.yaml에 정의된 채널마다 각자의 텔레그램 봇을 폴링합니다.
- 모든 채널: 승인/건너뛰기 버튼 응답을 pending/<slug>/<date>.json에 반영
- source.type이 telegram_inbox인 채널: 새로 들어온 사진/영상 + 설명을 감지해서
  Claude로 캡션을 작성하고, 공개 저장소에 올린 뒤, 승인 대기 미리보기를 다시 전송합니다.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import yaml

from engine import assets, media_caption, telegram
from engine.config import ROOT
from engine.overlay import render_overlay

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def _handle_inbox_item(cfg: dict, token: str, chat_id: str, item: dict) -> None:
    slug = cfg["slug"]
    date_key = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    print(f"  - [{slug}] 새 미디어 수신, 캡션 작성 중...")

    photo_path = item["paths"][0]
    overlay_cfg = cfg.get("overlay")
    is_image = photo_path.suffix.lower() in IMAGE_EXTS

    try:
        post = media_caption.write_post(
            photo_path, item["caption"], cfg.get("topic", cfg["name"]), cfg.get("hashtags", [])
        )
        caption = post["caption"]

        post_paths = item["paths"]
        if overlay_cfg and is_image:
            rendered = render_overlay(
                photo_path=photo_path,
                headline=post["headline"],
                out_path=photo_path.with_name(photo_path.stem + "_post.png"),
                logo_path=(ROOT / overlay_cfg["logo"]) if overlay_cfg.get("logo") else None,
                logo_text=overlay_cfg.get("logo_text"),
                brand_color=overlay_cfg.get("brand_color", "#ff7a00"),
            )
            post_paths = [rendered]

        image_urls = assets.upload_images(post_paths, slug, date_key)
    except Exception as e:
        print(f"  ! [{slug}] 처리 실패: {e}")
        try:
            telegram.notify(token, chat_id, f"❌ [{cfg['name']}] 사진 처리 중 오류: {e}")
        except Exception:
            pass
        return

    telegram.create_pending(
        slug, date_key, image_urls, caption, source_message_id=item["message_id"]
    )
    telegram.send_preview(token, chat_id, post_paths, caption, slug, date_key)
    print(f"  - [{slug}] {date_key} 미리보기 전송 완료")


def _process_channel(path) -> None:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    tg_cfg = cfg.get("telegram")
    if not tg_cfg:
        return

    token = os.environ.get(tg_cfg["bot_token_env"])
    if not token:
        print(f"  ! [{cfg['slug']}] {tg_cfg['bot_token_env']} 없음, 건너뜀")
        return
    chat_id = str(tg_cfg["chat_id"])

    is_inbox = (cfg.get("source") or {}).get("type") == "telegram_inbox"
    result = telegram.poll(token, bot_name=cfg["slug"], inbox_chat_id=chat_id if is_inbox else None)

    for d in result["decided"]:
        print(f"  - [{cfg['slug']}] {d['date']}: {d['status']}")

    for item in result["inbox"]:
        _handle_inbox_item(cfg, token, chat_id, item)


def main() -> int:
    channels_dir = ROOT / "channels"
    if not channels_dir.exists():
        print("channels/ 폴더가 없습니다.")
        return 0

    for path in sorted(channels_dir.glob("*.yaml")):
        _process_channel(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
