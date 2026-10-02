"""히썹 디자인 기준(assets/brand/DESIGN.md)을 읽어 줍니다.

디자인을 하는 쪽(free_design)과 보는 쪽(team_review)이 같은 기준을 읽어야
"주황은 늘 주황", "로고에 번짐 금지" 같은 원장님 말씀이 매번 지켜집니다.
기준을 고치려면 DESIGN.md 만 고치면 됩니다.
"""
from __future__ import annotations

from functools import lru_cache

from .config import ROOT

GUIDE_PATH = ROOT / "assets" / "brand" / "DESIGN.md"


@lru_cache(maxsize=1)
def design_guide() -> str:
    try:
        return GUIDE_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def guide_block(intro: str) -> str:
    """시스템 프롬프트 끝에 붙일 덩어리. 기준 파일이 없으면 빈 문자열."""
    guide = design_guide()
    return f"\n\n[{intro}]\n{guide}" if guide else ""
