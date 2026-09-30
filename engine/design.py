"""카드 디자인을 고칠 때 결과물이 깨지지 않게 막아주는 장치.

디자인 담당이 CSS 를 자유롭게 쓰되, 쓴 결과가 망가졌는지는 기계가 봅니다.
사람이 매번 눈으로 확인할 수 없으니 넘어가면 안 되는 것만 자동으로 잡습니다.

  1. 글자나 상자가 카드 밖으로 나갔는가
  2. 글자가 최소 크기까지 줄었는데도 넘치는가 (renderer 가 따로 알려줍니다)
  3. 글자와 배경 색이 너무 비슷해 안 읽히는가
  4. 카드가 통째로 비었는가

하나라도 걸리면 고치기 전으로 되돌립니다. 되돌릴 수 있으니 자유롭게 써도 됩니다.

바깥 도구(BackstopJS, Percy 같은 화면 비교 도구)는 "전과 달라졌는지"를 알려줄 뿐
"망가졌는지"는 사람이 봐야 해서, 여기서는 규칙을 직접 검사합니다.
"""
from __future__ import annotations

from pathlib import Path

from .config import ROOT

# 카드 밖으로 이만큼까지는 나가도 괜찮습니다. 일부러 흘려보낸 장식(큰 번호)이 있습니다.
BLEED_ALLOWANCE = 40

CHECK_SCRIPT = """
() => {
  const problems = [];
  const W = document.documentElement.clientWidth;
  const H = document.documentElement.clientHeight;
  const BLEED = %d;

  // 1) 글자가 카드 밖으로 나갔는가 (장식이 아니라 읽어야 하는 글자만 본다)
  document.querySelectorAll('h1, h2, p, li, span').forEach((el) => {
    const text = (el.textContent || '').trim();
    if (!text) return;
    if (el.closest('.bignum')) return;          // 일부러 흘려보낸 장식
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;
    if (r.left < -BLEED || r.top < -BLEED || r.right > W + BLEED || r.bottom > H + BLEED) {
      problems.push('카드 밖으로 나감: "' + text.slice(0, 20) + '"');
    }
  });

  // 2) 글자가 제 상자를 넘쳤는가 (잘려 보인다)
  document.querySelectorAll('[data-fit]').forEach((el) => {
    if (el.scrollHeight > el.clientHeight + 4 && getComputedStyle(el).overflow !== 'visible') {
      problems.push('글자 잘림: "' + (el.textContent || '').trim().slice(0, 20) + '"');
    }
  });

  // 3) 글자와 배경 색이 너무 비슷한가
  const lum = (c) => {
    const m = c.match(/[\\d.]+/g);
    if (!m) return null;
    const [r, g, b] = m.slice(0, 3).map(Number);
    const a = m.length > 3 ? Number(m[3]) : 1;
    if (a < 0.5) return null;                   // 반투명 장식은 넘어간다
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const bgOf = (el) => {
    let n = el;
    while (n && n !== document.documentElement) {
      const bg = getComputedStyle(n).backgroundColor;
      const l = lum(bg);
      if (l !== null) return l;
      n = n.parentElement;
    }
    return 1;
  };
  document.querySelectorAll('h1, h2, p, li').forEach((el) => {
    const text = (el.textContent || '').trim();
    if (!text || el.children.length) return;
    const fg = lum(getComputedStyle(el).color);
    if (fg === null) return;
    const bg = bgOf(el);
    const ratio = (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
    if (ratio < 3) problems.push('색이 비슷해 안 읽힘: "' + text.slice(0, 20) + '"');
  });

  // 4) 글자가 너무 작아졌는가
  // 1080px 짜리 카드에서 24px 아래로 내려가면 폰에서 안 읽힌다.
  // "키워달라" 고 했는데 상대 단위를 잘못 써서 작아지는 일이 있었다.
  document.querySelectorAll('.title, .summary li, .why p, .headline, .one-liner').forEach((el) => {
    const text = (el.textContent || '').trim();
    if (!text) return;
    const size = parseFloat(getComputedStyle(el).fontSize);
    if (size && size < 24) {
      problems.push('글자가 너무 작음 (' + Math.round(size) + 'px): "' + text.slice(0, 16) + '"');
    }
  });

  // 5) 카드가 통째로 비었는가
  const shown = [...document.querySelectorAll('h1, h2, p, li')]
    .filter((el) => (el.textContent || '').trim() && el.getBoundingClientRect().height > 0);
  if (shown.length < 2) problems.push('카드가 비어 있음');

  return problems;
}
""" % BLEED_ALLOWANCE


def design_path(slug: str) -> Path:
    """디자인 담당이 고친 내용이 쌓이는 자리. 기본 스타일 뒤에 덧씌웁니다."""
    return ROOT / "data" / f"{slug}-design.css"


def read_design(slug: str) -> str:
    p = design_path(slug)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def write_design(slug: str, css: str) -> None:
    p = design_path(slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(css, encoding="utf-8")
