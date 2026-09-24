"""사진 위에 브랜드 로고 + 헤드라인을 입혀 인스타그램용 이미지를 렌더링합니다.
(engine/renderer.py의 카드뉴스용 다단 렌더러와 달리, 사진 1장짜리 미디어 인박스 채널 전용입니다.)"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from .config import ROOT

TEMPLATE_DIR = ROOT / "templates" / "brand-overlay"

FIT_SCRIPT = """
() => {
  const overflow = (box) => box.scrollHeight > box.clientHeight + 1;
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
  });
}
"""


def render_overlay(
    photo_path: Path,
    headline: str,
    out_path: Path,
    logo_path: Path | None = None,
    logo_text: str | None = None,
    brand_color: str = "#ff7a00",
    width: int = 1080,
    height: int = 1350,
) -> Path:
    """사진 1장 + 헤드라인 + (선택) 로고를 합성해 out_path에 PNG로 저장합니다.
    logo_path가 있으면 이미지 로고, 없고 logo_text만 있으면 텍스트 로고를 씁니다."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    html = env.get_template("post.html").render(
        photo_uri=photo_path.resolve().as_uri(),
        logo_uri=logo_path.resolve().as_uri() if logo_path else None,
        logo_text=logo_text if not logo_path else None,
        headline=headline,
        brand_color=brand_color,
        css_url=(TEMPLATE_DIR / "style.css").as_uri(),
        font_dir=(ROOT / "assets" / "fonts").as_uri(),
    )
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    html_path = out_path.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.goto(html_path.as_uri())
        page.evaluate("document.fonts.ready")
        page.evaluate(FIT_SCRIPT)
        page.screenshot(path=str(out_path), clip={"x": 0, "y": 0, "width": width, "height": height})
        browser.close()

    html_path.unlink(missing_ok=True)
    return out_path
