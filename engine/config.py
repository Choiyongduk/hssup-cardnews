"""채널 설정(channels/<slug>.yaml) 로딩."""
from __future__ import annotations

from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def load_channel(slug: str) -> dict:
    path = ROOT / "channels" / f"{slug}.yaml"
    if not path.exists():
        available = ", ".join(p.stem for p in (ROOT / "channels").glob("*.yaml"))
        raise FileNotFoundError(f"채널 설정이 없습니다: {path}\n사용 가능한 채널: {available}")
    with path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg.setdefault("slug", slug)
    cfg.setdefault("template", slug)
    cfg.setdefault("size", {"width": 1080, "height": 1350})
    cfg.setdefault("limits", {"title": 30, "summary_line": 40, "summary_lines": 3})
    cfg.setdefault("hashtags", [])
    cfg.setdefault("outro", {})
    return cfg
