"""사용법: python publish_instagram.py
pending/<slug>/<date>.json 중 status가 "approved"인 항목을 찾아
(image_urls·caption은 render.py가 렌더링 시점에 이미 채워둔 값) Instagram Graph API로 캐러셀 게시합니다.
성공/실패 모두 pending 파일에 기록하고 텔레그램으로 알립니다."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

from engine import instagram
from engine.config import ROOT, load_channel


def _notify(cfg: dict, text: str) -> None:
    tg_cfg = cfg.get("telegram")
    if not tg_cfg:
        return
    token = os.environ.get(tg_cfg["bot_token_env"])
    if not token:
        return
    try:
        from engine.telegram import notify

        notify(token, str(tg_cfg["chat_id"]), text)
    except Exception as e:
        print(f"  ! 텔레그램 알림 실패: {e}")


def _write_status(path, status: str, **extra) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = status
    data["published_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    data.update(extra)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _publish_one(slug: str, date: str, entry_path, data: dict) -> None:
    cfg = load_channel(slug)
    ig_cfg = cfg.get("instagram")
    if not ig_cfg:
        print(f"  ! {slug}: channels/{slug}.yaml에 instagram 설정이 없어 건너뜁니다.")
        return

    business_id = os.environ.get(ig_cfg["business_id_env"])
    token = os.environ.get(ig_cfg["token_env"])
    if not business_id or not token:
        print(f"  ! {slug}: {ig_cfg['business_id_env']}/{ig_cfg['token_env']} 환경변수가 없어 건너뜁니다.")
        return

    image_urls = data.get("image_urls")
    caption = data.get("caption")
    if not image_urls or not caption:
        _write_status(entry_path, "failed", error="pending 레코드에 image_urls/caption이 없습니다.")
        _notify(cfg, f"❌ [{cfg['name']}] {date} 게시 실패: 이미지/캡션 정보가 없습니다.")
        return

    try:
        media_id = instagram.publish_carousel(business_id, token, image_urls, caption)
    except Exception as e:
        _write_status(entry_path, "failed", error=str(e))
        _notify(cfg, f"❌ [{cfg['name']}] {date} 게시 실패: {e}")
        return

    _write_status(entry_path, "published", media_id=media_id)
    _notify(cfg, f"✅ [{cfg['name']}] {date} 인스타그램 게시 완료 (media_id: {media_id})")

    if slug == "hssup-news":
        try:
            from engine.trends_sync import create_trend

            create_trend(
                title=data.get("headline") or cfg["name"],
                content=data.get("one_liner"),
                image_urls=image_urls,
                category="업계소식",
            )
            print(f"  - {slug}: 앱 트렌드 속보에도 등록 완료")
        except Exception as e:
            print(f"  ! {slug}: 앱 트렌드 속보 등록 실패(인스타 게시는 정상 완료됨): {e}")


def main() -> int:
    pending_dir = ROOT / "pending"
    if not pending_dir.exists():
        print("게시 대기 중인 항목이 없습니다.")
        return 0

    count = 0
    for entry_path in sorted(pending_dir.glob("*/*.json")):
        slug = entry_path.parent.name
        date = entry_path.stem
        data = json.loads(entry_path.read_text(encoding="utf-8"))
        if data.get("status") != "approved":
            continue
        print(f"[{slug}] {date} 게시 시작")
        _publish_one(slug, date, entry_path, data)
        count += 1

    if count == 0:
        print("게시 대기 중인 항목이 없습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
