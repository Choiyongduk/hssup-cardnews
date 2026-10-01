"""사용법: python process_queue.py [--urgent]

channels/*.yaml의 telegram_inbox 채널마다 queue/<slug>/에서 가장 오래된 대기 항목 1개를 꺼내
캡션·헤드라인 작성 → (설정된 경우) 브랜드 오버레이 렌더링(사진/영상 모두) → 업로드 → 승인 요청 전송까지 처리합니다.
매일 정해진 시간(cron-job.org)에 실행되어 "하루 하나씩 순서대로 게시" 흐름을 만듭니다.

--urgent 는 앱에서 "지금 바로" 로 올린 것만 골라 전부 처리합니다.
원장님이 기다리고 있는 일이라 몇 분마다 호출됩니다. 급한 게 없으면 아무것도 하지 않습니다.
급하게 처리해도 인스타에 바로 올라가지는 않습니다 — 승인 요청까지만 앞당깁니다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

from engine import assets, free_design, media_caption, telegram, trends_sync
from engine.config import ROOT
from engine.overlay import render_overlay
from engine.video_overlay import extract_frame, render_video_overlay


def _render_style(entry: dict, slug: str, date_key: str, photo: Path, headline: str) -> Path | None:
    """올릴 때 고른 저장 디자인으로 그립니다. 못 그리면 None — 기본 틀로 넘어갑니다.

    그린 HTML 은 이 게시물 몫으로 떠둡니다. 시안 대화에서 "제목 더 크게" 하면
    기본 틀이 아니라 이 디자인 위에서 고쳐야 하기 때문입니다.
    """
    style_id = entry.get("style_id")
    if not style_id:
        return None
    style = trends_sync.fetch_style(style_id)
    if not style:
        print(f"  ! 저장한 디자인({style_id})을 찾지 못해 기본 틀로 그립니다")
        return None
    out = photo.with_name(photo.stem + "_post.png")
    try:
        problems = free_design.apply_style(style["html"], style.get("fonts") or [], [photo], headline, out)
    except Exception as e:
        print(f"  ! 「{style['name']}」 디자인으로 그리지 못했습니다: {e}")
        return None
    if problems:
        print(f"  ! 「{style['name']}」 디자인에 걸린 것: {problems} (그대로 씁니다)")
    free_design.save(slug, date_key, free_design.with_headline(style["html"], headline), style.get("fonts") or [])
    print(f"  - 「{style['name']}」 디자인으로 그림")
    return out


def _process_one(cfg: dict, token: str, chat_id: str, entry_path: Path) -> None:
    slug = cfg["slug"]
    entry = json.loads(entry_path.read_text(encoding="utf-8"))
    date_key = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    print(f"  - [{slug}] 대기열에서 꺼냄: {entry_path.name}")

    is_video = entry.get("media_type") == "video"
    media_urls = entry.get("media_urls") or [entry["media_url"]]

    tmp_dir = ROOT / "state" / "queue_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 여러 장이면 첫 장이 표지다. 캡션도 오버레이도 첫 장을 기준으로 한다.
        media_paths = []
        for i, url in enumerate(media_urls[:10]):  # 인스타 캐러셀 최대 10장
            ext = Path(urlparse(url).path).suffix or (".mp4" if is_video else ".jpg")
            suffix = "" if i == 0 else f"-{i}"
            dest = tmp_dir / f"{slug}-{date_key}{suffix}{ext}"
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            media_paths.append(dest)
        media_path = media_paths[0]

        caption_source_path = media_path
        if is_video:
            caption_source_path = extract_frame(media_path, tmp_dir / f"{slug}-{date_key}_frame.jpg")

        post = media_caption.write_post(
            caption_source_path, entry.get("user_caption", ""), cfg.get("topic", cfg["name"]), cfg.get("hashtags", [])
        )
        caption = post["caption"]

        post_paths = list(media_paths)
        overlay_cfg = cfg.get("overlay")
        if overlay_cfg:
            if is_video:
                video_logo = overlay_cfg.get("logo_video") or overlay_cfg.get("logo")
                rendered = render_video_overlay(
                    video_path=media_path,
                    headline=post["headline"],
                    out_path=media_path.with_name(media_path.stem + "_post.mp4"),
                    logo_path=(ROOT / video_logo) if video_logo else None,
                    logo_text=overlay_cfg.get("logo_text"),
                    brand_color=overlay_cfg.get("brand_color", "#fa5500"),
                )
            else:
                rendered = _render_style(entry, slug, date_key, media_path, post["headline"])
                if not rendered:
                    rendered = render_overlay(
                        photo_path=media_path,
                        headline=post["headline"],
                        out_path=media_path.with_name(media_path.stem + "_post.png"),
                        logo_path=(ROOT / overlay_cfg["logo"]) if overlay_cfg.get("logo") else None,
                        logo_text=overlay_cfg.get("logo_text"),
                        brand_color=overlay_cfg.get("brand_color", "#fa5500"),
                    )
            # 표지에만 헤드라인을 얹는다. 뒷장은 원본 그대로 넘어간다.
            post_paths = [rendered] + media_paths[1:]

        post_urls = assets.upload_images(post_paths, slug, date_key)
    except Exception as e:
        print(f"  ! [{slug}] 처리 실패: {e}")
        try:
            telegram.notify(token, chat_id, f"❌ [{cfg['name']}] 대기열 처리 중 오류: {e}")
        except Exception:
            pass
        return

    telegram.create_pending(
        slug, date_key, post_urls, caption,
        source_message_id=entry.get("message_id"),
        storage_path=entry.get("storage_path"),
        storage_paths=entry.get("storage_paths"),
        source_url=entry.get("media_url"),
        source_urls=media_urls,
    )
    telegram.send_preview(token, chat_id, post_paths, caption, slug, date_key)
    # 앱에서도 승인할 수 있게 같은 건을 올립니다. 앱 쪽이 검증되면 텔레그램을 걷어냅니다.
    try:
        trends_sync.create_approval(
            kind="post",
            channel=slug,
            ref_key=date_key,
            title=f"{cfg['name']} 게시 승인",
            body=caption,
            image_urls=post_urls,
            payload={
                "storage_path": entry.get("storage_path"),
                "storage_paths": entry.get("storage_paths"),
                "source_url": entry.get("media_url"),
                "source_urls": media_urls,
                "media_type": entry.get("media_type"),
            },
        )
    except Exception as e:
        print(f"  ! [{slug}] 앱 승인 등록 실패: {e}")

    entry_path.unlink()
    print(f"  - [{slug}] {date_key} 미리보기 전송 완료, 대기열에서 제거")


def _drain_app_queue() -> None:
    """앱에서 올린 소재를 파일 대기열로 옮깁니다.

    여기서 형식을 맞춰두면 텔레그램으로 온 것과 똑같이 처리됩니다.
    Supabase 원본은 오버레이를 입혀 에셋 저장소에 올린 뒤 지웁니다 — 남겨두면 용량만 찹니다.
    """
    rows = trends_sync.fetch_media_queue()
    if not rows:
        return

    # 한 번에 고른 사진들은 같은 group_key 를 갖는다. 그런 것끼리 묶어 한 게시물로 만든다.
    # group_key 가 없는 건 예전에 올린 것이라 id 를 묶음으로 친다.
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row.get("group_key") or f"id{row['id']}", []).append(row)

    for key, members in groups.items():
        members.sort(key=lambda r: (r.get("sort_order") or 0, r["id"]))
        head = members[0]
        slug = head["channel"]
        queue_dir = ROOT / "queue" / slug
        queue_dir.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
        entry_path = queue_dir / f"{ts}-app{head['id']}.json"

        # 설명은 아무 장에나 적을 수 있으니 처음 적힌 것을 쓴다.
        caption = next((r.get("user_caption") for r in members if r.get("user_caption")), "")

        entry_path.write_text(
            json.dumps(
                {
                    "media_urls": [r["media_url"] for r in members],
                    "media_url": head["media_url"],  # 예전 형식과의 호환
                    "media_type": head["media_type"],
                    "user_caption": caption,
                    "message_id": f"app{head['id']}",
                    "app_queue_id": head["id"],
                    "storage_paths": [r["storage_path"] for r in members],
                    "storage_path": head["storage_path"],
                    "urgency": head.get("urgency") or "scheduled",
                    "style_id": head.get("style_id"),  # 올릴 때 고른 저장 디자인
                    "queued_at": head["created_at"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        for row in members:
            try:
                trends_sync.update_media_queue(row["id"], "done")
            except Exception as e:
                print(f"  ! 앱 대기열 상태 갱신 실패(id {row['id']}): {e}")
        count = f"{len(members)}장" if len(members) > 1 else "1건"
        print(f"  - [{slug}] 앱에서 올린 소재를 대기열로 옮김 ({count}, 묶음 {key})")


def _is_urgent(entry_path: Path) -> bool:
    try:
        return json.loads(entry_path.read_text(encoding="utf-8")).get("urgency") == "now"
    except Exception:
        return False


def _process_channel(path, urgent_only: bool = False) -> None:
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

    if urgent_only:
        # 급한 건 기다리게 두지 않는다. 있는 만큼 다 처리한다.
        urgent = [e for e in entries if _is_urgent(e)]
        if not urgent:
            print(f"  - [{cfg['slug']}] 급한 소재 없음")
            return
        for entry in urgent:
            _process_one(cfg, token, chat_id, entry)
        return

    if not entries:
        print(f"  - [{cfg['slug']}] 대기열 비어있음")
        return

    _process_one(cfg, token, chat_id, entries[0])


def main() -> int:
    channels_dir = ROOT / "channels"
    if not channels_dir.exists():
        print("channels/ 폴더가 없습니다.")
        return 0

    parser = argparse.ArgumentParser()
    parser.add_argument("--urgent", action="store_true", help='앱에서 "지금 바로" 로 올린 것만 처리')
    args = parser.parse_args()

    _drain_app_queue()

    for path in sorted(channels_dir.glob("*.yaml")):
        _process_channel(path, urgent_only=args.urgent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
