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

from engine import assets, attachments, free_design, media_caption, telegram, trends_sync
from engine.config import ROOT
from engine.overlay import render_overlay
from engine.video_overlay import extract_frame, render_video_overlay


def _fit_instagram(path: Path) -> Path:
    """인스타가 받는 비율(세로 4:5 ~ 가로 1.91:1) 안으로 맞춥니다. 자르지 않고 여백을 붙입니다.

    ChatGPT 로 만든 이미지는 보통 2:3 이라 4:5 보다 길어서 인스타가 거절합니다.
    잘라내면 글자가 잘리니, 가장자리 색으로 양옆(또는 위아래)을 채웁니다.
    """
    from PIL import Image

    im = Image.open(path).convert("RGB")
    w, h = im.size
    ratio = w / h
    if 0.8 <= ratio <= 1.91:
        return path
    if ratio < 0.8:      # 너무 길다 → 양옆을 채운다
        new_w, new_h = round(h * 0.8), h
    else:                # 너무 넓다 → 위아래를 채운다
        new_w, new_h = w, round(w / 1.91)
    # 가장자리 한 줄의 평균 색. 배경과 이어져 보이게.
    edge = im.crop((0, 0, 1, h)) if ratio < 0.8 else im.crop((0, 0, w, 1))
    color = tuple(int(c) for c in edge.resize((1, 1)).getpixel((0, 0)))
    canvas = Image.new("RGB", (new_w, new_h), color)
    canvas.paste(im, ((new_w - w) // 2, (new_h - h) // 2))
    out = path.with_name(path.stem + "_fit.jpg")
    canvas.save(out, "JPEG", quality=92)
    print(f"  - 인스타 비율에 맞춰 여백을 붙임 ({w}x{h} → {new_w}x{new_h})")
    return out


def _design_from_text(entry: dict, slug: str, date_key: str, tmp_dir: Path) -> Path:
    """사진 없이 글로만 요청한 게시물을 그립니다. 그린 HTML 은 떠둬서 시안 대화로 고칠 수 있게 합니다."""
    refs = attachments.image_blocks(entry.get("ref_urls") or [])
    drawn = free_design.design(
        request=entry.get("user_caption") or "히썹 아카데미 인스타그램 게시물",
        photo_urls=[],
        references=refs,
        context="원본 사진 없이 글로만 요청한 게시물입니다. 필요하면 새 그림(illustrations)을 그려 쓰세요.",
        out_path=tmp_dir / f"{slug}-{date_key}_design.png",
        channel=slug,
    )
    if drawn["problems"]:
        print(f"  ! 디자인에 남은 문제(그대로 씁니다): {drawn['problems']}")
    free_design.save(slug, date_key, drawn["html"], drawn["fonts"])
    print(f"  - 글로만 요청한 디자인을 그림: {drawn['notes'][:80]}")
    return drawn["png"]


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
    _mark(entry, "working")   # 실패했다 다시 시도하는 것도 "만드는 중" 으로

    is_video = entry.get("media_type") == "video"
    # 사진 없이 글로만 요청한 것. 디자인 담당이 새 그림까지 그려 한 장을 만든다.
    is_design = entry.get("media_type") == "design"
    media_urls = [] if is_design else (entry.get("media_urls") or [entry["media_url"]])

    tmp_dir = ROOT / "state" / "queue_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 여러 장이면 첫 장이 표지다. 캡션도 오버레이도 첫 장을 기준으로 한다.
        media_paths = []
        if is_design:
            media_paths.append(_design_from_text(entry, slug, date_key, tmp_dir))
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

        user_text = entry.get("user_caption", "")
        finished = entry.get("as_is") or is_design   # 글씨까지 다 들어간 그림. 위에 또 얹지 않는다
        if finished:
            # 사진이 아니라 글씨까지 다 들어간 완성 디자인이다. 그림 속 글을 캡션에서 되풀이하지 않게.
            user_text = (f"{user_text}\n\n" if user_text else "") + (
                "(이건 원장님이 직접 완성한 디자인 이미지입니다. 이미지 속 글을 그대로 옮기지 말고, "
                "그 내용을 풀어 주는 캡션을 써 주세요. 헤드라인은 쓰이지 않습니다.)"
            )
        post = media_caption.write_post(
            caption_source_path, user_text, cfg.get("topic", cfg["name"]), cfg.get("hashtags", [])
        )
        caption = post["caption"]

        post_paths = list(media_paths)
        overlay_cfg = cfg.get("overlay")
        if finished and not is_video:
            # 원장님이 ChatGPT 등으로 이미 완성해 온 이미지. 글씨를 얹지 않고 비율만 맞춘다.
            post_paths = [_fit_instagram(p) for p in media_paths]
            print(f"  - [{slug}] 완성본 그대로 {len(post_paths)}장 (캡션만 씀)")
        elif overlay_cfg:
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
        # 앱에서 "실패" 와 이유가 보이게. 앱에서 올린 건 파일 대기열에서 빼 둔다.
        # 앱의 "다시 맡기기" 가 상태를 queued 로 돌리면 새로 옮겨 와 처음부터 한다(두 번 들어가지 않게).
        # 텔레그램으로 온 건 예전처럼 남겨 두고 다음 차례에 다시 시도한다.
        _mark(entry, "failed", str(e)[:300])
        if _queue_ids(entry):
            entry_path.unlink(missing_ok=True)
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
                "as_is": bool(entry.get("as_is")),  # 시안 대화에서 그림을 다시 그리지 않게
                "app_queue_ids": _queue_ids(entry),  # 앱에서 "시안 나옴" 을 짝지을 때
            },
        )
    except Exception as e:
        print(f"  ! [{slug}] 앱 승인 등록 실패: {e}")

    _mark(entry, "done")
    entry_path.unlink()
    print(f"  - [{slug}] {date_key} 미리보기 전송 완료, 대기열에서 제거")


