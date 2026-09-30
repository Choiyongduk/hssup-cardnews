"""사용법: python make_cards.py --channel hssup-tips [--report-id 12]

박서준 팀장이 쓴 기획안을 카드뉴스 내용으로 옮깁니다.

지금까지는 기획안을 보고 사람이 JSON 으로 옮겨 적어야 카드가 나왔습니다.
그 옮겨 적는 일을 대신합니다. 여기까지 끝나면 render.py 가 그림을 그립니다.

기획안에 없는 사실을 지어내지 않는 게 핵심입니다. 문장을 카드에 맞게
다듬기만 하고, 내용을 보태지 않습니다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from anthropic import Anthropic

from engine import trends_sync
from engine.config import ROOT, load_channel
from engine.voice import HSSUP_VOICE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM = """당신은 히썹 인스타그램 계정의 카드뉴스 편집자입니다.
기획안을 받아 카드 {cards}장짜리 캐러셀 내용으로 옮깁니다.

가장 중요한 규칙 — **기획안에 없는 내용을 지어내지 마세요.**
기획안에 적힌 것을 카드 칸에 맞게 다듬기만 하세요. 기획안이 부족하면
있는 내용을 나눠서 채우고, 없는 사실을 새로 만들지 마세요.

각 항목의 조건:
- `headline` : 표지 대표 문구. {title_limit}자 이내. 완전한 문장이 아니어도 됩니다.
- `one_liner`: 마무리 카드 한 줄. 전체를 한 문장으로 눌러 담으세요.
- `items[].title` : 카드 제목. {title_limit}자 이내. 짧고 단정하게.
- `items[].summary` : 정확히 {lines}줄. 각 줄 {line_limit}자 이내.
  한 줄에 한 가지만 담고, 줄끼리 같은 말을 반복하지 마세요.
- `items[].why` : 그 카드에서 딱 하나 기억할 것. 한 문장, {line_limit}자 이내.
  summary 의 어느 줄과도 같은 말이 되면 안 됩니다.
- `caption` : 인스타 캡션. 기획안에 캡션 초안이 있으면 그걸 살려 쓰세요.
  해시태그는 넣지 마세요(따로 붙습니다).

표지는 주제에 맞는 짜임새를 고르세요. **매번 같은 얼굴이면 안 됩니다.**
{recent}

- `cover_style` : plain / quote / versus / number 중 하나
  * quote — 한 문장으로 밀어붙입니다. 주장이나 통념을 뒤집는 말에 어울립니다.
    제목을 길게(스무 자 안팎) 쓰고 핵심 어절만 대괄호로 묶으세요.
    예) "잔흔 남았다고 [무조건 레이저] 아닙니다"
  * versus — 둘을 맞세우는 주제. `versus_left` 와 `versus_right` 에 각각
    다섯 자 이내로 짧게. 예) "릴스" 대 "피드", "기술" 대 "운영"
  * number — **의미 있는 수치가 기획안에 있을 때만** 씁니다.
    `cover_number` 에 그 수치를 적으세요. 예) "8,875", "90%", "3년", "100만+"
    ⚠️ 카드가 몇 장인지(4가지, 5가지)는 수치가 아닙니다. 그건 절대 쓰지 마세요.
    기획안에 내세울 수치가 없으면 number 를 고르지 마세요.
  * plain — 위에 안 맞으면 이걸 쓰세요. 제목 하나로 단정하게 갑니다.
- `cover_bg` : orange(기본) 또는 ink. 대부분 orange 로 두고,
  무겁거나 단호한 주제일 때만 ink 를 쓰세요.
- `kicker` : 표지 맨 윗줄 작은 글씨. 한 줄, 열두 자 이내.
  매번 "OO 필독 4가지" 로 쓰지 마세요. 주제마다 달라야 합니다.
  예) "3분 정리", "많이 묻는 질문", "해보고 알았습니다", "먼저 읽어보세요"
- 표지 제목에 대괄호를 쓰면 그 부분이 강조됩니다. 한 군데만.

제목과 summary 는 카드에 크게 박히는 글자입니다. 말투 규칙을 적용하지 말고
짧고 단단하게 쓰세요. caption 에만 아래 말투를 적용합니다.

명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요. 한자를 쓰지 마세요.

