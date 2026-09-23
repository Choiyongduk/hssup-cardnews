"""데이터 검증: 스키마 오류는 중단, 길이 초과는 경고만 출력."""
from __future__ import annotations


def validate(data: dict, cfg: dict) -> list[str]:
    errors, warnings = [], []
    lim = cfg["limits"]

    for key in ("headline", "one_liner", "items"):
        if not data.get(key):
            errors.append(f"필수 항목 누락: {key}")

    items = data.get("items") or []
    need = cfg.get("cards", len(items))
    if len(items) < need:
        errors.append(f"뉴스 {need}건이 필요한데 {len(items)}건뿐입니다.")

    for i, it in enumerate(items[:need], 1):
        for key in ("title", "summary", "why", "source"):
            if not it.get(key):
                errors.append(f"뉴스 {i}: {key} 누락")
        if len(it.get("title", "")) > lim["title"]:
            warnings.append(f"뉴스 {i} 제목 {len(it['title'])}자 (기준 {lim['title']}자)")
        lines = it.get("summary", [])
        if len(lines) != lim["summary_lines"]:
            warnings.append(f"뉴스 {i} 요약 {len(lines)}줄 (기준 {lim['summary_lines']}줄)")
        for j, line in enumerate(lines, 1):
            if len(line) > lim["summary_line"]:
                warnings.append(f"뉴스 {i} 요약 {j}줄째 {len(line)}자 (기준 {lim['summary_line']}자)")
        if not (it.get("source") or {}).get("name"):
            errors.append(f"뉴스 {i}: 출처명 누락")

    if errors:
        raise ValueError("데이터 오류:\n  - " + "\n  - ".join(errors))
    return warnings
