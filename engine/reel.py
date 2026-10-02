"""카드뉴스를 움직이는 릴스(9:16, 1080x1920)로 만듭니다.

피드 분석에서 릴스 도달이 피드보다 훨씬 높게 나왔습니다. 카드뉴스를 만들 때 같은 내용으로
릴스도 하나 뽑아, 따로 승인받아 올립니다(인스타에서 캐러셀과 릴스는 서로 다른 게시물).

AI 가 그때그때 움직임을 짜지 않고, 정해진 움직임 틀에 카드 내용을 넣습니다.
그래서 결과가 늘 고르고 비용이 들지 않습니다(그리는 데 30초 안팎).

  표지(3.4초)   단어가 하나씩 올라오고, 목차가 차례로
  카드마다(3.6초) 큰 번호 → STEP → 제목 → 설명 줄 → "이것만 기억하세요"
  마무리(2.8초)  정리 한 줄 + 팔로우 안내

시각을 직접 정해(seek) 한 장씩 찍고 ffmpeg 로 잇습니다. 컴퓨터가 느려도 움직임이 끊기지 않습니다.
위쪽엔 스토리처럼 진행 막대, 아래 20% 는 인스타 캡션과 버튼이 덮는 자리라 비워 둡니다.
음악은 넣지 않습니다(공식 연동으로는 저작권 음악을 붙일 수 없음).
"""
from __future__ import annotations

import html
import re
import subprocess
import tempfile
from pathlib import Path

from .config import ROOT

FPS = 30
W, H = 1080, 1920
ORANGE = "#FF5C1F"   # assets/brand/DESIGN.md 의 시그니처 주황

COVER, CARD, OUTRO = 3.4, 3.6, 2.8
COVER_FRAME = 3.0   # 표지 글이 다 떠오른 때. 인스타 표지와 앱 미리보기가 이 장면을 쓴다(첫 장면은 비어 있음)


def _hl(text: str) -> str:
    """[강조] → 주황 글자"""
    return re.sub(r"\[(.+?)\]", r'<em class="hl">\1</em>', html.escape(text or ""))


def _words(text: str, at: float, step: float = 0.07) -> str:
    """단어마다 따로 들어오게. 강조 [ ] 가 여러 단어에 걸쳐 있어도("[무조건 레이저]") 이어지게,
    단어마다 강조가 열려 있는지 기억하며 태그를 닫았다 다시 연다."""
    spans, open_ = [], False
    for i, word in enumerate((text or "").split(" ")):
        piece = '<em class="hl">' if open_ else ""
        for ch in word:
            if ch == "[":
                piece += '<em class="hl">'
                open_ = True
            elif ch == "]":
                piece += "</em>"
                open_ = False
            else:
                piece += html.escape(ch)
        if open_:
            piece += "</em>"
        spans.append(f'<span class="a w" data-at="{at + i * step:.2f}" data-fx="up">{piece}</span>')
    return " ".join(spans)


def build_html(data: dict, items: list[dict], handle: str) -> tuple[str, float]:
    """릴스 한 편의 HTML 과 전체 길이(초)."""
    font = (ROOT / "assets" / "fonts").as_uri()
    logo = (ROOT / "assets" / "logos" / "hssup-wordmark.png").as_uri()

    scenes, t = [], 0.0
    toc = "".join(
        f'<li class="a" data-at="{1.6 + i * 0.18:.2f}" data-fx="up"><b>{i + 1:02d}</b>{html.escape(it.get("title", ""))}</li>'
        for i, it in enumerate(items)
    )
    scenes.append((t, t + COVER, f"""
  <div class="kicker a" data-at="0.15" data-fx="left">{html.escape(data.get('kicker') or '')}</div>
  <h1 class="cover-title">{_words(data.get('headline', ''), 0.45)}</h1>
  <div class="bar a" data-at="1.3" data-fx="bar"></div>
  <ol class="toc">{toc}</ol>"""))
    t += COVER
    for i, it in enumerate(items, 1):
        lines = "".join(
            f'<li class="a" data-at="{0.9 + j * 0.32:.2f}" data-fx="left"><i></i>{html.escape(s)}</li>'
            for j, s in enumerate(it.get("summary") or [])
        )
        why = f'<div class="why a" data-at="2.4" data-fx="up"><span>이것만 기억하세요</span><p>{_hl(it["why"])}</p></div>' if it.get("why") else ""
        scenes.append((t, t + CARD, f"""
  <div class="bignum a" data-at="0" data-fx="scale">{i:02d}</div>
  <div class="step a" data-at="0.1" data-fx="left">STEP {i:02d}</div>
  <h2 class="title">{_words(it.get('title', ''), 0.25, 0.06)}</h2>
  <ul class="lines">{lines}</ul>{why}"""))
        t += CARD
    scenes.append((t, t + OUTRO, f"""
  <div class="kicker a" data-at="0.1" data-fx="left">정리하면</div>
  <h2 class="one">{_words(data.get('one_liner') or '', 0.3, 0.05)}</h2>
  <div class="cta a" data-at="1.5" data-fx="up">팔로우하고 다음 편 받아보기<br><b>{html.escape(handle)}</b></div>"""))
    total = t + OUTRO

    body = "\n".join(f'<section class="scene" data-start="{s:.2f}" data-end="{e:.2f}">{b}</section>' for s, e, b in scenes)
    page = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>