{voice}"""

# 표지 짜임새. 뼈대는 같고 주인공만 바뀝니다.
ALL_STYLES = ("plain", "quote", "versus", "number")

TOOL = {
    "name": "cards",
    "description": "카드뉴스 내용을 제출합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {"type": "string"},
            "one_liner": {"type": "string"},
            "caption": {"type": "string"},
            "cover_style": {"type": "string", "enum": list(ALL_STYLES)},
            "cover_bg": {"type": "string", "enum": ["orange", "ink"]},
            "kicker": {"type": "string", "description": "표지 맨 윗줄 작은 글씨"},
            "cover_number": {"type": "string", "description": "number 스타일일 때 숫자만"},
            "cover_unit": {"type": "string", "description": "number 스타일일 때 단위"},
            "versus_left": {"type": "string", "description": "versus 스타일일 때 왼쪽"},
            "versus_right": {"type": "string", "description": "versus 스타일일 때 오른쪽"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "summary": {"type": "array", "items": {"type": "string"}},
                        "why": {"type": "string"},
                    },
                    "required": ["title", "summary", "why"],
                },
            },
        },
        "required": ["headline", "one_liner", "caption", "items"],
    },
}


def _pick_report(report_id: int | None) -> dict:
    """옮길 기획안을 고릅니다. 지정이 없으면 가장 최근 것."""
    if report_id:
        rows = trends_sync._get("ai_reports", {"select": "*", "id": f"eq.{report_id}"})
        if not rows:
            raise SystemExit(f"기획안 {report_id} 번을 찾지 못했습니다.")
        return rows[0]

    rows = trends_sync._get(
        "ai_reports",
        {"select": "*", "kind": "in.(request,plan)", "order": "created_at.desc", "limit": "1"},
    )
    if not rows:
        raise SystemExit("옮길 기획안이 없습니다.")
    return rows[0]


def _recent_styles(slug: str, limit: int = 3) -> list[str]:
    """최근에 쓴 표지 짜임새. 같은 얼굴이 이어지지 않게 하려고 봅니다."""
    folder = ROOT / "data" / "posts"
    if not folder.exists():
        return []
    files = sorted(folder.glob(f"{slug}-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for f in files[:limit]:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")).get("cover_style") or "plain")
        except Exception:
            continue
    return out


def _allowed_styles(slug: str) -> list[str]:
    """이번에 고를 수 있는 짜임새.

    "같은 건 피하라" 고 말로만 하면 안 듣습니다. 실제로 두 번 연속 같은 걸 골랐습니다.
    목록에서 빼야 안 고릅니다. 다만 고를 게 둘은 남겨둡니다.
    """
    used = _recent_styles(slug, limit=2)
    left = [s for s in ALL_STYLES if s not in set(used)]
    return left if len(left) >= 2 else list(ALL_STYLES)


def _recent_kickers(slug: str, limit: int = 4) -> list[str]:
    """최근에 쓴 맨 윗줄 문구. 같은 말이 이어지면 더 획일적으로 보입니다."""
    folder = ROOT / "data" / "posts"
    if not folder.exists():
        return []
    files = sorted(folder.glob(f"{slug}-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for f in files[:limit]:
        try:
            k = (json.loads(f.read_text(encoding="utf-8")).get("kicker") or "").strip()
            if k:
                out.append(k)
        except Exception:
            continue
    return out


def _recent_note(slug: str) -> str:
    used = _recent_styles(slug)
    kickers = _recent_kickers(slug)
    lines = []
    if used:
        lines.append(f"최근에 쓴 짜임새: {', '.join(used)} — 그래서 이번에 고를 수 있는 건 위 목록뿐입니다.")
    else:
        lines.append("앞선 게시물이 없으니 주제에 가장 맞는 것을 고르세요.")
    if kickers:
        lines.append(f"최근에 쓴 맨 윗줄: {', '.join(kickers)} — **이것들과 다른 말로 쓰세요.**")
    return "\n".join(lines)


def _sections(body: str) -> list[str]:
    """리포트 하나에 기획안이 여러 개 들어 있을 때 나눕니다.

    요청을 여러 건 한 번에 처리하면 한 리포트에 같이 담깁니다.
    그중 하나만 카드로 만들고 싶을 때가 있습니다.
    """
    parts = [p.strip() for p in body.split("\n---\n")]
    return [p for p in parts if p]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="hssup-tips", help="channels/<이름>.yaml")
    ap.add_argument("--report-id", type=int, help="옮길 기획안 번호 (기본: 가장 최근)")
    ap.add_argument("--section", type=int,
                    help="리포트에 기획안이 여러 개면 몇 번째를 쓸지 (1부터)")
    args = ap.parse_args()

    cfg = load_channel(args.channel)
    src = cfg.get("source") or {}
    if src.get("type") != "json":
        raise SystemExit(f"{args.channel} 은 직접 쓴 내용을 받는 채널이 아닙니다.")

    report = _pick_report(args.report_id)
    body = report["body"]
    if args.section:
        parts = _sections(body)
        if not (1 <= args.section <= len(parts)):
            raise SystemExit(f"기획안이 {len(parts)}개인데 {args.section}번을 달라고 했습니다.")
        body = parts[args.section - 1]
        print(f"기획안: [{report['kind']}] {report['title']} — {args.section}번째")
    else:
        print(f"기획안: [{report['kind']}] {report['title']}")

    lim = cfg["limits"]

    # 고를 수 있는 짜임새만 남겨 건넵니다. 목록에 없으면 고를 수 없습니다.
    allowed = _allowed_styles(cfg["slug"])
    tool = json.loads(json.dumps(TOOL))
    tool["input_schema"]["properties"]["cover_style"]["enum"] = allowed
    print(f"고를 수 있는 표지: {', '.join(allowed)}")

    client = Anthropic()
    resp = client.messages.create(
        model=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
        max_tokens=4000,
        system=SYSTEM.format(
            cards=cfg["cards"],
            lines=lim["summary_lines"],
            line_limit=lim["summary_line"],
            title_limit=lim["title"],
            recent=_recent_note(cfg["slug"]),
            voice=HSSUP_VOICE,
        ),
        tools=[tool],
        tool_choice={"type": "tool", "name": "cards"},
        messages=[{"role": "user", "content": body}],
    )
    out = next(b for b in resp.content if b.type == "tool_use").input

    items = out["items"][: cfg["cards"]]
    if len(items) < cfg["cards"]:
        raise SystemExit(f"카드 {cfg['cards']}장이 필요한데 {len(items)}장만 왔습니다.")

    style = out.get("cover_style") or "plain"
    number = (out.get("cover_number") or "").strip()
    has_versus = bool(out.get("versus_left") and out.get("versus_right"))
    # 카드 장 수를 수치라고 내놓는 일이 잦습니다. 그건 숫자형의 주인공이 아닙니다.
    has_number = bool(number) and number != str(cfg["cards"])

    def _viable(s: str) -> bool:
        if s == "versus":
            return has_versus
        if s == "number":
            return has_number
        return True

    # 짜임새마다 꼭 있어야 하는 게 빠지면 쓸 수 없습니다.
    if not _viable(style):
        print(f"  ! {style} 에 필요한 값이 없습니다")
        style = "plain"

    # 목록에 없는 걸 골라 오는 일이 있습니다. 도구 제약은 강제가 아닙니다.
    # 같은 얼굴이 이어지지 않으려고 좁혀둔 것이므로 여기서 다시 막습니다.
    if style not in allowed:
        replacement = next((s for s in allowed if _viable(s)), "plain")
        print(f"  ! {style} 는 최근에 써서 뺐습니다 → {replacement}")
        style = replacement

    data = {
        "date": None,
        "headline": out["headline"],
        "one_liner": out["one_liner"],
        "caption": out["caption"],
        "cover_style": style,
        "cover_bg": out.get("cover_bg") or "orange",
        "kicker": (out.get("kicker") or "").strip(),
        "cover_number": number,
        "cover_unit": (out.get("cover_unit") or "").strip(),
        "versus_left": (out.get("versus_left") or "").strip(),
        "versus_right": (out.get("versus_right") or "").strip(),
        "items": [
            {
                "title": it["title"],
                "summary": it["summary"][: lim["summary_lines"]],
                "why": it["why"],
                # 직접 쓴 기획물이라 인용할 출처가 없습니다. 카드에도 안 나옵니다.
                "source": {"name": cfg["name"], "url": ""},
            }
            for it in items
        ],
    }

    path = ROOT / src.get("path", "data/cards.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"카드 내용 저장: {path.relative_to(ROOT)}")
    print(f"  표지: {data['headline']}")
    for i, it in enumerate(data["items"], 1):
        print(f"  {i}. {it['title']}")
    print()
    print("이제 render.py 로 그림을 그립니다:")
    print(f"  python render.py --channel {args.channel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
