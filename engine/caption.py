"""인스타 캡션 생성: 요약 + 출처 목록 + 해시태그."""
from __future__ import annotations


def build_caption(data: dict, cfg: dict, items: list[dict]) -> str:
    lines = [f"{cfg['name']} | {data['date']}", "", data["one_liner"], ""]
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. {it['title']}")
        src = it["source"]
        lines.append(f"   출처: {src['name']}" + (f" {src['url']}" if src.get("url") else ""))
    lines.append("")
    lines.append(" ".join(f"#{t.lstrip('#')}" for t in cfg["hashtags"]))
    return "\n".join(lines) + "\n"
