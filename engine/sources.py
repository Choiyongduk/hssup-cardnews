"""소스 입력부. 채널 설정의 source.type에 따라 교체됩니다.

모든 소스는 load()가 아래 스키마의 dict를 반환해야 합니다.
{
  "date": "YYYY-MM-DD" | null,       # null이면 오늘 날짜
  "headline": str,                   # 표지 대표 헤드라인
  "one_liner": str,                  # 마무리 카드 한 줄 요약
  "items": [
    {
      "title": str,
      "summary": [str, str, str],
      "why": str,
      "source": {"name": str, "url": str}
    }
  ]
}

cardnews 프로젝트의 engine/sources.py를 그대로 이식한 RssSource를 씁니다 (반영구 정책/규제 뉴스 카드뉴스용).
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Source(ABC):
    def __init__(self, cfg: dict):
        self.cfg = cfg

    @abstractmethod
    def load(self) -> dict: ...


class RssSource(Source):
    """RSS 수집 → 중복/사용 이력 제거 → 본문 추출 → Claude 요약.

    채널 설정 예:
    source:
      type: rss
      feeds:
        - https://example.com/feed.xml
      # model: claude-sonnet-5
    """

    def load(self) -> dict:
        from . import rss
        from .summarize import filter_relevant, generate

        feeds = self.cfg.get("feeds") or []
        if not feeds:
            raise ValueError("rss 소스는 channels/<slug>.yaml의 source.feeds에 피드 URL이 최소 1개 필요합니다.")

        slug = self.cfg.get("slug", "default")
        need = self.cfg.get("cards", 4)
        topic = self.cfg.get("topic", "뉴스")

        candidates = rss.fetch_entries(feeds)
        already_seen = set(rss.load_seen(slug))
        candidates = [c for c in candidates if c["url"] not in already_seen]

        require_keywords = self.cfg.get("require_keywords") or []
        if require_keywords:
            candidates = [c for c in candidates if any(k in c["title"] for k in require_keywords)]
            if not candidates:
                raise ValueError(
                    f"제목에 {require_keywords} 키워드가 포함된 새 기사가 오늘은 없습니다. 다음에 다시 시도하세요."
                )

        pool = candidates[:30]
        if pool:
            order = filter_relevant([c["title"] for c in pool], topic, need * 3)
            if not order:
                raise ValueError(f"채널 주제 '{topic}'에 맞는 새 기사가 오늘은 없습니다. 다음에 다시 시도하세요.")
            candidates = [pool[i] for i in order] + candidates[len(pool):]

        articles: list[dict] = []
        used_urls: list[str] = []
        for c in candidates:
            if len(articles) >= need:
                break
            body = rss.extract_body(c["url"])
            if not body:
                continue
            articles.append(
                {"title": c["title"], "url": c["url"], "source_name": c["source_name"], "body": body}
            )
            used_urls.append(c["url"])

        if len(articles) < need:
            raise ValueError(
                f"본문 추출에 성공한 새 기사가 {len(articles)}건뿐입니다 (필요: {need}건). "
                "피드를 추가하거나 잠시 후 다시 시도하세요."
            )

        data = generate(articles, model=self.cfg.get("model"), topic=self.cfg.get("topic", "뉴스"))
        data.setdefault("date", None)

        rss.save_seen(slug, list(already_seen) + used_urls)
        return data


REGISTRY: dict[str, type[Source]] = {
    "rss": RssSource,
}


def get_source(source_cfg: dict) -> Source:
    kind = source_cfg.get("type")
    if kind not in REGISTRY:
        raise ValueError(f"알 수 없는 소스 타입: {kind} (가능: {', '.join(REGISTRY) or '아직 없음'})")
    return REGISTRY[kind](source_cfg)
