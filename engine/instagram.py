"""Instagram 게시 (Buffer API 경유).

Buffer는 이미 Meta 승인을 받은 앱이라, 우리가 직접 Meta 개발자 앱을 만들거나
전화 인증을 거칠 필요가 없습니다. buffer.com에서 무료 플랜으로 가입 → 채널(계정) 연결에서
Instagram 비즈니스/크리에이터 계정을 Facebook 로그인으로 연결하기만 하면 됩니다.

사전 준비:
- buffer.com 가입 후 Instagram 계정 연결 (설정 > 채널)
- https://publish.buffer.com/settings/api 에서 API 키 발급 → BUFFER_API_KEY
- list_organizations()/list_channels()로 channelId를 한 번 조회해 channels/<slug>.yaml의
  instagram.channel_id에 적어둡니다 (민감정보 아님, 시크릿 불필요).
- 이미지는 공개 HTTPS URL이어야 하므로 engine/assets.py로 먼저 업로드해야 합니다.
"""
from __future__ import annotations

import os

import requests

API = "https://api.buffer.com"


def _token() -> str:
    token = os.environ.get("BUFFER_API_KEY")
    if not token:
        raise ValueError("BUFFER_API_KEY가 설정되어 있지 않습니다.")
    return token


def _graphql(query: str, variables: dict | None = None) -> dict:
    resp = requests.post(
        API,
        json={"query": query, "variables": variables or {}},
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        timeout=30,
    )
    body = resp.json()
    if "errors" in body:
        raise RuntimeError(f"Buffer API 오류: {body['errors']}")
    return body["data"]


def publish_carousel(channel_id: str, image_urls: list[str], caption: str) -> str:
    """이미지 URL 목록(최대 10장)을 캐러셀로 즉시 게시하고, 게시물 ID를 반환합니다."""
    query = """
    mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess {
          post { id dueAt }
        }
        ... on MutationError {
          message
        }
      }
    }
    """
    variables = {
        "input": {
            "text": caption,
            "channelId": channel_id,
            "schedulingType": "automatic",
            "mode": "shareNow",
            "assets": [{"image": {"url": url}} for url in image_urls[:10]],
            "metadata": {"instagram": {"type": "post", "shouldShareToFeed": True}},
        }
    }
    result = _graphql(query, variables)["createPost"]
    if "message" in result:
        raise RuntimeError(f"Buffer 게시 실패: {result['message']}")
    return result["post"]["id"]


def list_organizations() -> list[dict]:
    """채널 조회에 필요한 organizationId를 확인하기 위한 헬퍼 (최초 설정 시 1회용)."""
    query = "query { account { organizations { id name ownerEmail } } }"
    return _graphql(query)["account"]["organizations"]


def list_channels(organization_id: str) -> list[dict]:
    """연결된 채널(계정) 목록과 channelId를 확인하기 위한 헬퍼 (최초 설정 시 1회용)."""
    query = """
    query GetChannels($input: ChannelsInput!) {
      channels(input: $input) { id name displayName service }
    }
    """
    return _graphql(query, {"input": {"organizationId": organization_id}})["channels"]