def _queue_ids(entry: dict) -> list[int]:
    return entry.get("app_queue_ids") or ([entry["app_queue_id"]] if entry.get("app_queue_id") else [])


def _mark(entry: dict, status: str, error: str | None = None) -> None:
    """앱 대기열에 지금 상태를 적습니다. 원장님이 앱에서 "어디까지 됐나" 를 보는 근거입니다.

      queued  아직 차례가 안 옴 (정해진 시간 / 곧 시작)
      working 지금 만드는 중
      done    시안이 올라감
      failed  실패. error 에 이유
    """
    for row_id in _queue_ids(entry):
        try:
            trends_sync.update_media_queue(row_id, status, error)
        except Exception as e:
            print(f"  ! 앱 대기열 상태 갱신 실패(id {row_id}): {e}")


def _drain_app_queue(urgent_only: bool = False) -> None:
    """앱에서 올린 소재 중 **지금 만들 것만** 파일 대기열로 옮깁니다.

    예전에는 5분마다 전부 옮기고 "끝남" 으로 적어서, 정해진 시간을 기다리는 것도 앱에
    "만드는 중" 으로 보였습니다. 이제 앱 대기열이 진짜 상태를 갖습니다.
      - "바로 작업" 차례(urgent_only): 바로 작업으로 올린 것만
      - 정해진 시간 차례: 채널마다 가장 오래된 한 묶음만 (원래 한 번에 하나씩 게시)
    그래서 정해진 시간을 기다리는 동안 "바로 작업" 으로 바꾸면 다음 5분 안에 시작됩니다.
    """
    rows = trends_sync.fetch_media_queue()
    if not rows:
        return

    # 한 번에 고른 사진들은 같은 group_key 를 갖는다. 그런 것끼리 묶어 한 게시물로 만든다.
    # group_key 가 없는 건 예전에 올린 것이라 id 를 묶음으로 친다.
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row.get("group_key") or f"id{row['id']}", []).append(row)

    taken: set[str] = set()   # 정해진 시간 차례에 이미 하나 꺼낸 채널
    for key, members in groups.items():
        members.sort(key=lambda r: (r.get("sort_order") or 0, r["id"]))
        head = members[0]
        slug = head["channel"]
        queue_dir = ROOT / "queue" / slug
        queue_dir.mkdir(parents=True, exist_ok=True)
        if urgent_only:
            if head.get("urgency") != "now":
                continue
        else:
            # 파일 대기열에 이미 기다리는 게 있으면 그것부터. 새로 꺼내지 않는다.
            if slug in taken or any(queue_dir.glob("*.json")):
                continue
            taken.add(slug)
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
        entry_path = queue_dir / f"{ts}-app{head['id']}.json"

        # 설명은 아무 장에나 적을 수 있으니 처음 적힌 것을 쓴다.
        caption = next((r.get("user_caption") for r in members if r.get("user_caption")), "")

        entry_path.write_text(
            json.dumps(
                {
                    "media_urls": [r["media_url"] for r in members if r.get("media_url")],
                    "media_url": head["media_url"],  # 예전 형식과의 호환
                    "media_type": head["media_type"],
                    "user_caption": caption,
                    "message_id": f"app{head['id']}",
                    "app_queue_id": head["id"],
                    "app_queue_ids": [r["id"] for r in members],
                    "storage_paths": [r["storage_path"] for r in members if r.get("storage_path")],
                    "storage_path": head["storage_path"],
                    "urgency": head.get("urgency") or "scheduled",
                    "style_id": head.get("style_id"),  # 올릴 때 고른 저장 디자인
                    "as_is": bool(head.get("as_is")),  # 완성본 그대로 (글씨를 얹지 않음)
                    "ref_urls": head.get("ref_urls") or [],  # 사진 없이 만들 때 붙인 참고 사진
                    "queued_at": head["created_at"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        for row in members:
            try:
                trends_sync.update_media_queue(row["id"], "working")
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

    _drain_app_queue(urgent_only=args.urgent)

    for path in sorted(channels_dir.glob("*.yaml")):
        _process_channel(path, urgent_only=args.urgent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
