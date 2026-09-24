"""사용법: python poll_telegram.py
channels/*.yaml에 정의된 채널마다 각자의 텔레그램 봇을 폴링합니다.
- 모든 채널: 승인/건너뛰기 버튼 응답을 pending/<slug>/<date>.json에 반영
- source.type이 telegram_inbox인 채널: 새로 들어온 사진/영상 + 설명을 감지해서
  queue/<slug>/에 대기열로 등록합니다 (캡션 작성·게시는 process_queue.py가 매일 하나씩 처리).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

import yaml

from engine import assets, telegram
from engine.config import ROOT

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
VIDEO_EXTS = {".mp4", ".mov"}


def _enqueue_inbox_item(cfg: dict, token: str, chat_id: str, item: dict) -> None:
    slug = cfg["slug"]
    media_path = item["paths"][0]
    ext = media_path.suffix.lower()

    if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
        print(f"  ! [{slug}] 지원하지 않는 파일 형식이라 건너뜁니다: {media_path.name}")
        telegram.notify(token, chat_id, f"⚠️ [{cfg['name']}] 지원하지 않는 파일 형식이에요 — 사진/영상으로 보내주세요.")
        return

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    try:
        media_urls = assets.upload_images([media_path], slug, f"queue/{ts}")
    except Exception as e:
        print(f"  ! [{slug}] 대기열 등록 실패: {e}")
        try:
            telegram.notify(token, chat_id, f"❌ [{cfg['name']}] 대기열 등록 실패: {e}")
        except Exception:
            pass
        return

    queue_dir = ROOT / "queue" / slug
    queue_dir.mkdir(parents=True, exist_ok=True)
    entry_path = queue_dir / f"{ts}-{item['message_id']}.json"
    entry_path.write_text(
        json.dumps(
            {
                "media_url": media_urls[0],
                "media_type": "video" if ext in VIDEO_EXTS else "image",
                "user_caption": item["caption"],
                "message_id": item["message_id"],
                "queued_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    pending_count = len(list(queue_dir.glob("*.json")))
    telegram.notify(
        token,
        chat_id,
        f"📥 [{cfg['name']}] 대기열에 추가했어요 (현재 {pending_count}개 대기 중, 매일 순서대로 하나씩 게시돼요)",
    )
    print(f"  - [{slug}] 대기열에 추가 (총 {pending_count}개)")


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
        _enqueue_inbox_item(cfg, token, chat_id, item)


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
