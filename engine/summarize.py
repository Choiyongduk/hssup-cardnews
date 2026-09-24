"""원문 기사 텍스트 → 카드뉴스 JSON. Claude API의 tool_use로 sources.py 스키마를 강제 출력합니다."""
from __future__ import annotations

import os

from anthropic import Anthropic

# 프롬프트로도 가끔 새는 한자 혼용(국가명 약칭 "美·中" 등, "에너지發" 등)에 대한 코드 레벨 안전망.
_HANJA_FIXES = {
    "發": "발",
    "美": "미국",
    "中": "중국",
    "日": "일본",
    "英": "영국",
    "獨": "독일",
    "佛": "프랑스",
    "露": "러시아",
    "韓": "한국",
    "北": "북한",
}


def _clean_hanja(text: str) -> str:
    if not isinstance(text, str):
        return text
    for han, kor in _HANJA_FIXES.items():
        text = text.replace(han, kor)
    return text


def _clean_hanja_in(data: dict) -> dict:
    data["headline"] = _clean_middot(_clean_hanja(data.get("headline", "")))
    data["one_liner"] = _clean_hanja(data.get("one_liner", ""))
    for it in data.get("items", []):
        it["title"] = _clean_middot(_clean_hanja(it.get("title", "")))
        it["summary"] = [_clean_hanja(line) for line in it.get("summary", [])]
        it["why"] = _clean_hanja(it.get("why", ""))
    return data


def _clean_middot(text: str) -> str:
    """headline/title에 프롬프트로도 가끔 새는 가운뎃점(·)에 대한 코드 레벨 안전망."""
    if not isinstance(text, str):
        return text
    return text.replace("·", " ").replace("  ", " ").strip()

def _system_prompt(topic: str) -> str:
    return f"""당신은 {topic} 카드뉴스 편집자입니다. 아래 원칙을 반드시 지키세요.
- 원문에 없는 사실을 추가하지 마세요.
- 원문 문장을 그대로 옮기지 말고 재서술하세요.
- 각 기사의 출처명을 정확히 표기하세요.
- 과장하거나 클릭베이트성 표현을 쓰지 마세요.
- 존댓말, 간결한 뉴스체로 작성하세요.
- 해외 기사와 국내 기사를 함께 다루더라도 문체와 톤을 통일하세요.
- 한자를 단 한 글자도 쓰지 마세요. "發"를 접미사로 붙이는 표현("에너지發", "중앙그룹發" 등)을 절대 쓰지 말고 반드시 한글 "발"로 적으세요 (예: "에너지발", "중앙그룹발"). 국가명도 한자 약칭(美, 中, 日, 英 등) 대신 한글로 쓰세요 (예: "美 이란 협상" 금지 → "미국 이란 협상"). 고유명사를 제외한 모든 단어는 한글로만 작성하세요.
- headline과 title에는 가운뎃점(·)을 절대 쓰지 마세요. "신약·AI커머스"처럼 두 단어만 연결하는 경우도 금지입니다. 여러 소재를 다뤄야 하면 쉼표나 자연스러운 문장으로 풀어 쓰거나, 가장 핵심적인 사실 하나만 골라 구체적인 문장으로 표현하세요."""


DEFAULT_TOPIC = "뉴스"

EMIT_TOOL = {
    "name": "emit_cardnews",
    "description": "요약 결과를 카드뉴스 스키마에 맞춰 제출합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {"type": "string", "description": "표지 대표 헤드라인 (30자 이내 권장)"},
            "one_liner": {"type": "string", "description": "마무리 카드용 오늘의 한 줄 총평"},
            "items": {
                "type": "array",
                "description": "기사 순서와 동일한 개수의 카드",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "카드 제목 (30자 이내 권장)"},
                        "summary": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 3,
                            "maxItems": 3,
                            "description": "핵심 내용 3줄 (줄당 40자 이내 권장)",
                        },
                        "why": {"type": "string", "description": "이 소식이 왜 중요한지 1줄"},
                        "source": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "url": {"type": "string"},
                            },
                            "required": ["name", "url"],
                        },
                    },
                    "required": ["title", "summary", "why", "source"],
                },
            },
        },
        "required": ["headline", "one_liner", "items"],
    },
}

