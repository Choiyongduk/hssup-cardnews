"""영상에 자막을 붙입니다. 원장님이 찍은 영상에서 말소리를 받아 적어 화면 아래에 얹습니다.

1) 받아 적기: faster-whisper(무료, 내 컴퓨터에서 돈다). 없으면 CI 에서 처음 한 번 깐다.
2) 다듬기: 받아 적은 글은 반영구 용어를 자주 틀린다. AI 가 앞뒤 맥락(원장님 메모, 캡션)을 보고
   맞춤법과 용어만 고친다. 말을 바꾸거나 보태지는 않는다.
3) 그리기: 자막 줄마다 투명 PNG 를 브라우저로 그린다(카드뉴스와 같은 Pretendard 글꼴).
   ffmpeg 의 자막 필터는 우리 글꼴 파일(woff2)을 못 읽어서 이 방식을 쓴다.
   video_overlay.render_video_overlay 가 시간에 맞춰 영상 위에 얹는다.

자막은 승인 payload 의 `subtitles` 에 [{"start","end","text"}] 로 남는다. 시안 대화에서
"자막 둘째 줄 틀렸어" 하면 영상을 다시 받아 적지 않고 이 목록만 고쳐 다시 입힌다.

말소리가 없거나(음악만) 받아 적기에 실패하면 빈 목록. 자막 없이 예전처럼 나간다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .config import ROOT

MODEL = os.environ.get("WHISPER_MODEL", "small")
MAX_CHARS = 30          # 한 자막에 이 글자보다 길면 시간을 나눠 두 자막으로
BOTTOM = 560            # 화면 아래에서 자막 아래끝까지. 릴스 화면의 캡션, 버튼에 안 가리게


def _whisper():
    try:
        from faster_whisper import WhisperModel  # noqa: F401
    except ImportError:
        if not os.environ.get("GITHUB_ACTIONS"):
            raise
        # 영상이 올 때만 필요해서 requirements 에 넣지 않았다. 다른 일들이 무거워지지 않게.
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "faster-whisper"], check=True)
    from faster_whisper import WhisperModel
    return WhisperModel(MODEL, device="cpu", compute_type="int8")


def transcribe(video_path: Path) -> list[dict]:
    """말소리를 시간과 함께 받아 적습니다."""
    segments, _ = _whisper().transcribe(
        str(video_path), language="ko", vad_filter=True, beam_size=5,
        condition_on_previous_text=False,   # 앞 문장을 끌고 가며 같은 말을 되풀이하는 걸 막는다
    )
    out = []
    for s in segments:
        text = " ".join(s.text.split())
        # 말이 아닌 소리(음악, 잡음)를 글로 지어내는 걸 거른다
        if not text or s.no_speech_prob > 0.6 or s.avg_logprob < -1.0:
            continue
        out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": text})
    return out


POLISH = """영상에서 받아 적은 자막입니다. 받아 적기 프로그램이 틀린 글자를 고쳐 주세요.
반영구 아카데미(히썹) 원장님이 찍은 영상입니다. 자주 틀리는 말: 반영구, 엠보, 콤보, 섀도우, 수지, 잔흔,
리터치, 니들, 색소, 디자인, 수강생, 원장님.

- 맞춤법, 띄어쓰기, 잘못 들은 단어만 고치세요. 말투와 내용은 그대로. 말을 보태거나 줄이지 마세요.
- "음", "어" 같은 군소리는 빼도 됩니다.
- 줄 수와 순서는 그대로. 받은 것과 똑같은 개수의 문자열을 JSON 배열 하나로만 답하세요.

