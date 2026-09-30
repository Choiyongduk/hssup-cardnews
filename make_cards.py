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

제목과 summary 는 카드에 크게 박히는 글자입니다. 말투 규칙을 적용하지 말고
짧고 단단하게 쓰세요. caption 에만 아래 말투를 적용합니다.

명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요. 한자를 쓰지 마세요.

{voice}"""

TOOL = {
    "name": "cards",
    "description": "카드뉴스 내용을 제출합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {"type": "string"},
            "one_liner": {"type": "string"},
            "caption": {"type": "string"},
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="hssup-tips", help="channels/<이름>.yaml")
    ap.add_argument("--report-id", type=int, help="옮길 기획안 번호 (기본: 가장 최근)")
    args = ap.parse_args()

    cfg = load_channel(args.channel)
    src = cfg.get("source") or {}
    if src.get("type") != "json":
        raise SystemExit(f"{args.channel} 은 직접 쓴 내용을 받는 채널이 아닙니다.")

    report = _pick_report(args.report_id)
    print(f"기획안: [{report['kind']}] {report['title']}")

    lim = cfg["limits"]
    client = Anthropic()
    resp = client.messages.create(
        model=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
        max_tokens=4000,
        system=SYSTEM.format(
            cards=cfg["cards"],
            lines=lim["summary_lines"],
            line_limit=lim["summary_line"],
            title_limit=lim["title"],
            voice=HSSUP_VOICE,
        ),
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "cards"},
        messages=[{"role": "user", "content": report["body"]}],
    )
    out = next(b for b in resp.content if b.type == "tool_use").input

    items = out["items"][: cfg["cards"]]
    if len(items) < cfg["cards"]:
        raise SystemExit(f"카드 {cfg['cards']}장이 필요한데 {len(items)}장만 왔습니다.")

    data = {
        "date": None,
        "headline": out["headline"],
        "one_liner": out["one_liner"],
        "caption": out["caption"],
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
