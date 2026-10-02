"""사용법: python make_study_cards.py [--dry] [--limit 5]

수강생 복습 카드. 앱 꿀팁 글(tips)마다 질문과 답 카드를 3~5장 만듭니다.
lazyowen 가이드의 "공부 도우미 프롬프트"를 수강생 앱에 들인 것입니다.

- **원장님이 쓴 글 내용만으로** 만듭니다. 글에 없는 지식을 보태지 않습니다.
  반영구는 위생과 안전이 걸린 일이라, AI 가 아는 척 보탠 답이 수강생에게 가면 안 됩니다.
- 만든 카드는 바로 보이지 않습니다. 원장님이 글 아래에서 확인하고 "공개" 를 눌러야 수강생에게 보입니다.
- 글을 고치면 내용 지문(hash)이 달라져 다음 실행 때 카드를 새로 만들고 다시 검수 전으로 돌립니다.
- 짧은 글(구매처 안내처럼)은 건너뜁니다.

앱 쪽 칸: tips.study_cards, tips.study_cards_ok (hssup-app db/2026-10-02_tip_study_cards.sql)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

import requests

from engine import llm, trends_sync
from engine.config import ROOT  # noqa: F401  (.env 를 읽어 환경변수를 채웁니다)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MIN_CHARS = 150

SYSTEM = """당신은 히썹 반영구 아카데미의 복습 도우미입니다. 원장님이 쓴 글 하나를 읽고
수강생이 스스로 확인해 볼 복습 카드(질문과 답)를 만드세요.

- **글에 적힌 내용만으로** 질문과 답을 만드세요. 글에 없는 지식, 숫자, 제품, 이유를 보태지 마세요.
  답을 글에서 찾을 수 없는 질문은 만들지 마세요.
- 카드는 3~5장. 글이 짧으면 3장. 외울 만한 핵심(순서, 주의할 점, 원인과 해결, 구분법)을 고르세요.
- 질문은 한 줄, 수강생이 실제로 헷갈릴 만한 것으로. "~은 무엇인가요?" 보다 "~할 때 먼저 확인할 것은?" 처럼 쓰임새가 보이게.
- 답은 한두 문장. 글의 표현을 살리되 짧게.
- 존댓말. 한자를 쓰지 마세요. 명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요.

JSON 배열 하나로만 답하세요. 예: [{"q": "질문", "a": "답"}]"""


def _hash(tip: dict) -> str:
    return hashlib.sha1(f"{tip.get('title')}\n{tip.get('content')}".encode("utf-8")).hexdigest()[:12]


def _cards(tip: dict) -> list[dict]:
    resp = llm.client().messages.create(
        model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-5"),
        max_tokens=2000,
        system=SYSTEM,
        messages=[{"role": "user", "content": f"[글 제목] {tip['title']}\n[분류] {tip.get('category')}\n\n{tip['content']}"}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    cards = json.loads(text[text.index("["): text.rindex("]") + 1])
    return [{"q": " ".join(str(c["q"]).split()), "a": " ".join(str(c["a"]).split()).replace("·", ", ")}
            for c in cards if c.get("q") and c.get("a")][:5]


def _save(tip_id: str, value: dict) -> None:
    url, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    resp = requests.patch(
        f"{url}/rest/v1/tips",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "Prefer": "return=minimal"},
        params={"id": f"eq.{tip_id}"},
        json={"study_cards": value, "study_cards_ok": False},
        timeout=30,
    )
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"복습 카드 저장 실패: {resp.status_code} {resp.text}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true", help="저장하지 않고 보여주기만")
    parser.add_argument("--limit", type=int, default=5, help="한 번에 만들 글 수")
    args = parser.parse_args()

    query = {"select": "id,title,category,content,study_cards", "is_active": "eq.true", "order": "created_at.desc"}
    try:
        tips = trends_sync._get("tips", query)
    except Exception as e:
        if args.dry:   # 칸이 없어도 미리보기는 되게
            tips = trends_sync._get("tips", {**query, "select": "id,title,category,content"})
        else:
            # 앱에 칸을 아직 안 만들었으면(SQL 미실행) 조용히 넘어간다. 아침 브리핑을 막지 않게.
            print(f"  ! 꿀팁 글을 읽지 못했습니다(복습 카드 칸이 아직 없을 수 있습니다): {e}")
            return 0

    todo = [t for t in tips if len(t.get("content") or "") >= MIN_CHARS
            and (t.get("study_cards") or {}).get("hash") != _hash(t)][: args.limit]
    if not todo:
        print("새로 만들 복습 카드가 없습니다")
        return 0

    for tip in todo:
        try:
            cards = _cards(tip)
        except Exception as e:
            print(f"  ! 「{tip['title']}」 카드를 만들지 못했습니다: {e}")
            continue
        print(f"\n「{tip['title']}」 {len(cards)}장")
        for c in cards:
            print(f"  Q. {c['q']}\n  A. {c['a']}")
        if not args.dry and cards:
            _save(tip["id"], {"hash": _hash(tip), "cards": cards})
    return 0


if __name__ == "__main__":
    sys.exit(main())
