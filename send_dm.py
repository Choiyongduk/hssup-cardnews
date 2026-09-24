"""사용법: python send_dm.py
pending_dm/<slug>/<id>.json 중 status가 "approved"인 것만 실제 인스타그램 DM으로 발송합니다."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

from engine import dm, telegram
from engine.config import ROOT, load_channel


def _notify(cfg: dict, text: str) -> None:
    tg_cfg = cfg.get("telegram")
    if not tg_cfg:
        return
    token = os.environ.get(tg_cfg["bot_token_env"])
    if not token:
        return
    try:
        telegram.notify(token, str(tg_cfg["chat_id"]), text)
    except Exception as e:
        print(f"  ! 텔레그램 알림 실패: {e}")


def _write_status(path, status: str, **extra) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = status
    data["sent_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    data.update(extra)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _send_one(slug: str, entry_path, data: dict) -> None:
    cfg = load_channel(slug)
    ig_cfg = cfg.get("instagram")
    dm_cfg = cfg.get("dm")
    if not ig_cfg or not dm_cfg:
        return

    page_id = os.environ.get(dm_cfg["page_id_env"])
    token = os.environ.get(ig_cfg["token_env"])
    if not page_id or not token:
        print(f"  ! {slug}: instagram 환경변수 없음, 건너뜀")
        return

    try:
        message_id = dm.send_message(page_id, token, data["recipient_id"], data["draft_reply"])
    except Exception as e:
        _write_status(entry_path, "failed", error=str(e))
        _notify(cfg, f"❌ [{cfg['name']}] DM 발송 실패: {e}")
        return

    _write_status(entry_path, "sent", sent_message_id=message_id)
    _notify(cfg, f"✅ [{cfg['name']}] DM 답장 발송 완료")


def main() -> int:
    pending_dir = ROOT / "pending_dm"
    if not pending_dir.exists():
        print("발송 대기 중인 DM이 없습니다.")
        return 0

    count = 0
    for entry_path in sorted(pending_dir.glob("*/*.json")):
        slug = entry_path.parent.name
        data = json.loads(entry_path.read_text(encoding="utf-8"))
        if data.get("status") != "approved":
            continue
        # 초안 없이 승인 기록만 있는 레코드(초안 파일이 커밋되기 전에 버튼이 눌린 경우 등)는
        # 보낼 내용이 없습니다. 그냥 두면 매 실행마다 실패하며 알림을 반복하므로 건너뜁니다.
        if not data.get("recipient_id") or not data.get("draft_reply"):
            _write_status(entry_path, "skipped", error="초안 정보가 없어 발송할 수 없습니다")
            print(f"  ! [{slug}] {entry_path.name}: 초안 정보 없음, 건너뜀")
            continue
        print(f"[{slug}] DM 발송 시작")
        _send_one(slug, entry_path, data)
        count += 1

    if count == 0:
        print("발송 대기 중인 DM이 없습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
