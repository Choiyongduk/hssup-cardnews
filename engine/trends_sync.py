"""hssup-app(Supabase)의 "트렌드 속보"(trends 테이블)에 자동으로 글을 올립니다.
인스타그램 게시가 끝난 뒤 publish_instagram.py가 호출합니다. 서비스 롤 키로 RLS를 우회해서 씁니다
(민감한 권한이므로 이 모듈 밖에서는 절대 이 키를 로그·출력하지 않습니다)."""
from __future__ import annotations

import os

import requests


def create_trend(
    title: str,
    content: str | None = None,
    image_urls: list[str] | None = None,
    category: str = "업계소식",
    link_url: str | None = None,
) -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY가 설정되어 있지 않습니다.")

    image_urls = image_urls or []
    payload = {
        "category": category,
        "title": title,
        "content": content or None,
        "link_url": link_url,
        "image_urls": image_urls,
        "image_url": image_urls[0] if image_urls else None,
        "is_active": True,
    }
    resp = requests.post(
        f"{url}/rest/v1/trends",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        json=payload,
        timeout=30,
    )
    if resp.status_code not in (200, 201, 204):
        raise RuntimeError(f"트렌드 등록 실패: {resp.status_code} {resp.text}")
