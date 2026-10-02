"""사용법: python publish_instagram.py
pending/<slug>/<date>.json 중 status가 "approved"인 항목을 찾아
(image_urls·caption은 render.py가 렌더링 시점에 이미 채워둔 값) Instagram Graph API로 캐러셀 게시합니다.
성공/실패 모두 pending 파일에 기록하고 텔레그램으로 알립니다."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

from engine import instagram, trends_sync
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


def _drop_original(slug: str, data: dict) -> None:
    """앱에서 올린 원본을 지웁니다.

    게시하거나 건너뛰기 전까지는 남겨둡니다. 승인 전에 "이렇게 바꿔줘" 라고 하면
    오버레이를 다시 입혀야 하는데, 글자가 이미 박힌 결과물 위에 또 입힐 수는 없기 때문입니다.
    """
    paths = data.get("storage_paths") or ([data["storage_path"]] if data.get("storage_path") else [])
    if not paths:
        return
    for path in paths:
        try:
            trends_sync.delete_storage_object("content-media", path)
        except Exception as e:
            print(f"  ! {slug}: 원본 삭제 실패(게시에는 지장 없음): {e}")
    print(f"  - {slug}: 앱에 올린 원본 {len(paths)}건 삭제")


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
        is_video = image_urls[0].lower().endswith((".mp4", ".mov"))
        if is_video:
            # 카드뉴스 릴스(engine/reel.py COVER_FRAME)는 표지 글이 3초쯤 다 떠오른다. 그 장면을 표지로.
            # reel 을 import 하지 않는다. 게시 작업엔 Playwright 를 깔지 않아서.
            offset = 3000 if str(date).endswith("-reel") else None
            media_id = instagram.publish_video(business_id, token, image_urls[0], caption, offset)
        else:
            media_id = instagram.publish_carousel(business_id, token, image_urls, caption)
    except Exception as e:
        _write_status(entry_path, "failed", error=str(e))
        _notify(cfg, f"❌ [{cfg['name']}] {date} 게시 실패: {e}")
        return

    _write_status(entry_path, "published", media_id=media_id)
    _notify(cfg, f"✅ [{cfg['name']}] {date} 인스타그램 게시 완료 (media_id: {media_id})")
    _drop_original(slug, data)

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


def _apply_app_decisions() -> dict[tuple[str, str], int]:
    """앱(AI 오피스)에서 내린 결정을 pending 파일에 반영합니다.

    게시 자체는 아래 기존 흐름이 그대로 처리하고, 여기서는 상태만 맞춰줍니다.
    반환: 게시까지 지켜봐야 할 {(slug, date): 승인행 id}
    """
    try:
        rows = trends_sync.fetch_decided_approvals(kind="post")
    except Exception as e:
        print(f"  ! 앱 승인 목록 조회 실패: {e}")
        return {}

    watching: dict[tuple[str, str], int] = {}
    for row in rows:
        slug, date = row["channel"], row["ref_key"]
        entry_path = ROOT / "pending" / slug / f"{date}.json"
        if not entry_path.exists():
            trends_sync.update_approval(row["id"], "failed", "대기 기록을 찾을 수 없습니다")
            continue

        data = json.loads(entry_path.read_text(encoding="utf-8"))
        if data.get("status") not in ("awaiting_approval", "approved", "skipped"):
            # 이미 게시됐거나 실패한 건은 건드리지 않습니다.
            trends_sync.update_approval(row["id"], data.get("status") or "failed")
            continue

        if row["status"] == "skipped":
            _write_status(entry_path, "skipped")
            _drop_original(slug, data)
            trends_sync.update_approval(row["id"], "skipped")
            continue

        # 원장이 앱에서 캡션을 고쳤으면 그 내용으로 게시합니다.
        edited = row.get("body")
        if edited and edited != data.get("caption"):
            _write_status(entry_path, "approved", caption=edited)
        else:
            _write_status(entry_path, "approved")
        watching[(slug, date)] = row["id"]

    return watching


def main() -> int:
    watching = _apply_app_decisions()

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

        row_id = watching.get((slug, date))
        if row_id:
            result = json.loads(entry_path.read_text(encoding="utf-8"))
            published = result.get("status") == "published"
            trends_sync.update_approval(
                row_id, "sent" if published else "failed", None if published else result.get("error")
            )

    if count == 0:
        print("게시 대기 중인 항목이 없습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
