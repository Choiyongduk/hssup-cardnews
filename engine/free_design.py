"""틀 없이 처음부터 그리는 디자인.

지금까지 사진 게시물은 정해진 틀(로고 + 왼쪽 아래 헤드라인)에 글씨만 바꿔 넣었습니다.
원장님이 "이 사진처럼 만들어줘" 하고 캔바로 만든 걸 보여주면 따라 할 방법이 없었습니다.

여기서는 디자인 담당(차은우)이 카드 HTML 을 통째로 새로 씁니다.

  1. 그린다    참고 사진, 원본 사진, 요청을 보고 HTML 을 쓴다
  2. 찍는다    브라우저로 그려 그림으로 뽑는다
  3. 본다      기계 검사(밖으로 나감, 너무 작음, 그림 깨짐) + 담당자가 결과 그림을
               참고 사진과 나란히 놓고 직접 본다. 어색하면 고쳐 다시 그린다 (최대 2번)

새 그림(일러스트, 사진)을 만들어내지는 못합니다. 도형, 글자, 받은 사진으로 구성합니다.

한 번 이렇게 그린 게시물은 그 HTML 을 data/posts/ 에 떠둡니다.
이후 "제목 더 크게" 같은 요청은 그 디자인 위에서 고칩니다.
"""
from __future__ import annotations

import base64
import os
import re
import tempfile
from pathlib import Path

import requests

from .config import ROOT

DEFAULT_MODEL = "claude-opus-5-5"   # 디자인은 품질이 전부라 가장 잘 그리는 모델을 쓴다
MAX_REVIEWS = 2
W, H = 1080, 1350

# 구글 폰트에서 쓸 수 있는 한글 글꼴. 목록 밖은 받지 않는다(아무 주소나 불러오지 않게).
GOOGLE_FONTS = {
    "Noto Sans KR": "Noto+Sans+KR:wght@300;400;500;700;900",
    "Noto Serif KR": "Noto+Serif+KR:wght@400;600;700;900",
    "Gothic A1": "Gothic+A1:wght@300;400;600;800;900",
    "IBM Plex Sans KR": "IBM+Plex+Sans+KR:wght@300;400;600;700",
    "Nanum Myeongjo": "Nanum+Myeongjo:wght@400;700;800",
    "Black Han Sans": "Black+Han+Sans",
    "Do Hyeon": "Do+Hyeon",
    "Gowun Dodum": "Gowun+Dodum",
    "Gowun Batang": "Gowun+Batang:wght@400;700",
    "Montserrat": "Montserrat:wght@500;700;800;900",
}

FONT_FACES = "\n".join(
    f'@font-face {{ font-family: "Pretendard"; src: url("{{{{FONT_DIR}}}}/Pretendard-{name}.woff2") format("woff2"); font-weight: {w}; }}'
    for name, w in [("Regular", 400), ("Medium", 500), ("SemiBold", 600), ("Bold", 700), ("ExtraBold", 800)]
)

LOGOS = {
    "LOGO_WHITE": "assets/logos/hssup-academy-white.png",
    "LOGO": "assets/logos/hssup-academy.png",
    "WORDMARK": "assets/logos/hssup-wordmark.png",
}

