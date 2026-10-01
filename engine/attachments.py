"""대화에 붙은 사진을 클로드가 볼 수 있게 바꿉니다.

원장님이 앱에서 "이 사진처럼 바꿔줘" 하고 참고 사진을 붙이면, 그 주소가
attachments 칸에 들어옵니다. 지금 시안 그림도 같은 방식으로 보여줍니다.
글만 읽고서는 "이런 느낌" 이 뭔지 알 수 없기 때문입니다.

주소를 그대로 넘기지 않고 직접 내려받아 넘깁니다.
- 지워졌거나 못 여는 사진 하나 때문에 요청 전체가 실패하면 안 됩니다. 그런 건 건너뜁니다.
- raw.githubusercontent.com 은 그림 종류를 제대로 알려주지 않을 때가 있어서
  파일 앞부분을 보고 종류를 정합니다.
"""
from __future__ import annotations

import base64

import requests

MAX_BYTES = 5 * 1024 * 1024  # 클로드가 받는 한 장 크기 한도

_SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
]


def _media_type(data: bytes) -> str | None:
    for sig, kind in _SIGNATURES:
        if data.startswith(sig):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_blocks(urls: list[str] | None, limit: int = 6) -> list[dict]:
    """사진 주소들을 클로드에 넘길 그림 조각으로 바꿉니다. 못 여는 건 건너뜁니다."""
    blocks = []
    for url in (urls or [])[:limit]:
        try:
            resp = requests.get(url, timeout=30)
        except Exception as e:
            print(f"  ! 사진을 내려받지 못했습니다: {e}")
            continue
        if resp.status_code != 200 or len(resp.content) > MAX_BYTES:
            print(f"  ! 사진 건너뜀({resp.status_code}, {len(resp.content)}바이트): {url}")
            continue
        kind = _media_type(resp.content)
        if not kind:
            print(f"  ! 열 수 없는 형식이라 건너뜀: {url}")  # 영상 등
            continue
        blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": kind, "data": base64.b64encode(resp.content).decode()},
        })
    return blocks


def owner_content(body: str, urls: list[str] | None) -> str | list[dict]:
    """원장님 한 마디. 사진이 붙었으면 사진을 먼저, 말을 뒤에 둡니다."""
    if not urls:
        return body or "(빈 메시지)"
    blocks = image_blocks(urls)
    if not blocks:
        return f"{body}\n\n(사진을 함께 보내셨는데 열리지 않았습니다)".strip()
    label = f"[원장님이 보낸 참고 사진 {len(blocks)}장]"
    return [{"type": "text", "text": label}, *blocks, {"type": "text", "text": body or "(사진만 보내셨습니다)"}]


def requests_content(text: str, reqs: list[dict]) -> str | list[dict]:
    """콘텐츠 요청 묶음. 요청마다 붙은 참고 사진을 어느 요청 것인지 밝혀 덧붙입니다."""
    blocks: list[dict] = [{"type": "text", "text": text}]
    for i, r in enumerate(reqs, 1):
        imgs = image_blocks(r.get("attachments"))
        if imgs:
            blocks += [{"type": "text", "text": f"[요청 {i}「{(r.get('body') or '')[:40]}」에 붙은 참고 사진]"}, *imgs]
    return blocks if len(blocks) > 1 else text


def with_images(label: str, urls: list[str] | None, content: str | list[dict], limit: int = 6) -> str | list[dict]:
    """대화 맨 앞에 그림을 덧붙입니다. 예) 지금 올라와 있는 시안."""
    blocks = image_blocks(urls, limit=limit)
    if not blocks:
        return content
    rest = content if isinstance(content, list) else [{"type": "text", "text": content}]
    return [{"type": "text", "text": label}, *blocks, *rest]
