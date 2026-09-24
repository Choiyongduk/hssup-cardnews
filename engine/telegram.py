"""텔레그램 승인 봇 + 미디어 인박스.

두 가지 흐름을 지원합니다:
1. (카드뉴스형) send_preview()로 렌더링된 카드 미리보기를 보내고, poll()이 승인/건너뛰기 버튼 응답을 처리
2. (미디어 인박스형) 사용자가 사진/영상 + 설명을 보내면 poll()이 감지해서 다운로드
   → poll_telegram.py가 Claude로 캡션을 작성하고 다시 미리보기를 보냅니다.

채널마다 다른 봇(토큰)을 쓸 수 있도록 모든 함수가 token/chat_id를 인자로 받습니다.
봇별 폴링 오프셋은 state/telegram_offset_<bot_name>.json에 따로 저장됩니다.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import requests

from .config import ROOT

API = "https://api.telegram.org/bot{token}/{method}"


def _call(token: str, method: str, files: dict | None = None, **params) -> dict:
    url = API.format(token=token, method=method)
    resp = requests.post(url, data=params, files=files, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError(f"텔레그램 API 오류({method}): {body}")
    return body["result"]


def notify(token: str, chat_id: str, text: str) -> None:
    """단순 텍스트 알림을 보냅니다 (게시 성공/실패 등)."""
    _call(token, "sendMessage", chat_id=chat_id, text=text)


def create_pending(slug: str, date: str, image_urls: list[str], caption: str, **extra) -> None:
    """승인 대기 레코드를 만듭니다. publish_instagram.py가 나중에 이 파일을 읽어 게시합니다."""
    out_path = ROOT / "pending" / slug / f"{date}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "status": "awaiting_approval",
        "image_urls": image_urls,
        "caption": caption,
        "rendered_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    data.update(extra)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def send_preview(token: str, chat_id: str, image_paths: list[Path], caption: str, slug: str, date: str) -> None:
    """이미지를 앨범으로 보내고, 승인 버튼이 달린 안내 메시지를 보냅니다."""
    media = []
    files = {}
    handles = []
    for i, p in enumerate(image_paths[:10]):  # 텔레그램 앨범은 최대 10장
        key = f"photo{i}"
        is_video = p.suffix.lower() in (".mp4", ".mov")
        media.append({"type": "video" if is_video else "photo", "media": f"attach://{key}"})
        fh = p.open("rb")
        handles.append(fh)
        if is_video:
            mime = "video/mp4"
        else:
            mime = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        files[key] = (p.name, fh, mime)
    try:
        _call(token, "sendMediaGroup", chat_id=chat_id, media=json.dumps(media), files=files)
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
    _call(token, "sendMessage", chat_id=chat_id, text=text, reply_markup=json.dumps(keyboard))


def create_pending_dm(slug: str, dm_id: str, recipient_id: str, incoming_text: str, draft_reply: str) -> None:
    """DM 답장 승인 대기 레코드를 만듭니다. send_dm.py가 나중에 이 파일을 읽어 실제 DM을 보냅니다."""
    out_path = ROOT / "pending_dm" / slug / f"{dm_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "status": "awaiting_approval",
                "recipient_id": recipient_id,
                "incoming_text": incoming_text,
                "draft_reply": draft_reply,
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def send_dm_preview(token: str, chat_id: str, slug: str, dm_id: str, incoming_text: str, draft_reply: str) -> None:
    """받은 DM 원문 + AI 답장 초안을 보여주고, 발송 승인 버튼을 보냅니다."""
    text = f"📩 새 DM 문의\n\n\"{incoming_text}\"\n\n💬 AI 답장 초안:\n{draft_reply}\n\n이대로 보낼까요?"
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ 발송", "callback_data": f"senddm:{slug}:{dm_id}"},
            {"text": "⏭ 건너뛰기(직접 응대)", "callback_data": f"skipdm:{slug}:{dm_id}"},
        ]]
    }
    _call(token, "sendMessage", chat_id=chat_id, text=text[:4000], reply_markup=json.dumps(keyboard))


def _offset_path(bot_name: str) -> Path:
    return ROOT / "state" / f"telegram_offset_{bot_name}.json"


def _download_file(token: str, file_id: str, dest_dir: Path) -> Path:
    info = _call(token, "getFile", file_id=file_id)
    file_path = info["file_path"]
    url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    dest = dest_dir / Path(file_path).name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return dest


def poll(token: str, bot_name: str, inbox_chat_id: str | None = None) -> dict:
    """새 업데이트를 확인합니다.
    - callback_query(승인 버튼) → pending/<slug>/<date>.json 상태 갱신
    - inbox_chat_id가 주어지면, 그 chat에서 온 사진/영상 메시지를 다운로드해서 inbox 목록으로 반환
      (V1 제한: 메시지당 사진/영상 1개만 처리 — 여러 장을 한 앨범으로 보내면 첫 장만 반영됩니다.)

    반환: {"decided": [{"slug","date","status"}, ...], "inbox": [{"paths": [Path], "caption": str, "message_id": int}, ...]}
    """
    offset_path = _offset_path(bot_name)
    offset = 0
    if offset_path.exists():
        offset = json.loads(offset_path.read_text(encoding="utf-8")).get("offset", 0)

    updates = _call(token, "getUpdates", offset=offset, timeout=0)
    decided: list[dict] = []
    inbox: list[dict] = []
    max_update_id = offset - 1

    for u in updates:
        max_update_id = max(max_update_id, u["update_id"])

        cq = u.get("callback_query")
        if cq and "data" in cq:
            try:
                action, slug, key = cq["data"].split(":", 2)
            except ValueError:
                continue

            is_dm = action in ("senddm", "skipdm")
            if is_dm:
                status = "approved" if action == "senddm" else "skipped"
                out_path = ROOT / "pending_dm" / slug / f"{key}.json"
            else:
                status = "approved" if action == "approve" else "skipped"
                out_path = ROOT / "pending" / slug / f"{key}.json"

            out_path.parent.mkdir(parents=True, exist_ok=True)
            existing = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
            existing["status"] = status
            existing["decided_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            out_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
            decided.append({"slug": slug, "date": key, "status": status, "dm": is_dm})

            # 콜백 응답에는 유효시간이 있어 폴링 주기보다 먼저 만료될 수 있습니다.
            # 화면 갱신이 실패해도 위의 pending/ 기록은 이미 끝났으니 무시하고 계속 진행합니다.
            label = ("✅ 발송 확정" if is_dm else "✅ 게시 확정") if status == "approved" else "⏭ 건너뜀"
            try:
                _call(token, "answerCallbackQuery", callback_query_id=cq["id"], text=label)
                msg = cq["message"]
                _call(
                    token,
                    "editMessageReplyMarkup",
                    chat_id=msg["chat"]["id"],
                    message_id=msg["message_id"],
                    reply_markup=json.dumps({"inline_keyboard": [[{"text": label, "callback_data": "noop"}]]}),
                )
            except Exception as e:
                print(f"  ! 텔레그램 UI 갱신 실패(응답 만료 가능성, 기록은 정상 반영됨): {e}")
            continue

        msg = u.get("message")
        if msg and inbox_chat_id and str(msg.get("chat", {}).get("id")) == str(inbox_chat_id):
            photos = msg.get("photo")
            video = msg.get("video")
            # "파일로 보내기"(갤러리 선택이 아닌 첨부)로 보내면 photo/video가 아니라
            # document로 옵니다 — mime_type이 이미지/영상이면 같은 방식으로 처리합니다.
            document = msg.get("document")
            doc_mime = (document or {}).get("mime_type", "")
            if document and not (doc_mime.startswith("image/") or doc_mime.startswith("video/")):
                document = None
            if not photos and not video and not document:
                continue
            dest_dir = ROOT / "state" / "inbox" / bot_name / str(u["update_id"])
            paths = []
            if photos:
                largest = photos[-1]  # 텔레그램은 작은 해상도부터 순서대로 줍니다
                paths.append(_download_file(token, largest["file_id"], dest_dir))
            if video:
                paths.append(_download_file(token, video["file_id"], dest_dir))
            if document:
                paths.append(_download_file(token, document["file_id"], dest_dir))
            inbox.append({"paths": paths, "caption": msg.get("caption", ""), "message_id": msg["message_id"]})

    offset_path.parent.mkdir(parents=True, exist_ok=True)
    offset_path.write_text(json.dumps({"offset": max_update_id + 1}), encoding="utf-8")
    return {"decided": decided, "inbox": inbox}
