"""컬러 팔레트. 네오브루탈리즘 톤을 유지하는 조화로운 세트를 미리 큐레이션해두고(무작위 생성 아님),
채널 yaml의 palette 값으로 고정해서 씁니다 (같은 계정에 여러 채널을 올릴 때 색으로 구분하기 위함).
palette를 지정하지 않으면 날짜 기반으로 자동 로테이션합니다.

각 팔레트의 역할:
- yellow: 밝은 액센트 (표지 배경, 블랙 텍스트)
- violet: 어두운 액센트 (마무리 배경, 화이트 텍스트)
- pink: 어두운 액센트 (뉴스 카드 기본 포인트, 화이트 텍스트)
"""
from __future__ import annotations

import datetime as dt

PALETTES: dict[str, dict[str, str]] = {
    "yellow": {"yellow": "#F5FF3D", "pink": "#FF3B7F", "violet": "#7A5CFF"},  # 옐로우 · 핑크 · 바이올렛
    "mint": {"yellow": "#3DFFC0", "pink": "#FF6B4A", "violet": "#2E2A8F"},    # 민트 · 코랄 · 인디고
    "sky": {"yellow": "#4FD6FF", "pink": "#FF2E7A", "violet": "#6D28D9"},    # 스카이 · 핫핑크 · 퍼플
}
ROTATION_ORDER = ["yellow", "mint", "sky"]


def pick_palette(date: dt.date, fixed: str | None = None) -> dict[str, str]:
    if fixed:
        if fixed not in PALETTES:
            raise ValueError(f"알 수 없는 팔레트: {fixed} (가능: {', '.join(PALETTES)})")
        return PALETTES[fixed]
    name = ROTATION_ORDER[date.toordinal() % len(ROTATION_ORDER)]
    return PALETTES[name]
