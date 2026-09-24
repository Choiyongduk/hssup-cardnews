"""사용법: python poll_dm.py
channels/*.yaml의 dm 설정이 있는 채널마다 새로 들어온 인스타그램 DM을 확인해서
Claude로 답장 초안을 쓰고, 같은 채널의 텔레그램 봇으로 승인 요청을 보냅니다.
승인/건너뛰기 버튼 응답은 poll_telegram.py(engine.telegram.poll)가 함께 처리합니다.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import yaml

from engine import dm, dm_reply, telegram
from engine.config import ROOT


def _seen_path(slug: str):
    return ROOT / "state" / f"dm_seen_{slug}.json"


def _load_seen(slug: str) -> set[str]:
    path = _seen_path(slug)
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def _save_seen(slug: str, seen: set[str]) -> None:
    path = _seen_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 최근 500개만 보관
    path.write_text(json.dumps(list(seen)[-500:], ensure_ascii=False, indent=2), encoding="utf-8")


def _process_channel(path) -> None:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    dm_cfg = cfg.get("dm")
    tg_cfg = cfg.get("telegram")
    ig_cfg = cfg.get("instagram")
    if not dm_cfg or not tg_cfg or not ig_cfg:
        return

    slug = cfg["slug"]
    business_id = os.environ.get(ig_cfg["business_id_env"])
    page_id = os.environ.get(dm_cfg["page_id_env"])
    ig_token = os.environ.get(ig_cfg["token_env"])
    tg_token = os.environ.get(tg_cfg["bot_token_env"])
    if not page_id or not ig_token or not tg_token:
        print(f"  ! [{slug}] DM 관련 환경변수 없음, 건너뜀")
        return
    chat_id = str(tg_cfg["chat_id"])

    seen = _load_seen(slug)
    try:
        messages = dm.list_recent_messages(page_id, ig_token, self_id=business_id or "")
    except Exception as e:
        print(f"  ! [{slug}] DM 조회 실패: {e}")
        return

    new_count = 0
    for m in messages:
        if m["message_id"] in seen:
            continue

        # 인스타그램 메시지 ID는 텔레그램 callback_data 한도(64바이트)를 넘으므로 짧은 키로 줄입니다.
        key = hashlib.sha1(m["message_id"].encode()).hexdigest()[:12]

        try:
            draft = dm_reply.write_reply(
                m["text"], cfg.get("topic", cfg["name"]), dm_cfg.get("context", "")
            )
            telegram.create_pending_dm(slug, key, m["from_id"], m["text"], draft)
            telegram.send_dm_preview(tg_token, chat_id, slug, key, m["text"], draft)
            print(f"  - [{slug}] 새 DM 답장 초안 전송: {m['message_id']}")
            seen.add(m["message_id"])  # 성공했을 때만 처리됨으로 기록 (실패하면 다음 폴링에서 재시도)
            new_count += 1
        except Exception as e:
            print(f"  ! [{slug}] DM 답장 초안 작성 실패: {e}")

    if new_count:
        _save_seen(slug, seen)
    else:
        print(f"  - [{slug}] 새 DM 없음")


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
