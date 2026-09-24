"""Instagram DM(다이렉트 메시지) 조회·발송. Meta Graph API 사용.
토큰에 instagram_manage_messages 권한이 있어야 합니다."""
from __future__ import annotations

import requests

API_VERSION = "v21.0"
API = f"https://graph.facebook.com/{API_VERSION}"


def _get(path: str, **params) -> dict:
    resp = requests.get(f"{API}/{path}", params=params, timeout=30)
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"Instagram DM API 오류({path}): {body['error']}")
    return body


def _post(path: str, **params) -> dict:
    resp = requests.post(f"{API}/{path}", data=params, timeout=30)
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"Instagram DM API 오류({path}): {body['error']}")
    return body


def list_recent_messages(business_id: str, token: str, limit: int = 20) -> list[dict]:
    """최근 대화들에서 상대방이 보낸 메시지를 최신순으로 반환합니다.
    반환: [{"conversation_id", "message_id", "from_id", "text", "created_time"}, ...]
    (우리가 보낸 메시지는 제외합니다.)"""
    convos = _get(
        f"{business_id}/conversations",
        fields=f"participants,messages.limit(5){{id,message,from,created_time}}",
        limit=limit,
        access_token=token,
    )
    out = []
    for convo in convos.get("data", []):
        messages = (convo.get("messages") or {}).get("data", [])
        for m in messages:
            from_id = (m.get("from") or {}).get("id")
            if from_id == business_id:
                continue  # 우리가 보낸 메시지는 건너뜀
            if not m.get("message"):
                continue  # 텍스트 없는 메시지(스티커 등)는 V1에서 건너뜀
            out.append(
                {
                    "conversation_id": convo["id"],
                    "message_id": m["id"],
                    "from_id": from_id,
                    "text": m["message"],
                    "created_time": m.get("created_time"),
                }
            )
    return out


def send_message(business_id: str, token: str, recipient_id: str, text: str) -> str:
    """recipient_id에게 텍스트 DM을 보내고 메시지 ID를 반환합니다."""
    import json

    result = _post(
        f"{business_id}/messages",
        recipient=json.dumps({"id": recipient_id}),
        message=json.dumps({"text": text}),
        access_token=token,
    )
    return result.get("message_id", "")
