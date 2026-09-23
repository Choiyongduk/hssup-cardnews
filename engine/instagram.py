"""Instagram Graph API 게시. 카드뉴스 PNG를 캐러셀로 인스타그램에 올립니다.

사전 준비 (Meta 쪽, 코드로 대신할 수 없음):
- 인스타그램 계정을 비즈니스 계정으로 전환 + Facebook 페이지 연결
- Meta for Developers에서 앱 생성, Instagram Graph API 권한으로 장기 액세스 토큰 발급
- 이미지는 공개 HTTPS URL이어야 하므로 engine/assets.py로 먼저 업로드해야 합니다.
"""
from __future__ import annotations

import time

import requests

API_VERSION = "v21.0"
API = f"https://graph.facebook.com/{API_VERSION}"


def _post(path: str, **params) -> dict:
    resp = requests.post(f"{API}/{path}", data=params, timeout=30)
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"Instagram API 오류({path}): {body['error']}")
    return body


def _get(path: str, **params) -> dict:
    resp = requests.get(f"{API}/{path}", params=params, timeout=30)
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"Instagram API 오류({path}): {body['error']}")
    return body


def _wait_until_ready(container_id: str, token: str, timeout: int = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = _get(container_id, fields="status_code", access_token=token).get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"컨테이너 처리 실패: {container_id}")
        time.sleep(2)
    raise TimeoutError(f"컨테이너 처리 대기 시간 초과: {container_id}")


def publish_carousel(business_id: str, token: str, image_urls: list[str], caption: str) -> str:
    """이미지 URL 목록(최대 10장)을 캐러셀로 게시하고, 게시된 미디어 ID를 반환합니다."""
    child_ids = []
    for url in image_urls[:10]:
        container = _post(f"{business_id}/media", image_url=url, is_carousel_item="true", access_token=token)
        child_ids.append(container["id"])

    for cid in child_ids:
        _wait_until_ready(cid, token)

    carousel = _post(
        f"{business_id}/media",
        media_type="CAROUSEL",
        children=",".join(child_ids),
        caption=caption,
        access_token=token,
    )
    _wait_until_ready(carousel["id"], token)

    published = _post(f"{business_id}/media_publish", creation_id=carousel["id"], access_token=token)
    return published["id"]


def refresh_long_lived_token(token: str, app_id: str, app_secret: str) -> tuple[str, int]:
    """만료 전에 장기 토큰을 새 장기 토큰으로 교환합니다. (new_token, expires_in_seconds) 반환."""
    body = _get(
        "oauth/access_token",
        grant_type="fb_exchange_token",
        client_id=app_id,
        client_secret=app_secret,
        fb_exchange_token=token,
    )
    return body["access_token"], body.get("expires_in", 0)