SYSTEM = """당신은 히썹 반영구 아카데미 인스타그램의 디자인 담당 차은우 팀장입니다.
캔바에서 디자이너가 하듯, 정해진 틀 없이 인스타그램 게시물 한 장을 HTML 과 CSS 로 직접 그립니다.

[캔버스]
- 가로 1080px, 세로 1350px (인스타 세로형). 이 크기에 딱 맞게 그리세요. 스크롤은 없습니다.
- `html` 에는 <body> 안에 들어갈 내용만 쓰세요. <style> 은 그 안에 넣으면 됩니다.
  html, body 의 여백과 크기, 기본 글꼴(Pretendard)은 이미 잡혀 있습니다.

[쓸 수 있는 재료]
- 원본 사진: {photos}. <img src="{{{{PHOTO_1}}}}"> 처럼 씁니다. 배경으로 쓰려면 object-fit: cover.
- 로고: {{{{LOGO_WHITE}}}}(어두운 바탕용 흰 로고), {{{{LOGO}}}}(밝은 바탕용), {{{{WORDMARK}}}}(글자 로고).
- 글꼴: 기본은 Pretendard(400~800). 더 필요하면 `fonts` 에 아래 목록에서 골라 적으세요.
  {fonts}
- 별, 화살표, 아이콘은 글자(★)로 쓰지 말고 inline SVG 로 그리세요. 글꼴에 없으면 네모로 나옵니다.
- 바깥 주소(인터넷 이미지 등)는 불러와지지 않습니다.

[원칙]
- 폰에서 읽혀야 합니다. 읽으라고 넣은 글자는 28px 아래로 내리지 마세요.
  장식으로 넣은 작은 글자에는 data-deco 를 붙이세요.
- 한글은 word-break: keep-all 로 단어가 잘리지 않게 하세요.
- 브랜드 주황은 #FF5C1F 입니다. 참고 사진이 다른 색을 쓰면 참고 사진을 따르세요.
- 참고 사진이 있으면 **그 구성을 최대한 그대로** 따라 하세요. 배치, 색, 글자 크기의 비율,
  띠나 라벨, 그라데이션, 여백까지. 글자 내용만 이번 게시물에 맞게 바꿉니다.
- 원본 사진 위에 글자를 얹을 때는 그라데이션이나 그림자로 글자가 확실히 읽히게 하세요.
- 사진 속 글자(후기 본문 등)를 다시 타이핑하지 마세요. 사진은 사진대로 둡니다.
- 게시물마다 바뀌는 큰 제목 요소에는 반드시 data-slot="headline" 을 붙이세요.
  이 디자인을 저장해 다른 사진에 쓸 때 그 글자만 바뀝니다. 제목은 길이가 달라질 수 있으니
  white-space: nowrap 대신 줄바꿈을 허용하세요. 라벨처럼 늘 같은 글자에는 붙이지 않습니다.

`notes` 에는 무엇을 어떻게 그렸는지 한두 줄로 적으세요. 원장님께 그대로 전해집니다.
명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요. 한자를 쓰지 마세요."""

REVIEW = """방금 그린 결과를 그림으로 뽑았습니다. 직접 보고 `review` 도구로 판단하세요.

{checks}

볼 것:
- 참고 사진이 있다면 구성이 그것과 닮았는가 (배치, 색, 크기 비율, 라벨, 그라데이션)
- 글자가 잘 읽히는가, 겹치거나 잘린 데는 없는가, 네모(깨진 글자)는 없는가
- 원장님 요청을 다 반영했는가

고칠 게 없으면 `verdict` 를 ok 로. 있으면 fix 로 하고 `html` 에 고친 전체를 다시 쓰세요."""

DRAW_TOOL = {
    "name": "draw",
    "description": "게시물 한 장을 HTML 로 그립니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "html": {"type": "string", "description": "<body> 안에 들어갈 HTML (style 포함)"},
            "fonts": {"type": "array", "items": {"type": "string"}, "description": "추가로 쓸 구글 글꼴 이름"},
            "notes": {"type": "string", "description": "무엇을 어떻게 그렸는지 한두 줄"},
        },
        "required": ["html", "notes"],
    },
}

REVIEW_TOOL = {
    "name": "review",
    "description": "그린 결과를 보고 판단합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["ok", "fix"]},
            "problems": {"type": "string", "description": "고칠 점. ok 면 빈 문자열."},
            "html": {"type": "string", "description": "fix 일 때 고친 전체 HTML"},
            "fonts": {"type": "array", "items": {"type": "string"}},
            "notes": {"type": "string", "description": "fix 일 때 무엇을 그렸는지 다시 한두 줄"},
        },
        "required": ["verdict"],
    },
}

