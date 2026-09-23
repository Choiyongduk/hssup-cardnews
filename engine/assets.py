"""카드뉴스 PNG를 별도 public 저장소에 올려 공개 URL을 얻습니다.
Instagram Graph API(Buffer 경유)는 image_url이 공개 HTTPS 주소여야만 이미지를 가져갈 수 있어서 필요합니다.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

import requests

API = "https://api.github.com"


def _token() -> str:
    token = os.environ.get("ASSETS_REPO_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("ASSETS_REPO_TOKEN(또는 GITHUB_TOKEN)이 설정되어 있지 않습니다.")
    return token


def _repo() -> str:
    repo = os.environ.get("ASSETS_REPO")
    if not repo:
        raise ValueError("ASSETS_REPO 환경변수(예: owner/repo-assets)가 설정되어 있지 않습니다.")
    return repo


def upload_images(pngs: list[Path], slug: str, date: str) -> list[str]:
    """pngs를 <ASSETS_REPO>/<slug>/<date>/<파일명> 경로로 올리고,
    raw.githubusercontent.com 공개 URL 목록을 같은 순서로 반환합니다."""
    repo = _repo()
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
    }
    urls = []
    for p in pngs:
        repo_path = f"{slug}/{date}/{p.name}"
        content_b64 = base64.b64encode(p.read_bytes()).decode()
        payload = {"message": f"add {repo_path}", "content": content_b64}

        existing = requests.get(
            f"{API}/repos/{repo}/contents/{repo_path}", headers=headers, timeout=30
        )
        if existing.status_code == 200:
            payload["sha"] = existing.json()["sha"]  # 같은 경로에 이미 파일이 있으면(재렌더링) 덮어쓰기 위해 필요

        resp = requests.put(
            f"{API}/repos/{repo}/contents/{repo_path}",
            headers=headers,
            json=payload,
            timeout=30,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"이미지 업로드 실패({repo_path}): {resp.status_code} {resp.text}")
        urls.append(f"https://raw.githubusercontent.com/{repo}/main/{repo_path}")
    return urls
