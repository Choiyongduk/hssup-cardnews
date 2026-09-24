"""사용법: python process_queue.py
channels/*.yaml의 telegram_inbox 채널마다 queue/<slug>/에서 가장 오래된 대기 항목 1개를 꺼내
캡션·헤드라인 작성 → (설정된 경우) 브랜드 오버레이 렌더링(사진/영상 모두) → 업로드 → 승인 요청 전송까지 처리합니다.
매일 정해진 시간(cron-job.org)에 실행되어 "하루 하나씩 순서대로 게시" 흐름을 만듭니다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

from engine import assets, media_caption, telegram
from engine.config import ROOT
from engine.overlay import render_overlay
from engine.video_overlay import extract_frame, render_video_overlay


def _process_one(cfg: dict, token: str, chat_id: str, entry_path: Path) -> None:
    slug = cfg["slug"]
    entry = json.loads(entry_path.read_text(encoding="utf-8"))
    date_key = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    print(f"  - [{slug}] 대기열에서 꺼냄: {entry_path.name}")

    is_video = entry.get("media_type") == "video"
    ext = Path(urlparse(entry["media_url"]).path).suffix or (".mp4" if is_video else ".jpg")

    tmp_dir = ROOT / "state" / "queue_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    media_path = tmp_dir / f"{slug}-{date_key}{ext}"

    try:
        resp = requests.get(entry["media_url"], timeout=30)
        resp.raise_for_status()
        media_path.write_bytes(resp.content)

        caption_source_path = media_path
        if is_video:
            caption_source_path = extract_frame(media_path, tmp_dir / f"{slug}-{date_key}_frame.jpg")

        post = media_caption.write_post(
            caption_source_path, entry.get("user_caption", ""), cfg.get("topic", cfg["name"]), cfg.get("hashtags", [])
        )
        caption = post["caption"]

        post_paths = [media_path]
        overlay_cfg = cfg.get("overlay")
        if overlay_cfg:
            if is_video:
                rendered = render_video_overlay(
                    video_path=media_path,
                    headline=post["headline"],
                    out_path=media_path.with_name(media_path.stem + "_post.mp4"),
                    logo_path=(ROOT / overlay_cfg["logo"]) if overlay_cfg.get("logo") else None,
                    logo_text=overlay_cfg.get("logo_text"),
                    brand_color=overlay_cfg.get("brand_color", "#ff7a00"),
                )
            else:
                rendered = render_overlay(
                    photo_path=media_path,
                    headline=post["headline"],
                    out_path=media_path.with_name(media_path.stem + "_post.png"),
                    logo_path=(ROOT / overlay_cfg["logo"]) if overlay_cfg.get("logo") else None,
                    logo_text=overlay_cfg.get("logo_text"),
                    brand_color=overlay_cfg.get("brand_color", "#ff7a00"),
                )
            post_paths = [rendered]

        media_urls = assets.upload_images(post_paths, slug, date_key)
    except Exception as e:
        print(f"  ! [{slug}] 처리 실패: {e}")
        try:
            telegram.notify(token, chat_id, f"❌ [{cfg['name']}] 대기열 처리 중 오류: {e}")
        except Exception:
            pass
        return

    telegram.create_pending(slug, date_key, media_urls, caption, source_message_id=entry.get("message_id"))
    telegram.send_preview(token, chat_id, post_paths, caption, slug, date_key)
    entry_path.unlink()
    print(f"  - [{slug}] {date_key} 미리보기 전송 완료, 대기열에서 제거")


def _process_channel(path) -> None:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    tg_cfg = cfg.get("telegram")
    is_inbox = (cfg.get("source") or {}).get("type") == "telegram_inbox"
    if not tg_cfg or not is_inbox:
        return

    token = os.environ.get(tg_cfg["bot_token_env"])
    if not token:
        print(f"  ! [{cfg['slug']}] {tg_cfg['bot_token_env']} 없음, 건너뜀")
        return
    chat_id = str(tg_cfg["chat_id"])

    queue_dir = ROOT / "queue" / cfg["slug"]
    entries = sorted(queue_dir.glob("*.json")) if queue_dir.exists() else []
    if not entries:
        print(f"  - [{cfg['slug']}] 대기열 비어있음")
        return

    _process_one(cfg, token, chat_id, entries[0])


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
