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

TODO: 콘텐츠 전략(교육 팁 / 강좌 홍보 / 비포애프터)이 정해지면 여기에 소스 타입을 추가합니다.
cardnews 프로젝트의 engine/sources.py, engine/summarize.py, engine/rss.py를 참고해 구조를 잡으면 됩니다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Source(ABC):
    def __init__(self, cfg: dict):
        self.cfg = cfg

    @abstractmethod
    def load(self) -> dict: ...


REGISTRY: dict[str, type[Source]] = {}


def get_source(source_cfg: dict) -> Source:
    kind = source_cfg.get("type")
    if kind not in REGISTRY:
        raise ValueError(f"알 수 없는 소스 타입: {kind} (가능: {', '.join(REGISTRY) or '아직 없음'})")
    return REGISTRY[kind](source_cfg)
