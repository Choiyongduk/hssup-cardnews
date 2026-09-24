"""영상 위에 브랜드 로고 + 헤드라인을 입힙니다 (ffmpeg 필요).
engine/overlay.py(사진용)와 짝을 이루는 영상용 렌더러. V1 범위: 로고+헤드라인만 입히기
(자르기·트랜지션·배경음악 등 진짜 "편집"은 다음 단계)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from .config import ROOT
from .overlay import FIT_SCRIPT, TEMPLATE_DIR


def probe_video(video_path: Path) -> dict:
    """ffprobe로 영상의 width/height/duration을 읽습니다."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-show_entries", "format=duration",
            "-of", "json", str(video_path),
        ],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    return {
        "width": stream["width"],
        "height": stream["height"],
        "duration": float(data["format"]["duration"]),
    }


def extract_frame(video_path: Path, out_path: Path, at_seconds: float = 1.0) -> Path:
    """캡션 작성용으로 영상에서 프레임 1장을 뽑습니다."""
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-ss", str(at_seconds), "-i", str(video_path),
            "-frames:v", "1", "-q:v", "2", str(out_path),
        ],
        capture_output=True, check=True,
    )
    return out_path


def _render_overlay_graphic(
    headline: str,
    out_path: Path,
    width: int,
    height: int,
    logo_path: Path | None = None,
    logo_text: str | None = None,
    brand_color: str = "#fa5500",
) -> Path:
    """로고+헤드라인만 있는 투명 배경 PNG를 렌더링합니다 (영상 위에 합성할 오버레이 레이어)."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    html = env.get_template("overlay-only.html").render(
        logo_uri=logo_path.resolve().as_uri() if logo_path else None,
        logo_text=logo_text if not logo_path else None,
        headline=headline,
        brand_color=brand_color,
        width=width,
        height=height,
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
        page.screenshot(path=str(out_path), omit_background=True, clip={"x": 0, "y": 0, "width": width, "height": height})
        browser.close()

    html_path.unlink(missing_ok=True)
    return out_path


def render_video_overlay(
    video_path: Path,
    headline: str,
    out_path: Path,
    logo_path: Path | None = None,
    logo_text: str | None = None,
    brand_color: str = "#fa5500",
) -> Path:
    """영상 원본 위에 로고+헤드라인을 입힌 새 mp4를 out_path에 씁니다."""
    dims = probe_video(video_path)
    out_path = out_path.resolve()
    overlay_png = out_path.with_name(out_path.stem + "_overlay.png")

    _render_overlay_graphic(
        headline=headline,
        out_path=overlay_png,
        width=dims["width"],
        height=dims["height"],
        logo_path=logo_path,
        logo_text=logo_text,
        brand_color=brand_color,
    )

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video_path), "-i", str(overlay_png),
            "-filter_complex", "[0:v][1:v]overlay=0:0",
            "-codec:a", "copy", str(out_path),
        ],
        capture_output=True, check=True,
    )
    overlay_png.unlink(missing_ok=True)
    return out_path
