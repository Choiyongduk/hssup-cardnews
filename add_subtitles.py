"""사용법: python add_subtitles.py <승인 번호> [--apply]

이미 올라와 있는 영상 시안에 자막을 붙입니다(자막 기능이 생기기 전에 만든 시안용, 그리고 점검용).
--apply 가 없으면 받아 적은 자막을 보여주기만 합니다. 있으면 영상을 다시 만들어 시안을 바꾸고
대화창에 차은우 팀장 이름으로 고치기 전과 후를 남깁니다. 인스타에는 올리지 않습니다(결재는 그대로).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import requests

import revise_post
from engine import subtitles, trends_sync

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    approval_id, apply = int(sys.argv[1]), "--apply" in sys.argv
    rows = trends_sync._get("ai_approvals", {"select": "*", "id": f"eq.{approval_id}"})
    if not rows:
        print(f"{approval_id}번 시안이 없습니다")
        return 1
    row = rows[0]
    payload = row.get("payload") or {}
    if payload.get("media_type") != "video":
        print(f"{approval_id}번은 영상 시안이 아닙니다")
        return 1

    source = (payload.get("source_urls") or [payload.get("source_url")])[0]
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"source{Path(urlparse(source).path).suffix or '.mp4'}"
        src.write_bytes(requests.get(source, timeout=120).content)
        subs = subtitles.make(src, hint=row.get("body") or "")
    for s in subs:
        print(f"  {s['start']:6.2f}~{s['end']:6.2f}  {s['text']}")
    if not apply:
        return 0
    if not subs:
        print("자막이 없어 시안은 그대로 둡니다")
        return 0

    urls = revise_post._rerender_photo(row, payload.get("headline") or "", subs)
    if not urls:
        print("영상을 다시 만들지 못했습니다")
        return 1
    trends_sync.update_approval_content(approval_id, image_urls=urls)
    trends_sync.update_approval_payload(approval_id, {**payload, "subtitles": subs})
    trends_sync.create_approval_message(
        approval_id, "staff",
        f"영상에 말소리를 받아 적은 자막 {len(subs)}줄을 넣었어요. 틀린 글자가 있으면 몇째 줄을 어떻게 고칠지 "
        "말씀해 주세요. 자막을 빼 달라고 하셔도 돼요.",
        staff_key="designer", attachments=revise_post._before_after(row.get("image_urls"), urls),
    )
    print(f"{approval_id}번 시안에 자막을 넣었습니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
