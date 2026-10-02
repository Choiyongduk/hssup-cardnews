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

from . import brand, illustrate
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
- 새 그림(일러스트, 배경, 소품 그림)이 필요하면 `illustrations` 에 영어로 설명을 적으세요. 최대 2장.
  첫 번째는 {{{{ILLUST_1}}}}, 두 번째는 {{{{ILLUST_2}}}} 로 씁니다. 1024x1024 정사각형으로 그려지니
  object-fit 으로 맞추세요. 그림 모델은 글자를 못 쓰니 글자는 그림에 넣지 말고 HTML 로 얹으세요.
  화풍, 색감, 구도까지 구체적으로 쓰면 잘 나옵니다. {illust_note}
- 그 밖의 바깥 주소(인터넷 이미지 등)는 불러와지지 않습니다.

[원칙]
- 폰에서 읽혀야 합니다. 읽으라고 넣은 글자는 28px 아래로 내리지 마세요.
  장식으로 넣은 작은 글자에는 data-deco 를 붙이세요.
- 한글은 word-break: keep-all 로 단어가 잘리지 않게 하세요.
- 색, 글꼴, 로고는 아래 [히썹 디자인 기준]을 따르세요. 시그니처 주황은 #FA5500 입니다.
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
            "illustrations": {
                "type": "array", "maxItems": 2,
                "description": "새로 그릴 그림. 필요 없으면 빈 배열",
                "items": {"type": "object", "properties": {
                    "prompt": {"type": "string", "description": "영어로 쓴 그림 설명 (화풍, 색, 구도)"}},
                    "required": ["prompt"]},
            },
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
            "illustrations": {
                "type": "array", "maxItems": 2,
                "description": "fix 에서 그림을 새로 그려야 할 때만. 지금 그림을 그대로 쓰면 빈 배열",
                "items": {"type": "object", "properties": {
                    "prompt": {"type": "string", "description": "영어로 쓴 그림 설명 (화풍, 색, 구도)"}},
                    "required": ["prompt"]},
            },
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


def _ask(client, model: str, system: str, content: list[dict], tool: dict) -> dict:
    """한 번 묻고, 그 도구의 형식으로 답을 받습니다.

    그리기와 검토는 각각 따로 묻습니다(이어지는 대화가 아님). 구독(claude -p)은 한 번에
    한 말만 받아서, 이렇게 해야 원장님 클로드 구독으로 돌 수 있습니다. 구독이 안 되면
    llm 이 API 로 넘깁니다.

    Opus 5.5 는 API 에서 특정 도구를 강제하는 옵션을 받지 않아서, 도구를 하나만 주고
    글로 부탁합니다. 그래도 안 쓰면 처음부터 한 번 더 묻습니다.
    """
    ask = [*content, {"type": "text", "text": f"`{tool['name']}` 도구로 답해 주세요."}]
    for _ in range(2):
        resp = client.messages.create(
            model=model, max_tokens=16000, system=system,
            messages=[{"role": "user", "content": ask}],
            tools=[tool], output_config={"effort": "high"},
        )
        call = next((b for b in resp.content if b.type == "tool_use" and b.name == tool["name"]), None)
        if call:
            return call.input
        if resp.stop_reason == "refusal":
            raise RuntimeError("디자인 요청을 거절당했습니다")
    raise RuntimeError(f"{tool['name']} 도구로 답하지 않았습니다 (stop_reason={resp.stop_reason})")


def _b64_block(data: bytes, kind: str = "image/png") -> dict:
    """그림 조각. 구독 쪽은 한 번에 10MB 까지만 받아서, 보낼 그림은 모두 JPEG 로 줄여 보낸다."""
    try:
        from io import BytesIO

        from PIL import Image

        im = Image.open(BytesIO(data)).convert("RGB")
        im.thumbnail((1280, 1280))
        buf = BytesIO()
        im.save(buf, "JPEG", quality=85)
        data, kind = buf.getvalue(), "image/jpeg"
    except Exception:
        pass   # 못 줄이면 원래대로
    return {"type": "image", "source": {"type": "base64", "media_type": kind, "data": base64.b64encode(data).decode()}}


def _shrink(blocks: list[dict] | None) -> list[dict]:
    """다른 데서 받은 그림 조각(참고 사진, 지금 시안)도 같은 크기로 줄인다."""
    out = []
    for b in blocks or []:
        src = b.get("source") or {}
        if b.get("type") == "image" and src.get("type") == "base64":
            out.append(_b64_block(base64.b64decode(src["data"]), src.get("media_type", "image/png")))
        else:
            out.append(b)
    return out


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
            if url.startswith("file:") or any(h in url for h in ALLOWED_HOSTS):
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


