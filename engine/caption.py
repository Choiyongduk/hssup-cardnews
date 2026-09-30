"""인스타 캡션 생성: 요약 + 출처 목록 + 해시태그."""
from __future__ import annotations


def build_caption(data: dict, cfg: dict, items: list[dict]) -> str:
    tags = " ".join(f"#{t.lstrip('#')}" for t in cfg["hashtags"])

    # 직접 쓴 캡션이 있으면 그대로 씁니다. 기사 요약이 아닌 기획물은
    # 자동으로 짜맞춘 목록보다 사람이 쓴 글이 낫습니다.
    written = (data.get("caption") or "").strip()
    if written:
        parts = [written] if tags in written else [written, tags]
        return "\n\n".join(parts) + "\n"

    lines = [f"{cfg['name']} | {data['date']}", "", data["one_liner"], ""]
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. {it['title']}")
        # 출처가 있는 기사에만 출처를 붙입니다. 직접 쓴 기획물에는 붙일 게 없습니다.
        src = it.get("source") or {}
        if src.get("url"):
            lines.append(f"   출처: {src['name']} {src['url']}")
    lines.append("")
    lines.append(tags)
    return "\n".join(lines) + "\n"