CHECK_SCRIPT = """
() => {
  const W = %d, H = %d, out = [];
  const textEls = [...document.body.querySelectorAll('*')].filter(el =>
    [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()));
  for (const el of textEls) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const t = el.textContent.trim().slice(0, 16);
    if (r.left < -8 || r.top < -8 || r.right > W + 8 || r.bottom > H + 8) out.push('카드 밖으로 나감: "' + t + '"');
    const fs = parseFloat(getComputedStyle(el).fontSize);
    if (fs < 22 && !el.closest('[data-deco]')) out.push('글자가 너무 작음 (' + Math.round(fs) + 'px): "' + t + '"');
    const st = getComputedStyle(el);
    if (st.overflow !== 'visible' && el.scrollHeight > el.clientHeight + 4) out.push('글자 잘림: "' + t + '"');
  }
  for (const img of document.images) {
    if (!img.complete || img.naturalWidth === 0) out.push('그림이 안 불러와짐: ' + (img.getAttribute('src') || '').slice(-30));
  }
  if (!textEls.length) out.push('글자가 하나도 없음');
  return out;
}
""" % (W, H)


def _ask(client, model: str, system: str, messages: list, want: str):
    """도구 하나로 답하게 합니다.

    이 모델은 특정 도구를 강제로 쓰게 하는 옵션(tool_choice)을 받지 않습니다.
    자동으로 두고 요청 글에서 어느 도구인지 말해 줍니다. 그래도 안 쓰면 한 번 더 부탁합니다.
    대화는 덧붙이기만 합니다(지난 차례를 고치면 거절됨). 그래서 쓴 대화를 같이 돌려줍니다.
    """
    for attempt in range(2):
        resp = client.messages.create(
            model=model, max_tokens=16000, system=system, messages=messages,
            tools=[DRAW_TOOL, REVIEW_TOOL], output_config={"effort": "high"},
        )
        call = next((b for b in resp.content if b.type == "tool_use" and b.name == want), None)
        if call:
            return resp, call, messages
        if resp.stop_reason == "refusal":
            raise RuntimeError("디자인 요청을 거절당했습니다")
        if attempt == 0:
            messages = [*messages, {"role": "assistant", "content": resp.content},
                        {"role": "user", "content": f"`{want}` 도구로 답해 주세요."}]
    raise RuntimeError(f"{want} 도구로 답하지 않았습니다 (stop_reason={resp.stop_reason})")


def _b64_block(data: bytes, kind: str = "image/png") -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": kind, "data": base64.b64encode(data).decode()}}


def _wrap(html: str, fonts: list[str]) -> str:
    links = ""
    picked = [GOOGLE_FONTS[f] for f in fonts or [] if f in GOOGLE_FONTS]
    if picked:
        fams = "&".join(f"family={p}" for p in picked)
        links = (
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{fams}&display=block">'
        )
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f"<style>{FONT_FACES}\n"
        f"*{{box-sizing:border-box}} html,body{{margin:0;padding:0;width:{W}px;height:{H}px;overflow:hidden;"
        'font-family:"Pretendard",sans-serif;background:#000}</style>'
        f"{links}</head><body>{html}</body></html>"
    )


def _fill(html: str, photos: list[Path]) -> str:
    """{{PHOTO_1}} 같은 자리에 실제 파일 주소를 넣습니다."""
    out = html.replace("{{FONT_DIR}}", (ROOT / "assets" / "fonts").as_uri())
    for key, rel in LOGOS.items():
        out = out.replace("{{" + key + "}}", (ROOT / rel).as_uri())
    for i, p in enumerate(photos, 1):
        out = out.replace("{{PHOTO_%d}}" % i, p.resolve().as_uri())
    return out


# 저장한 디자인에 다른 제목을 넣을 때. 제목이 길어져 넘치면 글자를 조금씩 줄인다(원래의 60% 까지).
SLOT_SCRIPT = """
(headline) => {
  const el = document.querySelector('[data-slot="headline"]');
  if (!el || !headline) return false;
  el.textContent = headline;
  const W = %d, base = parseFloat(getComputedStyle(el).fontSize);
  const over = () => {
    const r = el.getBoundingClientRect();
    // 오른쪽 여백은 왼쪽 여백만큼은 남긴다. 끝에 바짝 붙으면 답답해 보인다.
    const margin = Math.max(24, Math.min(r.left, 120));
    return r.right > W - margin || r.left < 24 || el.scrollWidth > el.clientWidth + 2;
  };
  let size = base;
  while (over() && size > base * 0.6) { size -= 2; el.style.fontSize = size + 'px'; }
  return true;
}
""" % W


