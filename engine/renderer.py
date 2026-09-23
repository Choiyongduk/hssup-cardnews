"""HTML 템플릿 → PNG 렌더링 (Jinja2 + Playwright)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from .config import ROOT
from .theme import pick_palette

# 넘치는 텍스트를 단계적으로 줄이는 스크립트.
# data-fit="최소px" 속성이 붙은 요소를 대상으로, 부모(.fit-box)를 넘치지 않을 때까지 축소합니다.
FIT_SCRIPT = """
() => {
  const overflow = (box) => box.scrollHeight > box.clientHeight + 1 || box.scrollWidth > box.clientWidth + 1;
  const report = [];
  document.querySelectorAll('.fit-box').forEach((box) => {
    const targets = [...box.querySelectorAll('[data-fit]')];
    let guard = 0;
    while (overflow(box) && guard < 80) {
      let shrunk = false;
      for (const el of targets) {
        const min = parseFloat(el.dataset.fit);
        const size = parseFloat(getComputedStyle(el).fontSize);
        if (size - 2 >= min) { el.style.fontSize = (size - 2) + 'px'; shrunk = true; }
      }
      if (!shrunk) break;
      guard++;
    }
    if (overflow(box)) report.push(box.dataset.name || 'box');
  });
  return report;
}
"""


class Renderer:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.tpl_dir = ROOT / "templates" / cfg["template"]
        if not self.tpl_dir.exists():
            raise FileNotFoundError(f"템플릿 폴더가 없습니다: {self.tpl_dir}")
        self.env = Environment(
            loader=FileSystemLoader(str(self.tpl_dir)),
            autoescape=select_autoescape(["html"]),
        )

    def build_pages(self, data: dict, items: list[dict]) -> list[tuple[str, str]]:
        total = len(items) + 2
        common = {
            "cfg": self.cfg,
            "data": data,
            "items": items,
            "total": total,
            "css_url": (self.tpl_dir / "style.css").as_uri(),
            "font_dir": (ROOT / "assets" / "fonts").as_uri(),
            "theme": pick_palette(dt.date.fromisoformat(data["date"]), fixed=self.cfg.get("palette")),
        }
        pages = [("01_cover", self.env.get_template("cover.html").render(page=1, **common))]
        for i, it in enumerate(items, 1):
            html = self.env.get_template("news.html").render(page=i + 1, index=i, item=it, **common)
            pages.append((f"{i + 1:02d}_news", html))
        pages.append((f"{total:02d}_outro", self.env.get_template("outro.html").render(page=total, **common)))
        return pages

    def render(self, data: dict, items: list[dict], out_dir: Path) -> list[Path]:
        html_dir = out_dir / "html"
        html_dir.mkdir(parents=True, exist_ok=True)
        w, h = self.cfg["size"]["width"], self.cfg["size"]["height"]
        results = []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
            for name, html in self.build_pages(data, items):
                html_path = html_dir / f"{name}.html"
                html_path.write_text(html, encoding="utf-8")
                page.goto(html_path.as_uri())
                page.evaluate("document.fonts.ready")
                still = page.evaluate(FIT_SCRIPT)
                if still:
                    print(f"  ! {name}: 최소 글자 크기에서도 넘침 → 문구를 줄이세요 ({', '.join(still)})")
                png = out_dir / f"{name}.png"
                page.screenshot(path=str(png), clip={"x": 0, "y": 0, "width": w, "height": h})
                results.append(png)
            browser.close()
        return results