@font-face {{ font-family: P; src: url("{font}/Pretendard-Medium.woff2"); font-weight: 500; }}
@font-face {{ font-family: P; src: url("{font}/Pretendard-SemiBold.woff2"); font-weight: 600; }}
@font-face {{ font-family: P; src: url("{font}/Pretendard-Bold.woff2"); font-weight: 700; }}
@font-face {{ font-family: P; src: url("{font}/Pretendard-ExtraBold.woff2"); font-weight: 800; }}
:root {{ --o: {ORANGE}; --ink: #0A0A0A; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ width: {W}px; height: {H}px; overflow: hidden; background: #fff; font-family: P, sans-serif; color: var(--ink); }}
.logo {{ position: absolute; top: 96px; left: 84px; height: 40px; z-index: 5; }}
.progress {{ position: absolute; top: 56px; left: 84px; right: 84px; display: flex; gap: 8px; z-index: 5; }}
.progress div {{ flex: 1; height: 6px; border-radius: 3px; background: rgba(10,10,10,0.1); overflow: hidden; }}
.progress div span {{ display: block; height: 100%; width: 0; background: var(--o); }}
.scene {{ position: absolute; inset: 0; padding: 300px 84px 380px; display: flex; flex-direction: column; justify-content: center; }}
.w {{ display: inline-block; }}
.hl {{ font-style: normal; color: var(--o); }}
.kicker {{ font-size: 34px; font-weight: 800; color: var(--o); letter-spacing: 0.02em; margin-bottom: 36px; }}
.cover-title {{ font-size: 112px; font-weight: 800; line-height: 1.12; letter-spacing: -0.04em; word-break: keep-all; }}
.bar {{ height: 10px; width: 120px; background: var(--o); border-radius: 5px; margin: 56px 0 48px; transform-origin: left; }}
.toc li {{ list-style: none; font-size: 40px; font-weight: 600; padding: 22px 0; border-top: 2px solid rgba(10,10,10,0.08); display: flex; gap: 24px; word-break: keep-all; }}
.toc b {{ color: var(--o); font-weight: 800; }}
.bignum {{ position: absolute; right: -30px; top: 210px; font-size: 520px; font-weight: 800; color: rgba(255,92,31,0.1); letter-spacing: -0.06em; line-height: 1; transform-origin: right top; }}
.step {{ font-size: 32px; font-weight: 800; letter-spacing: 0.22em; color: var(--o); margin-bottom: 28px; }}
.title {{ font-size: 96px; font-weight: 800; line-height: 1.14; letter-spacing: -0.035em; word-break: keep-all; margin-bottom: 64px; }}
.lines li {{ list-style: none; font-size: 46px; font-weight: 500; line-height: 1.35; padding: 22px 0; border-top: 2px solid rgba(10,10,10,0.07); display: flex; gap: 22px; align-items: center; word-break: keep-all; }}
.lines i {{ flex: none; width: 28px; height: 5px; background: var(--o); border-radius: 3px; }}
.why {{ margin-top: 56px; border-top: 6px solid var(--o); padding-top: 28px; }}
.why span {{ font-size: 30px; font-weight: 800; color: var(--o); letter-spacing: 0.1em; }}
.why p {{ font-size: 54px; font-weight: 800; line-height: 1.25; letter-spacing: -0.02em; margin-top: 12px; word-break: keep-all; }}
.one {{ font-size: 84px; font-weight: 800; line-height: 1.2; letter-spacing: -0.035em; word-break: keep-all; }}
.cta {{ margin-top: 80px; background: var(--o); color: #fff; border-radius: 28px; padding: 44px 48px; font-size: 40px; font-weight: 600; line-height: 1.5; }}
.cta b {{ font-size: 52px; font-weight: 800; }}
</style></head><body>
<div class="progress">{''.join('<div><span></span></div>' for _ in scenes)}</div>
<img class="logo" src="{logo}">
{body}
<script>
const ease = p => 1 - Math.pow(1 - Math.min(Math.max(p, 0), 1), 3);
const scenes = [...document.querySelectorAll('.scene')];
const bars = [...document.querySelectorAll('.progress span')];
window.seek = (t) => {{
  scenes.forEach((sc, i) => {{
    const s = +sc.dataset.start, e = +sc.dataset.end, local = t - s;
    const inP = ease(local / 0.25), outP = ease((t - (e - 0.25)) / 0.25);
    const visible = t >= s && t < e + 0.25;
    sc.style.opacity = visible ? Math.min(inP, 1 - outP) : 0;
    sc.style.transform = `translateY(${{(1 - inP) * 40 - outP * 40}}px)`;
    bars[i].style.width = (Math.min(Math.max((t - s) / (e - s), 0), 1) * 100) + '%';
    sc.querySelectorAll('.a').forEach(el => {{
      const p = ease((local - +el.dataset.at) / 0.45);
      const fx = el.dataset.fx;
      el.style.opacity = p;
      el.style.transform =
        fx === 'up' ? `translateY(${{(1 - p) * 60}}px)` :
        fx === 'left' ? `translateX(${{(1 - p) * -60}}px)` :
        fx === 'scale' ? `scale(${{0.85 + 0.15 * p}})` :
        fx === 'bar' ? `scaleX(${{p}})` : '';
    }});
  }});
}};
seek(0);
</script></body></html>"""
    return page, total


def make_reel(data: dict, items: list[dict], handle: str, out_path: Path) -> Path:
    """카드뉴스 내용으로 릴스 MP4 를 만들어 out_path 에 씁니다."""
    from playwright.sync_api import sync_playwright

    page_html, total = build_html(data, items, handle)
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "reel.html").write_text(page_html, encoding="utf-8")
        n = int(total * FPS)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": W, "height": H})
            page.goto((tmp / "reel.html").as_uri())
            page.evaluate("document.fonts.ready")
            for i in range(n):
                page.evaluate(f"seek({i / FPS})")
                page.screenshot(path=str(tmp / f"{i:05d}.jpg"), type="jpeg", quality=92)
            browser.close()
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", str(tmp / "%05d.jpg"),
            "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(out_path),
        ], check=True)
    return out_path