def render(html: str, fonts: list[str], photos: list[Path], out_path: Path, headline: str = "") -> list[str]:
    """그려서 out_path 에 PNG 로 저장하고, 기계 검사에 걸린 것을 돌려줍니다.

    headline 을 주면 data-slot="headline" 자리의 글자를 바꿔 넣습니다(저장한 디자인 쓰기).
    """
    from playwright.sync_api import sync_playwright

    doc = _fill(_wrap(html, fonts), photos)
    html_path = out_path.with_suffix(".html")
    html_path.write_text(doc, encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)

        # 우리 파일과 구글 글꼴만 불러온다.
        def gate(route):
            url = route.request.url
            if url.startswith("file:") or "fonts.googleapis.com" in url or "fonts.gstatic.com" in url:
                route.continue_()
            else:
                route.abort()

        page.route("**/*", gate)
        page.goto(html_path.as_uri(), wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        if headline:
            page.evaluate(SLOT_SCRIPT, headline)
        problems = page.evaluate(CHECK_SCRIPT)
        page.screenshot(path=str(out_path), clip={"x": 0, "y": 0, "width": W, "height": H})
        browser.close()
    html_path.unlink(missing_ok=True)
    return problems


def _download(urls: list[str], folder: Path) -> list[Path]:
    paths = []
    for i, url in enumerate(urls, 1):
        ext = Path(url.split("?")[0]).suffix or ".jpg"
        p = folder / f"photo{i}{ext}"
        if url.startswith("http"):
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            p.write_bytes(resp.content)
        else:
            p.write_bytes(Path(url).read_bytes())   # 손으로 돌려볼 때 내 컴퓨터 파일
        paths.append(p)
    return paths


def _photo_block(path: Path) -> dict | None:
    """원본 사진을 클로드에 보여줄 크기로 줄입니다(큰 사진은 거부됨)."""
    try:
        from io import BytesIO

        from PIL import Image

        im = Image.open(path).convert("RGB")
        im.thumbnail((1440, 1440))
        buf = BytesIO()
        im.save(buf, "JPEG", quality=88)
        return _b64_block(buf.getvalue(), "image/jpeg")
    except Exception as e:
        print(f"  ! 원본 사진을 보여주지 못했습니다: {e}")
        return None


def design(
    request: str,
    photo_urls: list[str],
    references: list[dict],
    current: list[dict] | None = None,
    previous_html: str = "",
    context: str = "",
    out_path: Path | None = None,
    client=None,
) -> dict:
    """한 장을 그립니다.

    references: 원장님이 보낸 참고 사진 (attachments.image_blocks 결과)
    current:    지금 올라와 있는 시안 그림
    previous_html: 이 게시물을 전에 이렇게 그렸다면 그 HTML. 이어서 고친다.

    돌려주는 값: {"png": Path, "html", "fonts", "notes", "problems"}
    problems 가 남아 있으면 끝내 못 고친 것이다. 쓸지는 부른 쪽에서 정한다.
    """
    from anthropic import Anthropic

    client = client or Anthropic()
    model = os.environ.get("DESIGN_MODEL", DEFAULT_MODEL)
    tmp = Path(tempfile.mkdtemp())
    photos = _download(photo_urls, tmp)
    out_path = out_path or tmp / "design.png"

    content: list[dict] = []
    if references:
        content += [{"type": "text", "text": f"[참고 사진 {len(references)}장 — 이렇게 만들고 싶다고 하셨습니다]"}, *references]
    if current:
        content += [{"type": "text", "text": "[지금 올라와 있는 시안]"}, *current]
    for i, p in enumerate(photos, 1):
        block = _photo_block(p)
        if block:
            content += [{"type": "text", "text": f"[원본 사진 {i} → {{{{PHOTO_{i}}}}}]"}, block]
    if previous_html:
        content.append({"type": "text", "text": f"[이 게시물을 전에 그린 HTML — 이걸 고쳐 주세요]\n{previous_html}"})
    if context:
        content.append({"type": "text", "text": f"[게시물 정보]\n{context}"})
    content.append({"type": "text", "text": f"[원장님 요청]\n{request}"})

    system = SYSTEM.format(
        photos=", ".join(f"{{{{PHOTO_{i}}}}}" for i in range(1, len(photos) + 1)) or "없음",
        fonts=", ".join(GOOGLE_FONTS),
    )
    content.append({"type": "text", "text": "`draw` 도구로 그려 주세요."})
    messages = [{"role": "user", "content": content}]
    resp, call, messages = _ask(client, model, system, messages, "draw")
    html, fonts, notes = call.input["html"], call.input.get("fonts") or [], call.input.get("notes", "")

    problems = render(html, fonts, photos, out_path)
    for round_no in range(1, MAX_REVIEWS + 1):
        checks = ("기계 검사에서 걸린 것:\n- " + "\n- ".join(problems)) if problems else "기계 검사는 통과했습니다."
        messages += [
            {"role": "assistant", "content": resp.content},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": call.id, "content": [
                    _b64_block(out_path.read_bytes()),
                    {"type": "text", "text": REVIEW.format(checks=checks)},
                ]},
            ]},
        ]
        resp, call, messages = _ask(client, model, system, messages, "review")
        verdict = call.input.get("verdict")
        print(f"  - 검토 {round_no}: {verdict} {call.input.get('problems', '')[:80]}")
        if verdict == "ok" and not problems:
            break
        if call.input.get("html"):
            html = call.input["html"]
            fonts = call.input.get("fonts") or fonts
            notes = call.input.get("notes") or notes
            problems = render(html, fonts, photos, out_path)
        elif verdict == "ok":
            break   # 기계 검사는 걸렸지만 고칠 HTML 을 안 줬다. 남은 문제로 넘긴다.

    return {"png": out_path, "html": html, "fonts": fonts, "notes": notes.strip(), "problems": problems}