DEFAULT_MODEL = "claude-sonnet-5"
CLASSIFY_MODEL = "claude-haiku-4-5-20251001"

SELECT_TOOL = {
    "name": "select_articles",
    "description": "채널 주제에 맞는 기사만 관련도 순으로 골라 제출합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "indices": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "채널 주제에 맞는 기사의 0부터 시작하는 인덱스, 관련도 높은 순",
            }
        },
        "required": ["indices"],
    },
}


def filter_relevant(titles: list[str], topic: str, limit: int) -> list[int]:
    """제목만 보고 topic에 맞는 기사를 관련도 순으로 최대 limit개 골라 인덱스로 반환합니다.
    본문 추출(느리고 비용 드는 작업) 전에 걸러내기 위한 저비용 사전 분류입니다."""
    if not titles:
        return []
    client = Anthropic()
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(titles))
    prompt = (
        f"아래는 뉴스 제목 목록입니다. 이 중 채널 주제 '{topic}'을 핵심 소재로 직접 다루는 기사만, "
        f"관련도가 높은 순서로 최대 {limit}개 골라 select_articles 도구로 제출하세요. "
        f"제목에 주제와 관련된 단어가 하나라도 있다고 포함시키지 말고, 기사의 핵심 소재가 실제로 "
        f"주제와 일치하는지 엄격하게 판단하세요 (막연히 비슷한 업종·분야라는 이유만으로 포함시키지 마세요). "
        f"같은 사건을 속보·후속 보도 등으로 여러 번 다룬 제목이 있으면, "
        f"가장 정보가 자세한 것 하나만 남기고 나머지는 제외하세요. "
        f"엄격히 봤을 때 주제에 맞는 기사가 하나도 없으면 빈 배열을 제출하세요 — "
        f"억지로 관련 없는 기사를 채워 넣으면 안 됩니다.\n\n{numbered}"
    )
    try:
        resp = client.messages.create(
            model=CLASSIFY_MODEL,
            max_tokens=1024,
            tools=[SELECT_TOOL],
            tool_choice={"type": "tool", "name": "select_articles"},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        return []
    for block in resp.content:
        if block.type == "tool_use" and block.name == "select_articles":
            return [i for i in block.input.get("indices", []) if 0 <= i < len(titles)]
    return []


def generate(articles: list[dict], model: str | None = None, topic: str = DEFAULT_TOPIC) -> dict:
    """articles: [{"title", "url", "source_name", "body"}, ...] → 표준 카드뉴스 dict (date 제외)."""
    client = Anthropic()

    blocks = []
    for i, a in enumerate(articles, 1):
        blocks.append(
            f"[기사 {i}]\n제목: {a['title']}\n출처: {a['source_name']}\nURL: {a['url']}\n본문:\n{a['body']}"
        )
    user_prompt = (
        f"아래 {len(articles)}개의 기사를 각각 카드 1장 분량으로 요약해 emit_cardnews 도구로 제출하세요.\n"
        f"items 배열은 기사 순서를 그대로 유지하세요. headline과 one_liner는 전체 기사를 아우르는 내용으로 작성하세요.\n\n"
        + "\n\n".join(blocks)
    )

    resp = client.messages.create(
        model=model or os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
        max_tokens=4096,
        system=_system_prompt(topic),
        tools=[EMIT_TOOL],
        tool_choice={"type": "tool", "name": "emit_cardnews"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    for block in resp.content:
        if block.type == "tool_use" and block.name == "emit_cardnews":
            return _clean_hanja_in(block.input)
    raise RuntimeError("Claude가 emit_cardnews 도구를 호출하지 않았습니다.")
