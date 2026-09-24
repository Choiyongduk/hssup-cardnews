"""RSS 수집 + 중복 제거 + 본문 추출. RssSource(sources.py)에서 사용합니다."""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from time import mktime

import feedparser
import trafilatura

from .config import ROOT

MIN_BODY_LEN = 200  # 이보다 짧게 추출되면 실패로 간주하고 다음 후보로 넘어갑니다.
SEEN_LIMIT = 500  # state 파일에 보관할 최대 URL 수

_BARE_AMP = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")


def _fetch_feed_xml(url: str) -> str | None:
    """일부 매체 피드는 본문에 이스케이프되지 않은 '&'가 섞여 XML 파싱이 깨집니다.
    직접 받아서 보정한 뒤 feedparser에 문자열로 넘깁니다."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
    except Exception:
        return None
    text = raw.decode("utf-8", errors="replace")
    return _BARE_AMP.sub("&amp;", text)


def _normalize_title(title: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", title).lower()


def fetch_entries(feeds: list[str]) -> list[dict]:
    """피드 목록을 읽어 {title, url, source_name, published} 목록을 최신순으로 반환합니다.
    URL과 정규화된 제목 기준으로 중복을 제거합니다."""
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    entries: list[dict] = []

    for feed_url in feeds:
        xml = _fetch_feed_xml(feed_url)
        parsed = feedparser.parse(xml) if xml is not None else feedparser.parse(feed_url)
        source_name = parsed.feed.get("title", feed_url)
        for e in parsed.entries:
            url = e.get("link")
            title = e.get("title")
            if not url or not title:
                continue
            norm = _normalize_title(title)
            if url in seen_urls or norm in seen_titles:
                continue
            seen_urls.add(url)
            seen_titles.add(norm)

            published = e.get("published_parsed") or e.get("updated_parsed")
            published_dt = (
                datetime.fromtimestamp(mktime(published), tz=timezone.utc)
                if published
                else datetime.now(tz=timezone.utc)
            )
            entries.append(
                {
                    "title": title,
                    "url": url,
                    "source_name": source_name,
                    "published": published_dt,
                }
            )

    entries.sort(key=lambda x: x["published"], reverse=True)
    return entries


def extract_body(url: str) -> str | None:
    """기사 URL에서 본문 텍스트를 추출합니다. 실패하거나 너무 짧으면 None을 반환합니다."""
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return None
    text = trafilatura.extract(downloaded, favor_recall=True)
    if not text or len(text) < MIN_BODY_LEN:
        return None
    return text


def _state_path(slug: str) -> Path:
    return ROOT / "state" / f"{slug}_seen.json"


def load_seen(slug: str) -> list[str]:
    """이미 카드뉴스로 사용한 기사 URL 목록(오래된 순)을 불러옵니다."""
    path = _state_path(slug)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_seen(slug: str, urls: list[str]) -> None:
    """사용한 URL 목록을 저장합니다. 최근 SEEN_LIMIT개만 보관합니다."""
    path = _state_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    trimmed = urls[-SEEN_LIMIT:]
    path.write_text(json.dumps(trimmed, ensure_ascii=False, indent=2), encoding="utf-8")