def apply_style(html: str, fonts: list[str], photo_paths: list[Path], headline: str, out_path: Path) -> list[str]:
    """저장해 둔 디자인을 새 사진과 새 제목으로 그립니다. AI 없이 그리기만 합니다."""
    return render(html, fonts, photo_paths, out_path, headline=headline)


def with_headline(html: str, headline: str) -> str:
    """떠둘 HTML 에도 실제 제목을 넣어 둡니다. 이후 고칠 때 그 글자를 보고 고칩니다."""
    return re.sub(
        r'(<([a-zA-Z0-9]+)[^>]*data-slot="headline"[^>]*>).*?(</\2>)',
        lambda m: m.group(1) + headline.replace("<", "&lt;") + m.group(3),
        html, count=1, flags=re.S,
    )


def saved_path(slug: str, ref_key: str) -> Path:
    """이 게시물을 자유롭게 그린 HTML 을 떠두는 자리."""
    return ROOT / "data" / "posts" / f"{slug}-{ref_key}-free.html"


def save(slug: str, ref_key: str, html: str, fonts: list[str]) -> None:
    p = saved_path(slug, ref_key)
    p.parent.mkdir(parents=True, exist_ok=True)
    head = f"<!-- fonts: {', '.join(fonts)} -->\n" if fonts else ""
    p.write_text(head + html, encoding="utf-8")


def load(slug: str, ref_key: str) -> str:
    p = saved_path(slug, ref_key)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def strip_font_note(saved: str) -> tuple[str, list[str]]:
    m = re.match(r"<!-- fonts: (.*?) -->\n", saved)
    if not m:
        return saved, []
    return saved[m.end():], [f.strip() for f in m.group(1).split(",") if f.strip()]