[참고: 원장님 메모와 캡션]
{hint}"""


def polish(segments: list[dict], hint: str = "") -> list[dict]:
    """맞춤법과 용어만 고칩니다. 실패하면 받아 적은 그대로 씁니다."""
    if not segments:
        return segments
    try:
        from . import llm

        resp = llm.client().messages.create(
            model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-5"),
            max_tokens=2000,
            system=POLISH.format(hint=(hint or "(없음)")[:1500]),
            messages=[{"role": "user", "content": json.dumps([s["text"] for s in segments], ensure_ascii=False)}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        lines = json.loads(text[text.index("["): text.rindex("]") + 1])
        if len(lines) != len(segments):
            print(f"  ! 자막 다듬기: 줄 수가 달라 받아 적은 그대로 씁니다 ({len(lines)} != {len(segments)})")
            return segments
        return [{**s, "text": " ".join(str(t).split())} for s, t in zip(segments, lines) if str(t).strip()]
    except Exception as e:
        print(f"  ! 자막 다듬기 실패, 받아 적은 그대로 씁니다: {e}")
        return segments


def split_long(segments: list[dict]) -> list[dict]:
    """한 화면에 너무 긴 자막은 띄어쓰기에서 둘로 나누고 시간도 글자 수만큼 나눕니다."""
    out = []
    for s in segments:
        text = s["text"]
        if len(text) <= MAX_CHARS or " " not in text:
            out.append(s)
            continue
        mid = len(text) // 2
        cut = min((m.start() for m in re.finditer(" ", text)), key=lambda i: abs(i - mid))
        a, b = text[:cut].strip(), text[cut:].strip()
        t = s["start"] + (s["end"] - s["start"]) * len(a) / max(1, len(a) + len(b))
        out += split_long([{"start": s["start"], "end": round(t, 2), "text": a}])
        out += split_long([{"start": round(t, 2), "end": s["end"], "text": b}])
    return out


def make(video_path: Path, hint: str = "") -> list[dict]:
    """받아 적고 다듬어 자막 목록을 돌려줍니다. 어디서 실패해도 빈 목록(자막 없이 진행)."""
    try:
        raw = transcribe(video_path)
    except Exception as e:
        print(f"  ! 자막 받아 적기 실패, 자막 없이 갑니다: {e}")
        return []
    if not raw:
        print("  - 말소리가 없어 자막을 넣지 않습니다")
        return []
    subs = split_long(polish(raw, hint))
    print(f"  - 자막 {len(subs)}줄")
    return subs


SUB_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
@font-face {{ font-family: P; src: url('{font}') format('woff2'); font-weight: 700; }}
html, body {{ margin: 0; background: transparent; }}
body {{ width: {w}px; height: {h}px; position: relative; }}
.sub {{ position: absolute; left: 50%; bottom: {bottom}px; transform: translateX(-50%);
  max-width: {maxw}px; width: max-content; text-align: center;
  font-family: P, sans-serif; font-weight: 700; font-size: 54px; line-height: 1.32; letter-spacing: -0.5px;
  color: #fff; word-break: keep-all; overflow-wrap: break-word;
  background: rgba(0,0,0,0.58); border-radius: 18px; padding: 14px 30px; }}
</style></head><body><div class="sub" id="s"></div></body></html>"""


def render_pngs(segments: list[dict], out_dir: Path, width: int, height: int) -> list[tuple[Path, float, float]]:
    """자막 줄마다 투명 PNG 하나. 브라우저 한 번 띄워 줄만 바꿔 가며 찍습니다."""
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "sub.html"
    html_path.write_text(SUB_HTML.format(
        font=(ROOT / "assets" / "fonts" / "Pretendard-Bold.woff2").as_uri(),
        w=width, h=height, bottom=BOTTOM, maxw=width - 140,
    ), encoding="utf-8")
    shots = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        page.goto(html_path.as_uri())
        page.evaluate("document.fonts.ready")
        for i, s in enumerate(segments):
            page.evaluate("t => { document.getElementById('s').textContent = t }", s["text"])
            png = out_dir / f"sub_{i:03d}.png"
            page.screenshot(path=str(png), omit_background=True)
            shots.append((png, float(s["start"]), float(s["end"])))
        browser.close()
    html_path.unlink(missing_ok=True)
    return shots
