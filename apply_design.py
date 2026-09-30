"""사용법: python apply_design.py --channel hssup-tips --css-file new.css

디자인 담당이 고친 CSS 를 입혀보고, 결과물이 깨졌으면 되돌립니다.

디자인은 자유롭게 고치되 카드가 망가지면 안 됩니다. 사람이 매번 눈으로
확인할 수 없으니, 입혀서 그려보고 기계가 검사한 뒤 문제가 있으면
고치기 전으로 되돌립니다. 되돌릴 수 있으니 과감하게 써도 됩니다.

검사 항목은 engine/design.py 에 있습니다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

from engine.config import ROOT, load_channel
from engine.design import design_path, read_design, write_design
from engine.renderer import Renderer
from engine.sources import get_source

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def try_design(slug: str, css: str) -> tuple[bool, list[str]]:
    """새 디자인을 입혀 그려보고, 깨졌으면 되돌립니다.

    돌려주는 값은 (성공했는지, 걸린 문제들) 입니다.
    """
    cfg = load_channel(slug)
    before = read_design(slug)

    write_design(slug, css)
    try:
        source_cfg = {
            **cfg["source"],
            "slug": cfg["slug"],
            "cards": cfg.get("cards", 4),
            "topic": cfg.get("topic", cfg["name"]),
        }
        data = get_source(source_cfg).load()
        date = dt.date.fromisoformat(data.get("date") or dt.date.today().isoformat())
        data["date"] = date.isoformat()
        data["date_label"] = f"{date.year}.{date.month:02d}.{date.day:02d}"

        renderer = Renderer(cfg)
        with tempfile.TemporaryDirectory() as tmp:
            renderer.render(data, data["items"][: cfg["cards"]], Path(tmp))
        problems = list(renderer.problems)
    except Exception as e:
        # 그리다 터진 것도 깨진 것으로 칩니다.
        problems = [f"그리는 중 오류: {e}"]

    if problems:
        if before:
            write_design(slug, before)
        elif design_path(slug).exists():
            design_path(slug).unlink()
        return False, problems

    return True, []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True)
    ap.add_argument("--css-file", required=True, help="입혀볼 CSS 파일")
    args = ap.parse_args()

    css = Path(args.css_file).read_text(encoding="utf-8")
    ok, problems = try_design(args.channel, css)

    if ok:
        print("디자인을 입혔습니다. 깨진 곳 없습니다.")
        print(f"  {design_path(args.channel).relative_to(ROOT)}")
        return 0

    print("깨진 곳이 있어 되돌렸습니다:")
    for p in problems:
        print(f"  - {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
