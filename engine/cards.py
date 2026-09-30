"""카드뉴스를 다시 그리는 일.

사진 게시물은 원본 사진에 글씨를 다시 얹으면 되지만, 카드뉴스는 원본 사진이
없습니다. 글에서 그려낸 그림이라 내용이나 디자인을 고치면 처음부터 다시 그립니다.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
from pathlib import Path

from . import assets
from .config import ROOT
from .renderer import Renderer
from .sources import get_source


def cards_path(cfg: dict) -> Path:
    """이 채널의 카드 내용이 들어 있는 파일."""
    return ROOT / ((cfg.get("source") or {}).get("path") or "data/cards.json")


def is_cards_channel(cfg: dict) -> bool:
    """글에서 그려내는 채널인지. 사진 게시물 채널과 처리가 다릅니다."""
    return (cfg.get("source") or {}).get("type") == "json"


def load_cards(cfg: dict) -> dict:
    return json.loads(cards_path(cfg).read_text(encoding="utf-8"))


def save_cards(cfg: dict, data: dict) -> None:
    cards_path(cfg).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def redraw(cfg: dict, ref_key: str) -> tuple[list[str], list[str]]:
    """카드를 다시 그려 올립니다.

    돌려주는 값은 (올라간 사진 주소들, 걸린 문제들) 입니다.
    문제가 있으면 부른 쪽에서 판단합니다.
    """
    source_cfg = {
        **cfg["source"],
        "slug": cfg["slug"],
        "cards": cfg.get("cards", 4),
        "topic": cfg.get("topic", cfg["name"]),
    }
    data = get_source(source_cfg).load()

    date = dt.date.fromisoformat(data.get("date") or dt.date.today().isoformat())
    data["date"] = date.isoformat()
    weekdays = "월화수목금토일"
    data["date_label"] = f"{date.year}.{date.month:02d}.{date.day:02d} ({weekdays[date.weekday()]})"

    renderer = Renderer(cfg)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        pngs = renderer.render(data, data["items"][: cfg["cards"]], out)
        problems = list(renderer.problems)
        if problems:
            return [], problems
        # 고칠 때마다 주소가 겹치지 않게 시각을 붙입니다.
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%H%M%S")
        urls = assets.upload_images(pngs, cfg["slug"], f"revised/{ref_key}-{stamp}")
    return urls, []


def style_summary(cfg: dict) -> str:
    """지금 쓰고 있는 글자 크기를 훑어 알려줍니다.

    지금 값을 모르면 1.1em 처럼 상대 단위로 찍게 되는데, 기본 16px 기준으로
    계산돼 오히려 작아집니다. 실제로 42px 이던 글자가 17px 이 된 적이 있습니다.
    """
    import re

    css = (ROOT / "templates" / cfg["template"] / "style.css").read_text(encoding="utf-8")
    want = [".headline", ".title", ".summary li", ".why p", ".kicker", ".one-liner", ".index li"]
    out = []
    for sel in want:
        m = re.search(re.escape(sel) + r"\s*\{[^}]*?font-size:\s*(\d+)px", css, re.S)
        if m:
            out.append(f"  {sel} : {m.group(1)}px")
    return chr(10).join(out)
