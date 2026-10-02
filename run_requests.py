"""사용법: python run_requests.py [--channel hssup-main]

원장님이 "지금" 으로 올린 콘텐츠 요청을 바로 기획안으로 만듭니다.
주간 기획(plan_content.py)과 달리 요청한 것만 다루는 짧은 기획안입니다.

답변봇과 같은 워크플로에서 몇 분마다 돌기 때문에, 적어두면 곧 결과가 나옵니다.
작업 큐를 따로 만들지 않은 것도 그래서입니다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from engine import brand, llm

from engine import attachments, feed, telegram, trends_sync
from engine.config import ROOT, load_channel
from engine.voice import HSSUP_VOICE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM = """당신은 {name} 인스타그램 계정의 콘텐츠 기획자입니다.
원장님이 직접 올린 요청을 기획안으로 만드세요. 요청한 것만 다루고, 다른 제안은 덧붙이지 마세요.

원칙:
- 요청 하나당 기획 하나입니다.
- 근거는 **이 계정의 실제 데이터**에서 가져오세요. 어떤 게시물이 어떤 숫자를 냈는지 인용하세요.
- 요청 내용이 성과 데이터와 어긋나도 만들어 주세요. 대신 무엇이 우려되는지 근거에 한 줄 적으세요.
- 촬영이 현실적으로 가능한 것만 쓰세요. 이 계정은 반영구 시술과 교육을 하는 곳입니다.
- 없는 수치를 지어내지 마세요.
- 요청에 참고 사진이 붙어 있으면 직접 보고, 무엇을 따라 하면 되는지 촬영과 형식에 구체적으로 녹이세요.
- 명사 3개 이상을 가운뎃점(·)으로 나열하지 마세요. 한자를 쓰지 마세요.

각 기획안은 이 형식으로 쓰세요:

## (제목)
- **요청**: 원장님이 뭐라고 하셨는지 그대로
- **형식**: 릴스 / 피드 / 캐러셀 중 하나와 예상 길이
- **근거**: 어떤 데이터를 보고 이렇게 만드는지 (실제 숫자 인용)
- **촬영**: 무엇을 어떻게 찍을지 두세 줄
- **캡션 초안**: 그대로 올려도 되는 수준으로. 아래 말투를 그대로 따르세요
- **해시태그**: 성과가 확인된 태그 위주로 5~7개

말투 규칙은 **캡션 초안에만** 적용합니다. 근거와 촬영 설명은 차분한 보고체로 쓰세요.

{voice}"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="hssup-main")
    parser.add_argument("--days", type=int, default=60)
    args = parser.parse_args()

    pending = trends_sync.fetch_requests(urgency="now")
    if not pending:
        print("지금 처리할 요청이 없습니다.")
        return 0
    print(f"요청 {len(pending)}건 처리 시작")

    cfg = load_channel(args.channel)
    ig_cfg = cfg["instagram"]
    business_id = os.environ.get(ig_cfg["business_id_env"])
    token = os.environ.get(ig_cfg["token_env"])
    if not business_id or not token:
        print(f"{args.channel}: instagram 환경변수가 없습니다.")
        return 1

    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)
    account = feed.fetch_account(business_id, token)
    media = feed.fetch_media(business_id, token, since)
    stats = feed.summarize(account, media)

    def brief(m: dict, cap: int = 300) -> dict:
        out = {
            "날짜": m["_when"].astimezone(feed.KST).strftime("%Y-%m-%d"),
            "형식": m.get("media_product_type"),
            "좋아요": m.get("like_count"),
            "댓글": m.get("comments_count"),
        }
        if m.get("reach") is not None:
            out |= {"도달": m["reach"], "저장": m.get("saved"), "공유": m.get("shares")}
        out["캡션"] = (m.get("caption") or "").replace("\n", " ")[:cap]
        return out

    payload = {
        "원장님_요청": [r["body"] for r in pending],
        "계정": account.get("username"),
        "형식별_도달": stats.get("by_type_reach"),
        "평균_도달": stats.get("avg_reach"),
        "평균_저장": stats.get("avg_saved"),
        "해시태그_성과": stats.get("top_hashtags"),
        "잘된_게시물": [brief(m, 400) for m in stats.get("top_posts", [])],
        "안된_게시물": [brief(m) for m in stats.get("bottom_posts", [])],
    }
    business = trends_sync.fetch_context("business")
    if business:
        payload["사업_상황"] = business

    client = llm.client()
    resp = client.messages.create(
        model=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
        max_tokens=8000,
        system=SYSTEM.format(name=cfg["name"], voice=HSSUP_VOICE) + brand.marketing_block(),
        messages=[{"role": "user", "content": attachments.requests_content(
            json.dumps(payload, ensure_ascii=False, indent=2), pending)}],
    )
    plan = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not plan:
        print(f"기획안이 비어 있습니다 (stop_reason={resp.stop_reason}).")
        return 1

    now = dt.datetime.now(feed.KST)
    out_path = ROOT / "output" / "analysis" / "request" / f"{now:%Y-%m-%d-%H%M}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(plan, encoding="utf-8")
    print(f"기획안 저장: {out_path}")

    try:
        # 요청 기획은 주간 기획과 따로 쌓입니다. 같은 날 여러 번 요청할 수 있으므로
        # target 에 시각을 넣어 덮어쓰기에 걸리지 않게 합니다.
        trends_sync.create_report(
            kind="request",
            target=f"{args.channel}-{now:%H%M}",
            title=f"요청 기획 {len(pending)}건 ({now:%m월 %d일 %H:%M})",
            body=plan,
            period_days=args.days,
        )
        print("앱에 등록 완료")
        trends_sync.close_requests([r["id"] for r in pending])
        print(f"요청 {len(pending)}건 처리 완료로 표시")
    except Exception as e:
        print(f"  ! 앱 등록 실패: {e}")
        return 1

    tg_cfg = cfg.get("telegram")
    bot_token = os.environ.get(tg_cfg["bot_token_env"]) if tg_cfg else None
    if bot_token:
        text = f"⚡ 요청하신 콘텐츠 기획안\n\n" + plan
        for i in range(0, len(text), 3900):
            telegram.notify(bot_token, str(tg_cfg["chat_id"]), text[i : i + 3900])
        print("텔레그램 전송 완료")

    return 0


if __name__ == "__main__":
    sys.exit(main())
