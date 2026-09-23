"""텔레그램 승인 봇. render.py가 미리보기를 보내고(send_preview),
poll_telegram.py가 주기적으로 버튼 응답을 확인해 pending/<slug>/<date>.json에 기록합니다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import requests

from .config import ROOT

API = "https://api.telegram.org/bot{token}/{method}"
OFFSET_PATH = ROOT / "state" / "telegram_offset.json"


def _token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN이 설정되어 있지 않습니다.")
    return token


def _chat_id() -> str:
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise ValueError("TELEGRAM_CHAT_ID가 설정되어 있지 않습니다.")
    return chat_id


def _call(method: str, files: dict | None = None, **params) -> dict:
    url = API.format(token=_token(), method=method)
    resp = requests.post(url, data=params, files=files, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError(f"텔레그램 API 오류({method}): {body}")
    return body["result"]


def notify(text: str) -> None:
    """단순 텍스트 알림을 보냅니다 (게시 성공/실패 등)."""
    _call("sendMessage", chat_id=_chat_id(), text=text)


def create_pending(slug: str, date: str, image_urls: list[str], caption: str) -> None:
    """렌더링 직후 승인 대기 레코드를 만듭니다. publish_instagram.py가 나중에 이 파일을 읽어 게시합니다."""
    out_path = ROOT / "pending" / slug / f"{date}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "status": "awaiting_approval",
                "image_urls": image_urls,
                "caption": caption,
                "rendered_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def send_preview(cfg: dict, pngs: list[Path], caption: str, slug: str, date: str) -> None:
    """카드뉴스 PNG를 앨범으로 보내고, 승인 버튼이 달린 안내 메시지를 보냅니다."""
    chat_id = _chat_id()

    media = []
    files = {}
    handles = []
    for i, p in enumerate(pngs[:10]):  # 텔레그램 앨범은 최대 10장
        key = f"photo{i}"
        media.append({"type": "photo", "media": f"attach://{key}"})
        fh = p.open("rb")
        handles.append(fh)
        files[key] = (p.name, fh, "image/png")
    try:
        _call("sendMediaGroup", chat_id=chat_id, media=json.dumps(media), files=files)
    finally:
        for fh in handles:
            fh.close()

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ 게시", "callback_data": f"approve:{slug}:{date}"},
            {"text": "⏭ 건너뛰기", "callback_data": f"skip:{slug}:{date}"},
        ]]
    }
    text = caption if len(caption) <= 3900 else caption[:3900] + "\n…"
    text += "\n게시할까요?"
    _call("sendMessage", chat_id=chat_id, text=text, reply_markup=json.dumps(keyboard))


def poll_and_record() -> list[dict]:
    """새 버튼 응답을 확인해 pending/<slug>/<date>.json에 기록하고, 처리한 결정 목록을 반환합니다."""
    offset = 0
    if OFFSET_PATH.exists():
        offset = json.loads(OFFSET_PATH.read_text(encoding="utf-8")).get("offset", 0)

    updates = _call("getUpdates", offset=offset, timeout=0)
    decided = []
    max_update_id = offset - 1

    for u in updates:
        max_update_id = max(max_update_id, u["update_id"])
        cq = u.get("callback_query")
        if not cq or "data" not in cq:
            continue
        try:
            action, slug, date = cq["data"].split(":", 2)
        except ValueError:
            continue
        status = "approved" if action == "approve" else "skipped"

        # render.py가 렌더링 직후 만들어둔 레코드(이미지 URL·캡션 포함)를 그대로 두고 상태만 갱신합니다.
        out_path = ROOT / "pending" / slug / f"{date}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        existing = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
        existing["status"] = status
        existing["decided_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        out_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        decided.append({"slug": slug, "date": date, "status": status})

        # 콜백 응답에는 유효시간이 있어 폴링 주기(5분)보다 먼저 만료될 수 있습니다.
        # 화면 갱신(체크 표시)이 실패해도 위의 pending/ 기록은 이미 끝났으니 무시하고 계속 진행합니다.
        label = "✅ 게시 확정" if status == "approved" else "⏭ 건너뜀"
        try:
            _call("answerCallbackQuery", callback_query_id=cq["id"], text=label)
            msg = cq["message"]
            _call(
                "editMessageReplyMarkup",
                chat_id=msg["chat"]["id"],
                message_id=msg["message_id"],
                reply_markup=json.dumps({"inline_keyboard": [[{"text": label, "callback_data": "noop"}]]}),
            )
        except Exception as e:
            print(f"  ! 텔레그램 UI 갱신 실패(응답 만료 가능성, 기록은 정상 반영됨): {e}")

    OFFSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    OFFSET_PATH.write_text(json.dumps({"offset": max_update_id + 1}), encoding="utf-8")
    return decided