# 그려 둔 HTML 이 불러와도 되는 바깥 주소. 구글 글꼴, 그리고 새로 그린 그림을 올려 둔 에셋 저장소.
ALLOWED_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com", "raw.githubusercontent.com")


def _illustrate(html: str, items: list[dict] | None, channel: str, folder: Path) -> tuple[str, list[str]]:
    """디자인이 부탁한 새 그림을 그려 {{ILLUST_n}} 자리에 넣습니다.

    그린 그림은 에셋 저장소에 올려 그 주소를 넣습니다. 그래야 디자인을 떠두거나
    저장해서 나중에 다시 그려도 그림이 남아 있습니다. 못 그리면 자리를 비우고
    그 사실을 검토 단계에 알립니다(검토가 그림 없이도 되게 고친다).
    """
    missing = []
    for i, item in enumerate((items or [])[:2], 1):
        slot = "{{ILLUST_%d}}" % i
        if slot not in html:
            continue
        try:
            if not illustrate.available():
                raise RuntimeError("그림 서버가 연결되지 않았습니다")
            path = folder / f"illust{i}.jpg"
            path.write_bytes(illustrate.generate(item["prompt"]))
            print(f"  - 새 그림 {i}: {item['prompt'][:60]}")
            url = path.resolve().as_uri()
            try:
                from . import assets

                url = assets.upload_images([path], channel, f"illust/{os.urandom(4).hex()}")[0]
            except Exception as e:
                print(f"  ! 새 그림을 저장소에 올리지 못해 이번 그리기에만 씁니다: {e}")
            html = html.replace(slot, url)
        except Exception as e:
            print(f"  ! 새 그림 {i} 실패: {e}")
            html = html.replace(slot, "")
            missing.append(f"새 그림 {i}을 그리지 못해 빈자리로 남았습니다. 그림 없이도 보기 좋게 고쳐 주세요")
    return html, missing


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
    channel: str = "hssup-academy",
) -> dict:
    """한 장을 그립니다.

    references: 원장님이 보낸 참고 사진 (attachments.image_blocks 결과)
    current:    지금 올라와 있는 시안 그림
    previous_html: 이 게시물을 전에 이렇게 그렸다면 그 HTML. 이어서 고친다.

    돌려주는 값: {"png": Path, "html", "fonts", "notes", "problems"}
    problems 가 남아 있으면 끝내 못 고친 것이다. 쓸지는 부른 쪽에서 정한다.
    """
    from . import llm

    client = client or llm.client()   # 구독 먼저, 안 되면 API
    model = os.environ.get("DESIGN_MODEL", DEFAULT_MODEL)
    tmp = Path(tempfile.mkdtemp())
    photos = _download(photo_urls, tmp)
    out_path = out_path or tmp / "design.png"

    references, current = _shrink(references), _shrink(current)
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
        illust_note="" if illustrate.available() else "(지금은 그림 서버가 연결되지 않아 새 그림을 쓸 수 없습니다. 비워 두세요.)",
        fonts=", ".join(GOOGLE_FONTS),
    ) + brand.guide_block("히썹 디자인 기준 — 그리기 전에 읽고 반드시 따르세요. 참고 사진과 부딪치면 색과 로고는 이 기준을 따릅니다")
    drawn = _ask(client, model, system, content, DRAW_TOOL)
    html, fonts, notes = drawn["html"], drawn.get("fonts") or [], drawn.get("notes", "")
    html, missing = _illustrate(html, drawn.get("illustrations"), channel, tmp)

    problems = missing + render(html, fonts, photos, out_path)
    for round_no in range(1, MAX_REVIEWS + 1):
        checks = ("기계 검사에서 걸린 것:\n- " + "\n- ".join(problems)) if problems else "기계 검사는 통과했습니다."
        # 검토도 따로 묻는다. 무엇을 보고 그렸는지(content)와 그린 HTML, 결과 그림을 같이 준다.
        review = _ask(client, model, system, [
            *content,
            {"type": "text", "text": f"[당신이 그린 HTML]\n{html}"},
            {"type": "text", "text": "[그 HTML 을 그림으로 뽑은 결과]"},
            _b64_block(out_path.read_bytes()),
            {"type": "text", "text": REVIEW.format(checks=checks)},
        ], REVIEW_TOOL)
        verdict = review.get("verdict")
        print(f"  - 검토 {round_no}: {verdict} {(review.get('problems') or '')[:80]}")
        if verdict == "ok" and not problems:
            break
        if review.get("html"):
            html = review["html"]
            fonts = review.get("fonts") or fonts
            notes = review.get("notes") or notes
            html, missing = _illustrate(html, review.get("illustrations"), channel, tmp)
            problems = missing + render(html, fonts, photos, out_path)
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
